"""Unit tests for Daily Trend Radar and specialized Kids Drawing & Wealth Book generation.
"""

import unittest
from pathlib import Path
from fastapi.testclient import TestClient

import config
from core.trend_radar import TrendRadar
from core.manuscript_compiler import ManuscriptCompiler
from core.cover_generator import CoverGenerator
from ui.app import app

class TestDailyTrendsAndDrawing(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.radar = TrendRadar()

    def test_01_trend_radar_discovery(self):
        """Tests that TrendRadar initializes and retrieves all curated trends."""
        trends = self.radar.get_trends(category="all")
        self.assertGreaterEqual(len(trends), 5)
        
        # Verify presence of key user-requested niches
        kids_trends = [t for t in trends if t.get("category") == "kids"]
        wealth_trends = [t for t in trends if t.get("category") == "wealth"]
        
        self.assertTrue(any("drawing" in t.get("id") or "tracing" in t.get("id") for t in kids_trends))
        self.assertTrue(any("rich" in t.get("id") or "wealth" in t.get("id") for t in wealth_trends))

    def test_02_trend_filtering_and_retrieval(self):
        """Tests filtering by category and search keywords."""
        kids = self.radar.get_trends(category="kids")
        for t in kids:
            self.assertEqual(t.get("category"), "kids")

        search_res = self.radar.get_trends(search_query="drawing")
        self.assertGreaterEqual(len(search_res), 1)
        self.assertTrue(any("drawing" in t.get("title").lower() for t in search_res))

        trend_obj = self.radar.get_trend_by_id("kids-drawing-animals-masterclass")
        self.assertIsNotNone(trend_obj)
        self.assertEqual(trend_obj.get("book_type"), "activity_drawing")
        self.assertEqual(trend_obj.get("suggested_trim_size"), "8.5x11")

    def test_03_drawing_canvas_and_8x11_pdf_compilation(self):
        """Tests compiling an 8.5x11 drawing activity book with practice canvases."""
        compiler = ManuscriptCompiler(trim_size="8.5x11")
        test_book = {
            "title": "Kids Fun Drawing Book",
            "subtitle": "Step by Step Animals",
            "author": "Test Author",
            "publisher": "Test Publisher",
            "slug": "test_kids_drawing",
            "book_type": "activity_drawing",
            "book_dir": str(config.OUTPUT_DIR / "test_kids_drawing"),
            "chapters": [
                {
                    "chapter_number": 1,
                    "title": "Drawing Cute Puppies",
                    "content": (
                        "# Chapter 1: Drawing Cute Puppies\n\n"
                        "Welcome to drawing puppies! Puppies are full of joy.\n\n"
                        "### Lesson 1: Little Beagle\n"
                        "- Shapes: 1 Oval, 2 Triangles\n"
                        "1. Step 1: Draw a soft oval for the puppy head.\n"
                        "2. Step 2: Add two floppy ears.\n"
                        "3. Step 3: Draw a happy tail!\n\n"
                        "[DRAWING_PRACTICE_GRID: Little Beagle Puppy]\n\n"
                        "Now color your puppy with bright crayons!"
                    )
                }
            ],
            "front_back": {
                "dedication": "For all future master artists!",
                "preface": "Welcome to drawing! Have fun and be creative."
            }
        }
        test_pdf = Path("/tmp/test_kids_drawing_interior.pdf")
        res = compiler.compile_pdf(test_book, output_path=test_pdf)
        self.assertTrue(test_pdf.exists())
        self.assertEqual(res["trim_size"], "8.5x11")
        self.assertGreater(res["page_count"], 0)
        self.assertAlmostEqual(res["width_inches"], 8.5, places=1)
        self.assertAlmostEqual(res["height_inches"], 11.0, places=1)

    def test_04_adaptive_cover_themes(self):
        """Tests that CoverGenerator auto-themes kids and wealth books."""
        gen_85x11 = CoverGenerator(trim_size="8.5x11")
        kids_cover = Path("/tmp/test_kids_cover.jpg")
        gen_85x11.generate_front_cover_image(
            title="Kids Drawing Masterclass",
            subtitle="Step by Step Animals for Ages 4-8",
            author="Test Artist",
            output_path=kids_cover
        )
        self.assertTrue(kids_cover.exists())
        self.assertGreater(kids_cover.stat().st_size, 50000)

        gen_6x9 = CoverGenerator(trim_size="6x9")
        wealth_cover = Path("/tmp/test_wealth_cover.jpg")
        gen_6x9.generate_front_cover_image(
            title="How to Get Rich in the Modern Economy",
            subtitle="21 Rules for Wealth & Cash Flow",
            author="Wealth Master",
            output_path=wealth_cover
        )
        self.assertTrue(wealth_cover.exists())
        self.assertGreater(wealth_cover.stat().st_size, 50000)

    def test_05_api_trends_endpoints(self):
        """Tests FastAPI REST endpoints /api/trends."""
        resp = self.client.get("/api/trends")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "success")
        self.assertGreaterEqual(data.get("total", 0), 5)

        resp_cat = self.client.get("/api/trends?category=kids")
        self.assertEqual(resp_cat.status_code, 200)
        for t in resp_cat.json().get("trends", []):
            self.assertEqual(t.get("category"), "kids")

if __name__ == "__main__":
    unittest.main()
