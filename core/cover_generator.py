"""Book Cover Generator
Generates high-resolution front cover (JPG) and full-wrap print cover (PDF)
with precise spine thickness calculations compliant with Amazon KDP & Flipkart printing guidelines.
"""

import os
import math
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from PIL import Image, ImageDraw, ImageFont, ImageFilter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, Color
from reportlab.pdfgen import canvas
import config

logger = logging.getLogger(__name__)

class CoverGenerator:
    def __init__(self, trim_size: str = "6x9", paper_type: str = "white_paper"):
        self.trim_size = trim_size if trim_size in config.AMAZON_KDP["TRIM_SIZES"] else "6x9"
        self.specs = config.AMAZON_KDP["TRIM_SIZES"][self.trim_size]
        self.paper_type = paper_type
        self.thickness_per_page = config.AMAZON_KDP["SPINE_PAGE_THICKNESS"].get(paper_type, 0.002252)

    def calculate_spine_width(self, page_count: int) -> float:
        """Calculates spine width in inches based on page count and paper type."""
        # Ensure page count is even for physical printing
        even_pages = page_count if page_count % 2 == 0 else page_count + 1
        width = even_pages * self.thickness_per_page
        return max(0.06, width)

    def generate_front_cover_image(
        self,
        title: str,
        subtitle: str,
        author: str,
        output_path: Path,
        primary_color: str = "#0F172A",
        accent_color: str = "#38BDF8"
    ) -> Path:
        """Generates a high-res (1600x2560 px) front cover image."""
        width = 1600
        height = 2560
        img = Image.new("RGB", (width, height), color="#0B1120")
        draw = ImageDraw.Draw(img)

        # Theme detection for tailored visual palettes
        is_kids = any(k in title.lower() for k in ["drawing", "kids", "doodle", "trace", "coloring", "sketch", "activity"])
        is_wealth = any(k in title.lower() for k in ["rich", "wealth", "money", "finance", "cash flow", "investing", "dollar"])

        if is_kids and primary_color == "#0F172A":
            primary_color = "#312E81"
            accent_color = "#FB7185"
        elif is_wealth and primary_color == "#0F172A":
            accent_color = "#10B981"

        # Draw decorative background gradient/geometric waves
        c1 = self._hex_to_rgb(primary_color)
        c2 = self._hex_to_rgb(accent_color)
        for y in range(height):
            ratio = y / height
            # Non-linear gradient with subtle glow in the middle
            glow = math.sin(ratio * math.pi) * 0.25
            r = int(c1[0] * (1 - ratio) + c2[0] * (ratio * 0.4 + glow))
            g = int(c1[1] * (1 - ratio) + c2[1] * (ratio * 0.4 + glow))
            b = int(c1[2] * (1 - ratio) + c2[2] * (ratio * 0.4 + glow))
            draw.line([(0, y), (width, y)], fill=(min(255, r), min(255, g), min(255, b)))

        # Add elegant geometric frame accent
        draw.rectangle([(80, 80), (width - 80, height - 80)], outline=accent_color, width=3)
        draw.rectangle([(95, 95), (width - 95, height - 95)], outline="#CBD5E1", width=1)

        # Load system fonts or fallback to default
        font_title = self._get_font(95, bold=True)
        font_sub = self._get_font(44, bold=False)
        font_author = self._get_font(52, bold=True)
        font_badge = self._get_font(28, bold=True)

        # Top Badge / Category banner
        if is_kids:
            badge_text = "CREATIVE ACTIVITY & DRAWING EDITION"
            bottom_badge = "STEP-BY-STEP DRAWING LESSONS & PRACTICE GRIDS"
        elif is_wealth:
            badge_text = "WEALTH & FINANCIAL FREEDOM PLAYBOOK"
            bottom_badge = "ACTIONABLE CASH FLOW & WEALTH BLUEPRINT"
        else:
            badge_text = "INTERNATIONAL BESTSELLER EDITION"
            bottom_badge = "FOREWORD & ACTIONABLE BLUEPRINT INCLUDED"

        draw.text((width // 2, 220), badge_text, fill="#E2E8F0", font=font_badge, anchor="mm")
        draw.line([(width // 2 - 250, 260), (width // 2 + 250, 260)], fill=accent_color, width=2)

        # Wrap and draw title
        title_lines = self._wrap_text(title.upper(), max_chars=18)
        start_y = 650
        line_height = 115
        for idx, line in enumerate(title_lines):
            draw.text((width // 2, start_y + (idx * line_height)), line, fill="#FFFFFF", font=font_title, anchor="mm")

        # Accent divider
        div_y = start_y + (len(title_lines) * line_height) + 40
        draw.line([(width // 2 - 120, div_y), (width // 2 + 120, div_y)], fill=accent_color, width=6)

        # Subtitle
        if subtitle:
            sub_lines = self._wrap_text(subtitle, max_chars=32)
            sub_y = div_y + 60
            for idx, s_line in enumerate(sub_lines):
                draw.text((width // 2, sub_y + (idx * 55)), s_line, fill="#94A3B8", font=font_sub, anchor="mm")

        # Bottom Author Box
        draw.line([(width // 2 - 300, height - 420), (width // 2 + 300, height - 420)], fill="#334155", width=2)
        draw.text((width // 2, height - 330), f"BY {author.upper()}", fill="#F8FAFC", font=font_author, anchor="mm")
        draw.text((width // 2, height - 250), bottom_badge, fill="#64748B", font=font_badge, anchor="mm")


        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(output_path), "JPEG", quality=95)
        return output_path

    def generate_full_wrap_pdf(
        self,
        book_data: Dict[str, Any],
        page_count: int,
        front_cover_img_path: Path,
        output_pdf_path: Path
    ) -> Dict[str, Any]:
        """Generates print-ready full wrap PDF [Back Cover | Spine | Front Cover] with 0.125 inch bleed."""
        bleed = config.AMAZON_KDP["BLEED_INCHES"]
        trim_w = self.specs["width_in"]
        trim_h = self.specs["height_in"]

        spine_w = self.calculate_spine_width(page_count)
        total_w_in = (2 * trim_w) + spine_w + (2 * bleed)
        total_h_in = trim_h + (2 * bleed)

        total_w_pt = total_w_in * inch
        total_h_pt = total_h_in * inch

        c = canvas.Canvas(str(output_pdf_path), pagesize=(total_w_pt, total_h_pt))

        # Base background for entire wrap
        c.setFillColor(HexColor("#0B1120"))
        c.rect(0, 0, total_w_pt, total_h_pt, fill=True, stroke=False)

        # Coordinates
        bleed_pt = bleed * inch
        trim_w_pt = trim_w * inch
        trim_h_pt = trim_h * inch
        spine_w_pt = spine_w * inch

        back_cover_x = bleed_pt
        spine_x = back_cover_x + trim_w_pt
        front_cover_x = spine_x + spine_w_pt

        # 1. FRONT COVER SECTION: Draw generated front cover image
        if front_cover_img_path.exists():
            c.drawImage(
                str(front_cover_img_path),
                front_cover_x,
                bleed_pt,
                width=trim_w_pt,
                height=trim_h_pt,
                preserveAspectRatio=False
            )

        # 2. SPINE SECTION:
        # Dark spine with subtle border
        c.setFillColor(HexColor("#070B14"))
        c.rect(spine_x, bleed_pt, spine_w_pt, trim_h_pt, fill=True, stroke=False)

        # If spine is wide enough (>= 0.25 inches / approx 80+ pages), write spine text
        title = book_data.get("title", "")
        author = book_data.get("author", "")
        if spine_w >= 0.22:
            c.saveState()
            # Rotate 90 degrees clockwise (top of spine to bottom)
            c.translate(spine_x + (spine_w_pt / 2.0), total_h_pt / 2.0)
            c.rotate(-90)
            c.setFont("Helvetica-Bold", min(10, int(spine_w * 36)))
            c.setFillColor(HexColor("#FFFFFF"))
            spine_text = f"{title.upper()}  —  {author.upper()}"
            c.drawCentredString(0, -3, spine_text)
            c.restoreState()

        # 3. BACK COVER SECTION:
        c.saveState()
        back_center_x = back_cover_x + (trim_w_pt / 2.0)
        c.setFont("Helvetica-Bold", 14)
        c.setFillColor(HexColor("#38BDF8"))
        c.drawCentredString(back_center_x, total_h_pt - 80, "TRANSFORM YOUR REALITY")

        c.setFont("Helvetica", 9)
        c.setFillColor(HexColor("#E2E8F0"))

        hook = book_data.get("hook_summary") or book_data.get("outline", {}).get("hook_summary", "")
        if hook:
            hook_lines = self._wrap_text(hook, max_chars=46)
            cur_y = total_h_pt - 110
            for h_l in hook_lines:
                c.drawCentredString(back_center_x, cur_y, h_l)
                cur_y -= 14

        # Key Takeaways Bullet points on Back
        c.setFont("Helvetica-Bold", 11)
        c.setFillColor(HexColor("#FFFFFF"))
        c.drawString(back_cover_x + 36, total_h_pt - 210, "WHAT YOU WILL DISCOVER INSIDE:")

        c.setFont("Helvetica", 8.5)
        c.setFillColor(HexColor("#CBD5E1"))
        bullets = [
            "Actionable mental models that produce immediate, compound results.",
            "Field-tested frameworks to eliminate decision fatigue and friction.",
            "Strategic roadmaps designed to help you master momentum.",
            "End-of-chapter checklists for rapid daily implementation."
        ]
        b_y = total_h_pt - 235
        for b in bullets:
            c.drawString(back_cover_x + 40, b_y, f"•  {b}")
            b_y -= 20

        # Barcode Placeholder Zone (Mandatory 2x1.2 inch area in bottom right corner of back cover)
        barcode_w = 2.0 * inch
        barcode_h = 1.2 * inch
        barcode_x = spine_x - barcode_w - 20
        barcode_y = bleed_pt + 30

        c.setFillColor(HexColor("#FFFFFF"))
        c.rect(barcode_x, barcode_y, barcode_w, barcode_h, fill=True, stroke=False)
        c.setFont("Helvetica", 7)
        c.setFillColor(HexColor("#64748B"))
        c.drawCentredString(barcode_x + (barcode_w / 2.0), barcode_y + (barcode_h / 2.0) + 4, "[ BARCODE & ISBN ZONE ]")
        c.drawCentredString(barcode_x + (barcode_w / 2.0), barcode_y + (barcode_h / 2.0) - 8, "Amazon KDP / Flipkart Print-on-Demand")

        # Publisher Imprint
        c.setFont("Helvetica-Oblique", 8)
        c.setFillColor(HexColor("#94A3B8"))
        publisher = book_data.get("publisher", config.DEFAULT_PUBLISHER_NAME)
        c.drawString(back_cover_x + 36, barcode_y + 15, f"Published by {publisher}")
        c.restoreState()

        c.save()

        return {
            "cover_wrap_pdf": str(output_pdf_path),
            "front_cover_jpg": str(front_cover_img_path),
            "spine_width_inches": round(spine_w, 4),
            "total_width_inches": round(total_w_in, 3),
            "total_height_inches": round(total_h_in, 3),
            "page_count_used": page_count
        }

    def _get_font(self, size: int, bold: bool = False):
        try:
            name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
            return ImageFont.truetype(f"/usr/share/fonts/truetype/dejavu/{name}", size)
        except Exception:
            return ImageFont.load_default()

    def _hex_to_rgb(self, hex_code: str):
        hex_code = hex_code.lstrip("#")
        return tuple(int(hex_code[i:i+2], 16) for i in (0, 2, 4))

    def _wrap_text(self, text: str, max_chars: int = 24):
        words = text.split()
        lines = []
        cur_line = []
        cur_len = 0
        for w in words:
            if cur_len + len(w) + 1 <= max_chars:
                cur_line.append(w)
                cur_len += len(w) + 1
            else:
                if cur_line:
                    lines.append(" ".join(cur_line))
                cur_line = [w]
                cur_len = len(w)
        if cur_line:
            lines.append(" ".join(cur_line))
        return lines
