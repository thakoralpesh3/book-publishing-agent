"""Metadata Intelligence Engine
Generates comprehensive, platform-compliant listing metadata for both Amazon KDP and Flipkart Seller Hub.
"""

import json
import logging
import re
from typing import Dict, Any, List, Optional
import config
from core.gemini_engine import GeminiBookEngine
from core.preflight_validator import generate_valid_isbn13, sanitize_kdp_html, validate_and_clean_kdp_keywords

logger = logging.getLogger(__name__)

class MetadataEngine:
    def __init__(self, gemini_engine: Optional[GeminiBookEngine] = None):
        self.engine = gemini_engine or GeminiBookEngine()

    def generate_all_metadata(
        self,
        book_data: Dict[str, Any],
        page_count: Optional[int] = None,
        trim_size: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generates unified metadata packages for Amazon KDP and Flipkart."""
        title = book_data.get("title", "")
        subtitle = book_data.get("subtitle", "")
        author = book_data.get("author", config.DEFAULT_AUTHOR_NAME)
        publisher = book_data.get("publisher", config.DEFAULT_PUBLISHER_NAME)
        genre = book_data.get("genre", "Self-Help / Business")
        hook = book_data.get("hook_summary", "")
        pages = page_count or book_data.get("estimated_pages", 120)
        t_size = trim_size or book_data.get("trim_size") or config.AMAZON_KDP["DEFAULT_TRIM_SIZE"]

        amazon_meta = self._generate_amazon_kdp_metadata(
            title=title,
            subtitle=subtitle,
            author=author,
            publisher=publisher,
            genre=genre,
            hook=hook,
            page_count=pages,
            trim_size=t_size
        )

        flipkart_meta = self._generate_flipkart_metadata(
            title=title,
            subtitle=subtitle,
            author=author,
            publisher=publisher,
            genre=genre,
            hook=hook,
            page_count=pages,
            amazon_meta=amazon_meta,
            trim_size=t_size
        )

        unified_dossier = {
            "book_title": title,
            "book_subtitle": subtitle,
            "author": author,
            "publisher": publisher,
            "page_count": pages,
            "amazon_kdp": amazon_meta,
            "flipkart": flipkart_meta,
            "publishing_tips": {
                "amazon_kdp_checklist": [
                    "Sign in to https://kdp.amazon.com/ with your Amazon account.",
                    "Click '+ Create' and choose 'Kindle eBook' or 'Paperback'.",
                    "Copy/Paste the Title, Subtitle, and Author Name.",
                    "Paste the formatted HTML Description directly into the KDP Description box (Source view or Rich text).",
                    "Choose 'I own the copyright and I hold the necessary publishing rights'.",
                    "Add the 7 exact Backend Keywords provided in this dossier.",
                    "Select the 3 Browse Categories suggested.",
                    "Upload the manuscript interior PDF/EPUB and Book Cover.",
                    "Confirm the Print Previewer check.",
                    "Set pricing: Enroll in KDP Select (70% royalty) and set INR/USD list prices."
                ],
                "flipkart_seller_checklist": [
                    "Sign in to https://seller.flipkart.com/.",
                    "Go to Listings -> My Listings -> Add New Listings.",
                    "Select Vertical: 'Books'.",
                    "Enter ISBN-13 (Required by Flipkart to authenticate physical books).",
                    "Upload the generated Flipkart Bulk Catalog Excel file (.xlsx) or copy/paste fields into single listing.",
                    "Enter HSN Code: 4901.10.00 (Printed books attract 0% GST in India).",
                    "Enter Package Dimensions (Length, Breadth, Height) and Weight (grams) from this dossier.",
                    "Upload Front Cover, Back Cover, and Inside Sample images.",
                    "Set MRP and Selling Price (taking into account Flipkart commission and shipping fee)."
                ],
                "pod_aggregator_pathway": [
                    "Alternatively, upload your manuscript PDF & cover to Notion Press (notionpress.com) or Pothi (pothi.com).",
                    "They provide print-on-demand fulfillment and auto-distribute directly to Flipkart and Amazon India simultaneously.",
                    "Zero inventory required: When a customer orders on Flipkart, the distributor prints and ships the copy!"
                ]
            }
        }

        # Save dossier to book directory
        book_dir = book_data.get("book_dir")
        if book_dir:
            out_file = config.OUTPUT_DIR / book_data.get("slug", "book") / "listing_metadata.json"
            out_file.parent.mkdir(parents=True, exist_ok=True)
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(unified_dossier, f, indent=2)

        return unified_dossier

    def _generate_amazon_kdp_metadata(
        self,
        title: str,
        subtitle: str,
        author: str,
        publisher: str,
        genre: str,
        hook: str,
        page_count: int,
        trim_size: str = "6x9"
    ) -> Dict[str, Any]:
        """Generates Amazon KDP specific details."""
        sys_prompt = (
            "You are a leading Amazon KDP conversion copywriter and SEO publishing specialist. "
            "Generate high-CTR, policy-compliant Amazon KDP metadata."
        )

        prompt = f"""
Book Title: "{title}"
Subtitle: "{subtitle}"
Author: "{author}"
Genre: "{genre}"
Hook: "{hook}"
Page Count: {page_count}
Trim Size: {trim_size}

Generate the exact metadata for Amazon KDP according to Amazon's strict policies:
1. Formatted HTML Book Description: Under 4,000 characters. ONLY use allowed tags (<b>, <i>, <h3>, <p>, <ul>, <li>, <blockquote>, <hr>).
   Include: A powerful headline, problem/curiosity hook, bolded benefit bullet points, who this is for, and a call to action.
2. Exactly 7 Backend Search Keywords: High-intent, competitive search terms that do NOT duplicate words already in the title/subtitle.
3. 3 Amazon Browse Categories (with full hierarchy, e.g. "Nonfiction > Self-Help > Personal Growth").
4. Suggested Pricing:
   - India (INR): eBook price, Paperback MRP.
   - US (USD): eBook price, Paperback MRP.

Return JSON with this schema:
{{
    "title": "{title}",
    "subtitle": "{subtitle}",
    "author_first_name": "First name",
    "author_last_name": "Last name",
    "html_description": "Clean HTML formatted description with <b>, <h3>, <p>, <ul><li>",
    "plain_description": "Plain text version of description",
    "backend_keywords": [
        "keyword phrase 1",
        "keyword phrase 2",
        "keyword phrase 3",
        "keyword phrase 4",
        "keyword phrase 5",
        "keyword phrase 6",
        "keyword phrase 7"
    ],
    "browse_categories": [
        "Category 1 hierarchy",
        "Category 2 hierarchy",
        "Category 3 hierarchy"
    ],
    "bisac_codes": [
        "BISAC 1 (e.g. SEL021000 SELF-HELP / Personal Growth / General)",
        "BISAC 2",
        "BISAC 3"
    ],
    "pricing": {{
        "inr": {{
            "ebook_list_price": 199,
            "paperback_list_price": 499,
            "currency": "INR",
            "royalty_plan": "70%"
        }},
        "usd": {{
            "ebook_list_price": 4.99,
            "paperback_list_price": 14.99,
            "currency": "USD",
            "royalty_plan": "70%"
        }}
    }},
    "print_specifications": {{
        "trim_size": "{trim_size}",
        "paper_type": "Black & white interior with white paper",
        "bleed": "No Bleed",
        "cover_finish": "Matte",
        "page_count": {page_count}
    }}
}}
"""
        raw_meta = self.engine.generate_json(prompt, system_instruction=sys_prompt)

        # Post-Processing: Ironclad Zero-Mistake Sanitization
        raw_desc = raw_meta.get("html_description") or raw_meta.get("plain_description", "")
        raw_meta["html_description"] = sanitize_kdp_html(raw_desc, max_chars=3900)

        # Optimize and clean all 7 keyword slots
        raw_keywords = raw_meta.get("backend_keywords", [])
        raw_meta["backend_keywords"] = validate_and_clean_kdp_keywords(raw_keywords, title=title, subtitle=subtitle)

        # Ensure print specifications match exact compile parameters
        if "print_specifications" not in raw_meta or not isinstance(raw_meta["print_specifications"], dict):
            raw_meta["print_specifications"] = {}
        raw_meta["print_specifications"]["trim_size"] = trim_size
        raw_meta["print_specifications"]["page_count"] = page_count
        raw_meta["print_specifications"]["paper_type"] = "Black & white interior with white paper"
        raw_meta["print_specifications"]["bleed"] = "No Bleed"
        raw_meta["print_specifications"]["cover_finish"] = "Matte"

        return raw_meta

    def _generate_flipkart_metadata(
        self,
        title: str,
        subtitle: str,
        author: str,
        publisher: str,
        genre: str,
        hook: str,
        page_count: int,
        amazon_meta: Dict[str, Any],
        trim_size: str = "6x9"
    ) -> Dict[str, Any]:
        """Generates Flipkart Seller Hub specific catalog attributes."""
        # Calculate physical dimensions dynamically based on trim size
        dim_specs = config.FLIPKART["DIMENSIONS_CM"].get(trim_size, config.FLIPKART["DIMENSIONS_CM"]["6x9"])
        thickness_cm = round(0.4 + (page_count * 0.0057), 1)  # approx 1.2 - 2.0 cm
        weight_grams = int(config.FLIPKART["COVER_WEIGHT_GRAMS"] + (page_count * config.FLIPKART["WEIGHT_GRAMS_PER_PAGE"]))

        clean_slug = re.sub(r"[^\w]", "", title.upper())[:6]
        sku_id = f"FP-BK-{clean_slug}-01"

        # Mathematical EAN-13 Mod-10 Checksum ISBN Generation
        isbn_seed = abs(hash(f"{title}_{author}_{page_count}"))
        valid_isbn_13 = generate_valid_isbn13(prefix="97893", seed=isbn_seed)

        sys_prompt = (
            "You are an Indian e-commerce listing specialist for Flipkart Seller Hub Books vertical. "
            "Generate accurate product attributes and bullet points optimized for Flipkart mobile conversions."
        )

        prompt = f"""
Book Title: "{title}"
Subtitle: "{subtitle}"
Author: "{author}"
Publisher: "{publisher}"
Genre: "{genre}"
Page Count: {page_count}
Trim Size: {trim_size}

Generate Flipkart listing data:
1. 4-6 Key Highlights (Bullet points displayed prominently on Flipkart app).
2. Clean Product Description / Synopsis (250-400 words).
3. 5 Flipkart Search Keywords.
4. Suggested Flipkart Selling Price (taking into account MRP ₹{amazon_meta.get('pricing', {}).get('inr', {}).get('paperback_list_price', 499)} and 20-30% discount).

Return JSON with this schema:
{{
    "highlights": [
        "Language: English",
        "Binding: Paperback",
        "Publisher: {publisher}",
        "Genre: {genre}",
        "Key Feature 1",
        "Key Feature 2"
    ],
    "synopsis": "Full product description for Flipkart listing",
    "search_keywords": ["keyword 1", "keyword 2", "keyword 3", "keyword 4", "keyword 5"],
    "flipkart_category": "Books > Non-Fiction > Self-Help",
    "mrp": {amazon_meta.get('pricing', {}).get('inr', {}).get('paperback_list_price', 499)},
    "selling_price": {int(amazon_meta.get('pricing', {}).get('inr', {}).get('paperback_list_price', 499) * 0.78)}
}}
"""
        raw_flipkart = self.engine.generate_json(prompt, system_instruction=sys_prompt)

        # Clean highlights to be concise bullet points (< 120 chars each)
        raw_highlights = raw_flipkart.get("highlights", [])
        clean_highlights = []
        for h in raw_highlights:
            clean_h = str(h).strip().replace("\n", " ")
            if clean_h and len(clean_h) <= 120:
                clean_highlights.append(clean_h)
        if len(clean_highlights) < 3:
            clean_highlights = [
                f"Language: {config.FLIPKART['DEFAULT_LANGUAGE']}",
                f"Binding: {config.FLIPKART['DEFAULT_BINDING']}",
                f"Publisher: {publisher}",
                f"Format: {trim_size} Print Edition ({page_count} Pages)"
            ]

        # Clean synopsis
        synopsis = raw_flipkart.get("synopsis", "").strip()
        if len(synopsis) < 100:
            synopsis = f"{title}: {subtitle}. A comprehensive {genre} book by {author}, published by {publisher}. Featuring actionable guidance across {page_count} pages."

        mrp = raw_flipkart.get("mrp") or amazon_meta.get("pricing", {}).get("inr", {}).get("paperback_list_price", 499)
        selling_price = raw_flipkart.get("selling_price") or int(mrp * 0.78)
        if selling_price > mrp:
            selling_price = mrp

        return {
            "sku_id": sku_id,
            "isbn_13": valid_isbn_13,
            "vertical": config.FLIPKART["VERTICAL"],
            "title": title,
            "subtitle": subtitle,
            "author": author,
            "publisher": publisher,
            "edition": "1st Edition",
            "publication_year": 2026,
            "language": config.FLIPKART["DEFAULT_LANGUAGE"],
            "binding": config.FLIPKART["DEFAULT_BINDING"],
            "number_of_pages": page_count,
            "trim_size": trim_size,
            "flipkart_category": raw_flipkart.get("flipkart_category", "Books > Non-Fiction"),
            "hsn_code": config.FLIPKART["HSN_CODE"],
            "gst_rate_percent": config.FLIPKART["GST_RATE_PERCENT"],
            "mrp_inr": mrp,
            "selling_price_inr": selling_price,
            "procurement_sla_days": config.FLIPKART["DEFAULT_PROCUREMENT_SLA_DAYS"],
            "dimensions_cm": {
                "length": dim_specs["length"],
                "breadth": dim_specs["breadth"],
                "height": thickness_cm
            },
            "weight_grams": weight_grams,
            "highlights": clean_highlights[:6],
            "synopsis": synopsis,
            "search_keywords": raw_flipkart.get("search_keywords", ["printed book", "paperback", genre.lower()])
        }
