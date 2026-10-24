"""Configuration settings for Book Publishing Agent (PublisheR AI)
Supports Amazon KDP & Flipkart Seller Hub specifications and validation rules.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Fallback API keys from known workspace paths if not set in local .env
def _get_api_key():
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    for fallback_env in [
        Path("/home/alpesh/youtube-agent/.env"),
        Path("/home/alpesh/executive_os/.env"),
    ]:
        if fallback_env.exists():
            with open(fallback_env, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("GEMINI_API_KEY="):
                        extracted = line.strip().split("=", 1)[1].strip()
                        if extracted:
                            return extracted
    return ""

GEMINI_API_KEY = _get_api_key()
DEFAULT_MODELS = [
    "gemini-4-argon",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.8-flash",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-flash-latest"
]
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-4-argon")

GEMINI_4_ARGON_SPECS = {
    "model_name": "gemini-4-argon",
    "display_name": "Gemini 4 Argon",
    "context_window_tokens": 1048576,
    "max_output_tokens": 32768,
    "architecture": "Next-Gen Long-Horizon Multimodal Reasoning Engine",
    "supported_features": [
        "Multi-Section Deep Narrative Exposition",
        "Tactical 3-Tier Step-by-Step Action Frameworks",
        "Field Case Studies & Cognitive Mental Models",
        "Executive Reader Worksheets & Self-Audit Exercises",
        "Algorithmic Amazon KDP & Flipkart Copywriting"
    ]
}

# Output directory for books, covers, metadata, and spreadsheets
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", str(BASE_DIR / "output")))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Data directory for persistent queues, state, and cache
DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE_DIR / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Amazon KDP Specifications
AMAZON_KDP = {
    "MAX_TITLE_CHARS": 200,
    "MAX_SUBTITLE_CHARS": 200,
    "MAX_DESCRIPTION_CHARS": 4000,
    "KEYWORD_COUNT": 7,
    "MAX_KEYWORD_CHARS": 50,
    "ALLOWED_HTML_TAGS": [
        "<b>", "</b>", "<i>", "</i>", "<u>", "</u>", "<em>", "</em>",
        "<strong>", "</strong>", "<h3>", "</h3>", "<h4>", "</h4>",
        "<h5>", "</h5>", "<h6>", "</h6>", "<p>", "</p>", "<ul>", "</ul>",
        "<ol>", "</ol>", "<li>", "</li>", "<blockquote>", "</blockquote>",
        "<hr>", "<br>", "<br/>"
    ],
    "DEFAULT_MARKETPLACE": "amazon.in",
    "ROYALTY_PLANS": ["35%", "70%"],
    "TRIM_SIZES": {
        "6x9": {"width_in": 6.0, "height_in": 9.0, "width_pt": 432.0, "height_pt": 648.0},
        "5.5x8.5": {"width_in": 5.5, "height_in": 8.5, "width_pt": 396.0, "height_pt": 612.0},
        "5x8": {"width_in": 5.0, "height_in": 8.0, "width_pt": 360.0, "height_pt": 576.0},
        "8.5x11": {"width_in": 8.5, "height_in": 11.0, "width_pt": 612.0, "height_pt": 792.0},
    },
    "DEFAULT_TRIM_SIZE": "6x9",
    "BLEED_INCHES": 0.125,
    "MARGINS_INCHES": {
        "inside_gutter": 0.75,  # Gutter margin for binding
        "outside": 0.5,
        "top": 0.6,
        "bottom": 0.6,
    },
    "SPINE_PAGE_THICKNESS": {
        "white_paper": 0.002252,   # inches per page
        "cream_paper": 0.0025,     # inches per page
        "color_paper": 0.002347,   # inches per page
    }
}

# Flipkart Seller Hub Specifications
FLIPKART = {
    "VERTICAL": "Books",
    "HSN_CODE": "4901.10.00",      # Printed books, brochures & leaflets
    "GST_RATE_PERCENT": 0,          # Printed books are Nil-rated / 0% GST in India
    "DEFAULT_BINDING": "Paperback",
    "BINDING_OPTIONS": ["Paperback", "Hardcover", "Board Book", "Spiral"],
    "DEFAULT_LANGUAGE": "English",
    "DIMENSIONS_CM": {
        "6x9": {"length": 22.86, "breadth": 15.24, "thickness_base": 1.2},
        "5.5x8.5": {"length": 21.59, "breadth": 13.97, "thickness_base": 1.2},
        "8.5x11": {"length": 27.94, "breadth": 21.59, "thickness_base": 1.0},
    },
    "WEIGHT_GRAMS_PER_PAGE": 1.8,   # Approx paper weight (80 GSM) + cover cardstock (approx 40g)
    "COVER_WEIGHT_GRAMS": 40.0,
    "DEFAULT_PROCUREMENT_SLA_DAYS": 2,
    "CATEGORY_HIERARCHY": [
        "Books > Children's Books > Activity, Crafts & Games",
        "Books > Business & Economics > Personal Finance & Investing",
        "Books > Literature & Fiction > General",
        "Books > Business & Economics > Management & Leadership",
        "Books > Self-Help > Personal Growth",
        "Books > Computing, Internet & Digital Media > Programming",
        "Books > Health, Fitness & Nutrition",
        "Books > Academic & Professional > Reference"
    ]
}

# Book Types and Architectural Blueprints
BOOK_TYPES = {
    "standard": "Standard Non-Fiction (Business, Wealth, Self-Help, Guides)",
    "activity_drawing": "Kids Drawing & Activity Book (Step-by-step tutorials, practice boxes)",
    "workbook_journal": "Interactive Workbook & Journal (Prompts, exercises, trackers)"
}

# General Publishing Defaults
DEFAULT_PUBLISHER_NAME = os.environ.get("DEFAULT_PUBLISHER", "Independent Publishing Press")
DEFAULT_AUTHOR_NAME = os.environ.get("DEFAULT_AUTHOR", "Alpesh Patel")

