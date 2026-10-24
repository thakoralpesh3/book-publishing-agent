"""Automated Test Suite for PublisheR AI
Verifies book assembly, PDF typesetting, spine math, metadata generation, and catalog exports.
"""

import os
import sys
import unittest
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import config
from core.book_writer import BookWriter
from core.manuscript_compiler import ManuscriptCompiler
from core.cover_generator import CoverGenerator
from core.catalog_exporter import CatalogExporter
from uploader.flipkart_assistant import FlipkartAssistant

class TestBookPublishingAgent(unittest.TestCase):
    def setUp(self):
        self.test_dir = PROJECT_ROOT / "output" / "test_book_run"
        self.test_dir.mkdir(parents=True, exist_ok=True)

        self.sample_book_data = {
            "title": "The Focused Mind",
            "subtitle": "How to Master Deep Concentration in an Age of Distraction",
            "author": "Alpesh Patel",
            "publisher": "InspireBooks Press",
            "slug": "the_focused_mind",
            "book_dir": str(self.test_dir),
            "genre": "Self-Help / Productivity",
            "hook_summary": "A proven framework for reclaiming focus and achieving exponential output.",
            "front_back": {
                "dedication": "Dedicated to all seekers of intentional focus.",
                "preface": "In a noisy world, concentration is the ultimate superpower. This book is your blueprint.",
                "author_bio": "Alpesh Patel is a technology strategist and researcher.",
                "review_cta": "If this guide brought value to your work, please take 60 seconds to leave an honest review on Amazon or Flipkart!"
            },
            "chapters": [
                {
                    "chapter_number": 1,
                    "title": "The Illusion of Multitasking",
                    "content": "# Chapter 1: The Illusion of Multitasking\n\n## The Cost of Context Switching\nEvery time you switch tabs, your brain pays a cognitive tax.\n\n> Focus is a muscle that compounds when trained daily.\n\n- Identify your top distraction triggers.\n- Create a 90-minute uninterrupted work block.\n\n1. First step: Put your phone in another room.\n2. Second step: Use full-screen mode."
                },
                {
                    "chapter_number": 2,
                    "title": "Building Your Focus Fortress",
                    "content": "# Chapter 2: Building Your Focus Fortress\n\n## Designing Your Environment\nYour environment dictates your willpower reserve.\n\n- Clear your physical desk.\n- Eliminate audio interruptions with binaural beats."
                }
            ]
        }

    def test_01_config_rules(self):
        """Verify Amazon KDP & Flipkart configuration constants."""
        self.assertEqual(config.AMAZON_KDP["KEYWORD_COUNT"], 7)
        self.assertIn("<b>", config.AMAZON_KDP["ALLOWED_HTML_TAGS"])
        self.assertEqual(config.FLIPKART["HSN_CODE"], "4901.10.00")
        self.assertEqual(config.FLIPKART["GST_RATE_PERCENT"], 0)

    def test_02_spine_calculation(self):
        """Verify exact spine width calculation for Paperback printing."""
        cover_gen = CoverGenerator(trim_size="6x9", paper_type="white_paper")
        # 100 pages * 0.002252 = 0.2252 inches
        spine_100 = cover_gen.calculate_spine_width(100)
        self.assertAlmostEqual(spine_100, 0.2252, places=3)

        # Minimum spine clamp
        spine_min = cover_gen.calculate_spine_width(10)
        self.assertGreaterEqual(spine_min, 0.06)

    def test_03_manuscript_compiler_pdf(self):
        """Verify ReportLab compiles valid interior PDF with expected pages."""
        compiler = ManuscriptCompiler(trim_size="6x9")
        out_pdf = self.test_dir / "manuscript_interior.pdf"

        res = compiler.compile_pdf(self.sample_book_data, output_path=out_pdf)
        self.assertTrue(out_pdf.exists())
        self.assertGreater(res["page_count"], 4)
        self.assertEqual(res["trim_size"], "6x9")

    def test_04_cover_generator(self):
        """Verify front cover JPG and full-wrap PDF generation."""
        cover_gen = CoverGenerator(trim_size="6x9")
        front_jpg = self.test_dir / "cover_front.jpg"
        cover_wrap_pdf = self.test_dir / "cover_full_wrap.pdf"

        # Generate front cover
        cover_gen.generate_front_cover_image(
            title=self.sample_book_data["title"],
            subtitle=self.sample_book_data["subtitle"],
            author=self.sample_book_data["author"],
            output_path=front_jpg
        )
        self.assertTrue(front_jpg.exists())
        self.assertGreater(front_jpg.stat().st_size, 50000) # Should be substantial JPG

        # Generate full wrap PDF
        wrap_res = cover_gen.generate_full_wrap_pdf(
            book_data=self.sample_book_data,
            page_count=64,
            front_cover_img_path=front_jpg,
            output_pdf_path=cover_wrap_pdf
        )
        self.assertTrue(cover_wrap_pdf.exists())
        self.assertGreater(wrap_res["total_width_inches"], 12.0) # 2 * 6" + spine + bleed > 12"

    def test_05_catalog_exporter_excel_and_markdown(self):
        """Verify Flipkart bulk catalog Excel spreadsheet and Amazon Markdown generation."""
        exporter = CatalogExporter()

        sample_dossier = {
            "book_title": self.sample_book_data["title"],
            "book_subtitle": self.sample_book_data["subtitle"],
            "author": self.sample_book_data["author"],
            "publisher": self.sample_book_data["publisher"],
            "page_count": 64,
            "amazon_kdp": {
                "title": self.sample_book_data["title"],
                "subtitle": self.sample_book_data["subtitle"],
                "author_first_name": "Alpesh",
                "author_last_name": "Patel",
                "html_description": "<h3>Master Your Focus</h3><p>Stop procrastinating today.</p><ul><li>Framework 1</li></ul>",
                "backend_keywords": ["deep focus", "mindset reset", "beat procrastination", "productivity habits", "mental models", "time mastery", "flow state"],
                "browse_categories": ["Nonfiction > Self-Help > Personal Growth", "Business > Productivity"],
                "pricing": {"inr": {"ebook_list_price": 199, "paperback_list_price": 499}, "usd": {"ebook_list_price": 4.99, "paperback_list_price": 14.99}},
                "print_specifications": {"trim_size": "6x9", "bleed": "No Bleed", "cover_finish": "Matte"}
            },
            "flipkart": {
                "sku_id": "FP-BK-FOCUS-01",
                "isbn_13": "9789381234567",
                "title": self.sample_book_data["title"],
                "author": self.sample_book_data["author"],
                "publisher": self.sample_book_data["publisher"],
                "hsn_code": "4901.10.00",
                "gst_rate_percent": 0,
                "mrp_inr": 499,
                "selling_price_inr": 389,
                "dimensions_cm": {"length": 22.86, "breadth": 15.24, "height": 1.4},
                "weight_grams": 220,
                "highlights": ["Language: English", "Binding: Paperback", "Publisher: InspireBooks Press", "Pages: 64", "Full Focus Method"],
                "synopsis": "A comprehensive practical guide to mastering deep focus and high performance.",
                "search_keywords": ["focus", "productivity", "study habits", "deep work", "discipline"]
            }
        }

        # Export all
        res = exporter.export_all(self.test_dir, sample_dossier)
        self.assertTrue(Path(res["flipkart_excel"]).exists())
        self.assertTrue(Path(res["amazon_markdown"]).exists())
        self.assertTrue(Path(res["pod_manifest"]).exists())

        # Validate Flipkart compliance
        assistant = FlipkartAssistant()
        # Save listing_metadata.json for validator
        with open(self.test_dir / "listing_metadata.json", "w", encoding="utf-8") as f:
            import json
            json.dump(sample_dossier, f)

        val = assistant.validate_flipkart_listing(self.test_dir)
        self.assertTrue(val["valid"], f"Flipkart validation failed with issues: {val['issues']}")
        self.assertEqual(len(val["issues"]), 0)

    def test_06_gemini_4_argon_model_config(self):
        """Verify Gemini 4 Argon model configuration and specs."""
        self.assertEqual(config.GEMINI_MODEL, "gemini-4-argon")
        self.assertIn("gemini-4-argon", config.DEFAULT_MODELS)
        self.assertEqual(config.DEFAULT_MODELS[0], "gemini-4-argon")
        self.assertEqual(config.GEMINI_4_ARGON_SPECS["context_window_tokens"], 1048576)
        self.assertEqual(config.GEMINI_4_ARGON_SPECS["max_output_tokens"], 32768)

if __name__ == "__main__":
    unittest.main()
