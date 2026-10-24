"""Unit tests for 25-point Zero-Mistake Pre-Flight Verification Engine.
Validates Amazon KDP and Flipkart Seller Hub rejection-free rules.
"""

import unittest
from unittest.mock import MagicMock
import json
import shutil
from pathlib import Path
from fastapi.testclient import TestClient

import config
from core.preflight_validator import (
    calculate_isbn13_check_digit,
    validate_isbn13,
    generate_valid_isbn13,
    sanitize_kdp_html,
    validate_and_clean_kdp_keywords,
    PreflightValidator,
    KDP_ALLOWED_TAGS,
)
from core.metadata_engine import MetadataEngine
from core.catalog_exporter import CatalogExporter
from core.manuscript_compiler import ManuscriptCompiler
from core.cover_generator import CoverGenerator
from ui.app import app


def create_mock_gemini_engine():
    mock_eng = MagicMock()
    def mock_gen_json(prompt, *args, **kwargs):
        if "flipkart" in prompt.lower():
            return {
                "sku_id": "FP-BK-TEST-01",
                "isbn_13": "9789312345678",
                "binding": "Paperback",
                "language": "English",
                "publishing_year": 2026,
                "edition": "1st Edition",
                "highlights": [
                    "Step-by-step master lessons",
                    "Practical exercises and frameworks",
                    "Standard 0% GST HSN 4901",
                    "Action plans for readers"
                ],
                "synopsis": "A comprehensive publishing masterclass providing full action plans.",
                "mrp_inr": 399,
                "selling_price_inr": 299,
                "search_keywords": ["masterclass", "self improvement", "focus", "productivity guide"]
            }
        else:
            return {
                "title": "Zero Mistake Masterclass",
                "subtitle": "Complete Automated Publishing",
                "author_first_name": "Test",
                "author_last_name": "Author",
                "html_description": "<h3>Zero Mistake Masterclass</h3><p>Complete publishing guide.</p><ul><li>Feature 1</li><li>Feature 2</li></ul>",
                "backend_keywords": [
                    "masterclass guide",
                    "action blueprints",
                    "publishing system",
                    "success strategies",
                    "step by step methods",
                    "productivity mastery",
                    "practical skills"
                ],
                "browse_categories": [
                    "Nonfiction > Self-Help > Personal Growth",
                    "Business > Productivity"
                ],
                "pricing": {
                    "inr": {"ebook_list_price": 199, "paperback_list_price": 399},
                    "usd": {"ebook_list_price": 2.99, "paperback_list_price": 6.99}
                },
                "print_specifications": {
                    "trim_size": "6x9",
                    "bleed": "No Bleed",
                    "cover_finish": "Matte"
                }
            }
    mock_eng.generate_json.side_effect = mock_gen_json
    return mock_eng


class TestPreflightValidator(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.test_slug = "test_zero_mistake_book"
        cls.test_dir = config.OUTPUT_DIR / cls.test_slug
        cls.test_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        if cls.test_dir.exists():
            shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_01_isbn13_mod10_checksum_algorithm(self):
        """Tests mathematically rigorous EAN-13 Mod-10 checksum calculation and validation."""
        # Known standard ISBN-13: 978-0-306-40615-7
        self.assertEqual(calculate_isbn13_check_digit("978030640615"), 7)
        self.assertTrue(validate_isbn13("978-0-306-40615-7"))
        self.assertTrue(validate_isbn13("9780306406157"))

        # Invalid checksum should evaluate to False
        self.assertFalse(validate_isbn13("9780306406158"))
        self.assertFalse(validate_isbn13("12345"))  # too short
        self.assertFalse(validate_isbn13("978030640615A"))  # non-numeric

        # Test dynamic generator
        generated = generate_valid_isbn13()
        self.assertEqual(len(generated), 13)
        self.assertTrue(generated.startswith("978"))
        self.assertTrue(validate_isbn13(generated))

    def test_02_amazon_kdp_html_sanitizer(self):
        """Tests Amazon KDP HTML description sanitizer: allowed tags, attribute removal, length limit."""
        dirty_html = (
            "<p class='promo' style='color:red;'>Welcome to this <b>great</b> book!</p>"
            "<script>alert('hack');</script>"
            "<div id='wrapper'><h3>Key Features:</h3><ul><li>Item 1</li><li>Item 2</li></ul></div>"
            "<a href='http://spam.com'>Click here</a>"
        )
        clean = sanitize_kdp_html(dirty_html)

        # Disallowed tags like <script>, <div>, <a> must be stripped
        self.assertNotIn("<script>", clean)
        self.assertNotIn("<div>", clean)
        self.assertNotIn("<a", clean)

        # Attributes must be stripped
        self.assertNotIn("class=", clean)
        self.assertNotIn("style=", clean)
        self.assertNotIn("id=", clean)

        # Allowed tags must be retained in clean form
        self.assertIn("<p>", clean)
        self.assertIn("<b>great</b>", clean)
        self.assertIn("<h3>", clean)
        self.assertIn("<ul>", clean)
        self.assertIn("<li>", clean)

        # Test length enforcement <= 400
        super_long = "<p>" + ("word " * 1000) + "</p>"
        capped = sanitize_kdp_html(super_long, max_len=400)
        self.assertLessEqual(len(capped), 400)

    def test_03_amazon_kdp_backend_keywords_rules(self):
        """Tests that 7 backend keywords are strictly sanitized without buzzwords or title redundancy."""
        title = "How to Draw Cute Animals for Kids"
        dirty_keywords = [
            "how to draw cute animals",  # exact title duplicate -> stripped/cleaned
            "bestseller drawing guide",  # prohibited term "bestseller" -> removed
            "free coloring pages",       # prohibited term "free" -> removed
            "step by step sketching",
            "beginner art lessons",
            "cute cartoon doodles",
            "a" * 80,                    # exceeds 50 chars -> truncated
        ]

        cleaned_7 = validate_and_clean_kdp_keywords(dirty_keywords, title)

        self.assertEqual(len(cleaned_7), 7)
        for kw in cleaned_7:
            self.assertLessEqual(len(kw), 50)
            self.assertGreaterEqual(len(kw), 1)
            self.assertNotIn("bestseller", kw.lower())
            self.assertNotIn("free", kw.lower())

    def test_04_flipkart_dimensions_align_with_trim_size(self):
        """Tests that Flipkart dimensions in metadata dynamically adapt to 8.5x11 vs 6x9 trim size."""
        mock_engine = create_mock_gemini_engine()
        meta_engine = MetadataEngine(gemini_engine=mock_engine)

        sample_book_85 = {
            "title": "Drawing Animals Masterclass",
            "subtitle": "50 Steps for Kids",
            "author": "Art Master",
            "publisher": "Creative Press",
            "target_audience": "Kids 6-12",
            "topics": ["Drawing", "Art"],
            "slug": "sample_drawing_85",
            "book_type": "activity_drawing",
            "chapters": [{"title": "Ch 1", "word_count": 500, "scenes": []}]
        }

        # 8.5x11 trim size
        meta_85 = meta_engine.generate_all_metadata(sample_book_85, trim_size="8.5x11")
        fk_85 = meta_85["flipkart"]
        self.assertEqual(fk_85["dimensions_cm"]["length"], 27.94)
        self.assertEqual(fk_85["dimensions_cm"]["breadth"], 21.59)
        self.assertTrue(validate_isbn13(fk_85["isbn_13"]))
        self.assertEqual(fk_85["hsn_code"], "4901.10.00")
        self.assertEqual(fk_85["gst_rate_percent"], 0)

        # 6x9 trim size
        meta_69 = meta_engine.generate_all_metadata(sample_book_85, trim_size="6x9")
        fk_69 = meta_69["flipkart"]
        self.assertEqual(fk_69["dimensions_cm"]["length"], 22.86)
        self.assertEqual(fk_69["dimensions_cm"]["breadth"], 15.24)

    def test_05_manuscript_minimum_24_pages_guarantee(self):
        """Tests that ManuscriptCompiler guarantees >= 24 pages for KDP paperback compliance."""
        compiler = ManuscriptCompiler(trim_size="6x9")
        small_book = {
            "title": "Short Summary Guide",
            "subtitle": "Quick Reference",
            "author": "Quick Author",
            "publisher": "Quick Press",
            "slug": self.test_slug,
            "book_type": "standard",
            "book_dir": str(self.test_dir),
            "chapters": [
                {
                    "number": 1,
                    "title": "First Step",
                    "content": "This is a very short sample chapter content for testing pagination."
                }
            ]
        }
        pdf_path = compiler.compile_interior_pdf(small_book)
        self.assertTrue(pdf_path.exists())

        # Check page count
        validator = PreflightValidator(self.test_dir)
        page_count = validator._count_pdf_pages(pdf_path)
        self.assertGreaterEqual(page_count, 24)

    def test_06_complete_25_point_preflight_audit(self):
        """Tests end-to-end PreflightValidator 25-point audit execution and certification."""
        cover_gen = CoverGenerator(trim_size="6x9")
        test_book = {
            "title": "Zero Mistake Masterclass",
            "subtitle": "Complete Automated Publishing",
            "author": "Test Author",
            "publisher": "Test Publisher",
            "slug": self.test_slug,
            "book_type": "standard",
            "book_dir": str(self.test_dir),
            "chapters": [
                {
                    "number": i,
                    "title": f"Chapter {i}: Foundations of Success",
                    "content": "Detailed comprehensive text " * 50
                }
                for i in range(1, 4)
            ]
        }

        # Generate manuscript pdf
        compiler = ManuscriptCompiler(trim_size="6x9")
        interior_pdf = compiler.compile_interior_pdf(test_book)
        page_count = compiler.get_page_count(interior_pdf)

        # Generate front cover and full wrap cover
        front_jpg = self.test_dir / "cover_front.jpg"
        cover_wrap_pdf = self.test_dir / "cover_full_wrap.pdf"

        cover_gen.generate_front_cover_image(
            title=test_book["title"],
            subtitle=test_book["subtitle"],
            author=test_book["author"],
            output_path=front_jpg
        )
        cover_gen.generate_full_wrap_pdf(
            book_data=test_book,
            page_count=page_count,
            front_cover_img_path=front_jpg,
            output_pdf_path=cover_wrap_pdf
        )

        # Generate metadata with mock engine
        mock_engine = create_mock_gemini_engine()
        meta_engine = MetadataEngine(gemini_engine=mock_engine)
        metadata = meta_engine.generate_all_metadata(test_book, trim_size="6x9")

        # Export catalogs
        catalog_exp = CatalogExporter()
        catalog_exp.export_all_catalogs(self.test_dir, metadata)

        # Save metadata JSON and book_data.json
        (self.test_dir / "listing_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        (self.test_dir / "book_data.json").write_text(json.dumps(test_book, indent=2), encoding="utf-8")
        (self.test_dir / "manuscript.md").write_text("# Zero Mistake Masterclass\n\n" + ("Comprehensive chapter text covering publishing strategies and zero-rejection guidelines.\n\n" * 20), encoding="utf-8")

        # Run 25-point Pre-Flight Validator
        validator = PreflightValidator(self.test_dir)
        report = validator.run_full_audit()

        self.assertIn("zero_mistake_certified", report)
        self.assertIn("compliance_score", report)
        self.assertIn("passed_checks_count", report)
        self.assertGreaterEqual(report["passed_checks_count"], 23)
        self.assertEqual(report["issues_count"], 0)
        self.assertTrue(report["zero_mistake_certified"])
        self.assertEqual(report["compliance_score"], "100%")

        # Verify zero_mistake_audit.json created on disk
        audit_file = self.test_dir / "zero_mistake_audit.json"
        self.assertTrue(audit_file.exists())

        # Test API endpoint /api/validate/{slug}
        res = self.client.get(f"/api/validate/{self.test_slug}")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["zero_mistake_certified"])
        self.assertEqual(data["compliance_score"], "100%")
        self.assertTrue(data["platform_readiness"]["amazon_kdp_ready"])
        self.assertTrue(data["platform_readiness"]["flipkart_ready"])


if __name__ == "__main__":
    unittest.main()
