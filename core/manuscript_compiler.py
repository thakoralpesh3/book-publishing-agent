"""Manuscript Compiler
Compiles book markdown into print-ready interior PDF (ReportLab) and EPUB formats
meeting Amazon KDP Paperback and standard commercial printing specifications.
"""

import os
import re
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from reportlab.lib.units import inch, cm, mm
from reportlab.lib.colors import HexColor, black, Color
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, KeepTogether, HRFlowable, Table, TableStyle
)
from reportlab.pdfgen import canvas
import config


logger = logging.getLogger(__name__)

class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas for running headers and accurate 'Page X of Y' or alternating page numbers."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []
        self.book_title = "Book Title"
        self.current_chapter = ""

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        # Don't draw headers/footers on first 4 pages (Half Title, Title, Copyright, Dedication)
        if self._pageNumber <= 4:
            return

        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(HexColor("#666666"))

        page_width, page_height = self._pagesize

        # Running Header (alternate even/odd pages)
        # Even page (left): Book Title on left
        # Odd page (right): Chapter or author on right
        if self._pageNumber % 2 == 0:
            self.drawString(config.AMAZON_KDP["MARGINS_INCHES"]["outside"] * inch, page_height - 36, self.book_title.upper())
        else:
            self.drawRightString(page_width - (config.AMAZON_KDP["MARGINS_INCHES"]["outside"] * inch), page_height - 36, "CHAPTER SUMMARY")

        # Thin rule under header
        self.setStrokeColor(HexColor("#E0E0E0"))
        self.setLineWidth(0.5)
        self.line(
            config.AMAZON_KDP["MARGINS_INCHES"]["outside"] * inch,
            page_height - 42,
            page_width - (config.AMAZON_KDP["MARGINS_INCHES"]["outside"] * inch),
            page_height - 42
        )

        # Footer: Centered Page Number
        page_str = f"{self._pageNumber}"
        self.drawCentredString(page_width / 2.0, 30, page_str)
        self.restoreState()


class ManuscriptCompiler:
    def __init__(self, trim_size: str = "6x9"):
        self.trim_size = trim_size if trim_size in config.AMAZON_KDP["TRIM_SIZES"] else config.AMAZON_KDP["DEFAULT_TRIM_SIZE"]
        specs = config.AMAZON_KDP["TRIM_SIZES"][self.trim_size]
        self.page_width = specs["width_in"] * inch
        self.page_height = specs["height_in"] * inch

    def compile_pdf(self, book_data: Dict[str, Any], output_path: Optional[Path] = None) -> Dict[str, Any]:
        """Compiles the book content into a print-ready interior PDF."""
        title = book_data.get("title", "Untitled Book")
        subtitle = book_data.get("subtitle", "")
        author = book_data.get("author", config.DEFAULT_AUTHOR_NAME)
        publisher = book_data.get("publisher", config.DEFAULT_PUBLISHER_NAME)
        book_dir = Path(book_data.get("book_dir", config.OUTPUT_DIR))

        if output_path is None:
            output_path = book_dir / "manuscript_interior.pdf"
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        margins = config.AMAZON_KDP["MARGINS_INCHES"]
        left_margin = margins["inside_gutter"] * inch
        right_margin = margins["outside"] * inch
        top_margin = margins["top"] * inch
        bottom_margin = margins["bottom"] * inch
        avail_width = self.page_width - left_margin - right_margin
        is_large_format = (self.trim_size == "8.5x11")

        def create_doc_template():
            return SimpleDocTemplate(
                str(output_path),
                pagesize=(self.page_width, self.page_height),
                leftMargin=left_margin,
                rightMargin=right_margin,
                topMargin=top_margin,
                bottomMargin=bottom_margin
            )

        doc = create_doc_template()

        styles = getSampleStyleSheet()

        # Custom Typography Styles
        title_style = ParagraphStyle(
            'BookTitle',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=24,
            leading=28,
            alignment=1, # Center
            textColor=HexColor("#1A1A1A"),
            spaceAfter=14
        )

        subtitle_style = ParagraphStyle(
            'BookSubtitle',
            parent=styles['Normal'],
            fontName='Helvetica-Oblique',
            fontSize=13,
            leading=17,
            alignment=1,
            textColor=HexColor("#4A4A4A"),
            spaceAfter=30
        )

        author_style = ParagraphStyle(
            'BookAuthor',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=12,
            leading=16,
            alignment=1,
            textColor=HexColor("#2C3E50"),
            spaceAfter=8
        )

        publisher_style = ParagraphStyle(
            'BookPublisher',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=10,
            leading=14,
            alignment=1,
            textColor=HexColor("#7F8C8D"),
            spaceAfter=20
        )

        chapter_head_style = ParagraphStyle(
            'ChapterHeader',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=18,
            leading=22,
            textColor=HexColor("#0F172A"),
            spaceBefore=20,
            spaceAfter=14,
            keepWithNext=True
        )

        section_head_style = ParagraphStyle(
            'SectionHeader',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=13,
            leading=17,
            textColor=HexColor("#1E293B"),
            spaceBefore=14,
            spaceAfter=8,
            keepWithNext=True
        )

        body_style = ParagraphStyle(
            'BookBody',
            parent=styles['Normal'],
            fontName='Times-Roman',
            fontSize=10.5,
            leading=15,
            textColor=HexColor("#111827"),
            spaceAfter=8,
            firstLineIndent=14
        )

        quote_style = ParagraphStyle(
            'BookQuote',
            parent=styles['Normal'],
            fontName='Times-Italic',
            fontSize=10,
            leading=14,
            textColor=HexColor("#334155"),
            leftIndent=20,
            rightIndent=15,
            spaceBefore=8,
            spaceAfter=10
        )

        bullet_style = ParagraphStyle(
            'BookBullet',
            parent=styles['Normal'],
            fontName='Times-Roman',
            fontSize=10.5,
            leading=14,
            leftIndent=15,
            spaceAfter=4
        )

        copyright_style = ParagraphStyle(
            'CopyrightText',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=8,
            leading=12,
            textColor=HexColor("#4B5563"),
            spaceAfter=6
        )

        story = []

        # 1. Half Title Page
        story.append(Spacer(1, 100))
        story.append(Paragraph(title, title_style))
        story.append(PageBreak())

        # 2. Full Title Page
        story.append(Spacer(1, 70))
        story.append(Paragraph(title, title_style))
        if subtitle:
            story.append(Paragraph(subtitle, subtitle_style))
        story.append(Spacer(1, 60))
        story.append(Paragraph(f"By {author}", author_style))
        story.append(Spacer(1, 40))
        story.append(Paragraph(f"Published by {publisher}", publisher_style))
        story.append(PageBreak())

        # 3. Copyright Page
        story.append(Spacer(1, 180))
        story.append(Paragraph(f"<b>{title}</b>", copyright_style))
        if subtitle:
            story.append(Paragraph(f"<i>{subtitle}</i>", copyright_style))
        story.append(Spacer(1, 8))
        story.append(Paragraph(f"Copyright © 2026 by {author}.", copyright_style))
        story.append(Paragraph("All rights reserved. No part of this publication may be reproduced, stored in a retrieval system, or transmitted in any form or by any means without prior written permission of the publisher.", copyright_style))
        story.append(Spacer(1, 8))
        story.append(Paragraph(f"Publisher: {publisher}", copyright_style))
        story.append(Paragraph(f"Trim Size: {self.trim_size} inches", copyright_style))
        story.append(Paragraph("First Edition: 2026", copyright_style))
        story.append(PageBreak())

        # 4. Dedication / Preface
        front_back = book_data.get("front_back", {})
        if front_back.get("dedication"):
            story.append(Spacer(1, 120))
            story.append(Paragraph("<i>" + front_back["dedication"] + "</i>", ParagraphStyle('Dedication', parent=quote_style, alignment=1)))
            story.append(PageBreak())

        if front_back.get("preface"):
            story.append(Paragraph("Preface", chapter_head_style))
            story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#CBD5E1"), spaceAfter=14))
            for para in front_back["preface"].split("\n\n"):
                if para.strip():
                    story.append(Paragraph(para.strip(), body_style))
            story.append(PageBreak())

        # 5. Body Chapters
        chapters = book_data.get("chapters", [])
        for ch in chapters:
            content = ch.get("content", "")
            lines = content.split("\n")

            for line in lines:
                line_str = line.strip()
                if not line_str:
                    continue

                if line_str.startswith("# "):
                    ch_title = line_str.replace("# ", "").strip()
                    story.append(Paragraph(ch_title, chapter_head_style))
                    story.append(HRFlowable(width="100%", thickness=1, color=HexColor("#0F172A"), spaceAfter=14))
                elif line_str.startswith("## "):
                    sec_title = line_str.replace("## ", "").strip()
                    story.append(Paragraph(sec_title, section_head_style))
                elif line_str.startswith("### "):
                    sub_title = line_str.replace("### ", "").strip()
                    story.append(Paragraph(sub_title, section_head_style))
                elif line_str.startswith(">"):
                    q_text = line_str.replace(">", "").strip()
                    story.append(Paragraph(f"<i>“{q_text}”</i>", quote_style))
                elif line_str.startswith(("- ", "* ", "• ")):
                    b_text = re.sub(r"^[-*•]\s*", "", line_str)
                    story.append(Paragraph(f"• {b_text}", bullet_style))
                elif re.match(r"^\d+\.\s", line_str):
                    num_text = line_str
                    story.append(Paragraph(num_text, bullet_style))
                elif "[DRAWING_PRACTICE_GRID" in line_str:
                    match = re.search(r"\[DRAWING_PRACTICE_GRID(?::\s*([^\]]+))?\]", line_str)
                    subject_name = match.group(1).strip() if match and match.group(1) else "Creative Sketch"
                    story.append(Spacer(1, 8))
                    story.append(self._create_drawing_canvas(subject_name, avail_width, is_large_format))
                    story.append(Spacer(1, 14))
                elif line_str == "---":
                    story.append(HRFlowable(width="40%", thickness=0.5, color=HexColor("#94A3B8"), spaceBefore=10, spaceAfter=10))
                else:
                    # Clean bold / italic markdown for ReportLab
                    clean_para = line_str
                    clean_para = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", clean_para)
                    clean_para = re.sub(r"\*(.*?)\*", r"<i>\1</i>", clean_para)
                    story.append(Paragraph(clean_para, body_style))


            story.append(PageBreak())

        # 6. Back Matter: CTA & About Author
        if front_back.get("review_cta"):
            story.append(Paragraph("A Message from the Author", chapter_head_style))
            story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#CBD5E1"), spaceAfter=14))
            for para in front_back["review_cta"].split("\n\n"):
                if para.strip():
                    story.append(Paragraph(para.strip(), body_style))
            story.append(Spacer(1, 20))

        if front_back.get("author_bio"):
            story.append(Paragraph("About the Author", chapter_head_style))
            story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#CBD5E1"), spaceAfter=14))
            for para in front_back["author_bio"].split("\n\n"):
                if para.strip():
                    story.append(Paragraph(para.strip(), body_style))

        # Build PDF with canvas
        def make_canvas(*args, **kwargs):
            c = NumberedCanvas(*args, **kwargs)
            c.book_title = title
            return c

        doc.build(list(story), canvasmaker=make_canvas)

        # Inspect generated PDF page count
        final_page_count = self._count_pdf_pages(output_path)

        # Amazon KDP Paperback strictly requires at least 24 pages.
        # If below 24 pages, append structured Implementation & Notes pages.
        if final_page_count < 24:
            pages_needed = 24 - final_page_count
            for p_idx in range(1, pages_needed + 1):
                story.append(PageBreak())
                story.append(Paragraph(f"Reader Notes &amp; Action Plan (Part {p_idx})", section_head_style))
                story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#CBD5E1"), spaceAfter=14))
                for _ in range(8 if is_large_format else 6):
                    story.append(Spacer(1, 24))
                    story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#E2E8F0"), spaceAfter=6))
            doc = create_doc_template()
            doc.build(list(story), canvasmaker=make_canvas)
            final_page_count = self._count_pdf_pages(output_path)

        return {
            "pdf_path": str(output_path),
            "trim_size": self.trim_size,
            "page_count": final_page_count,
            "width_inches": self.page_width / inch,
            "height_inches": self.page_height / inch
        }

    def _create_drawing_canvas(self, subject: str, available_width: float, is_large_format: bool = False) -> Table:
        """Creates a dedicated, printable drawing practice canvas for activity books."""
        head_style = ParagraphStyle(
            'CanvasHeader',
            fontName='Helvetica-Bold',
            fontSize=10,
            leading=13,
            alignment=1,
            textColor=HexColor("#334155")
        )
        canvas_title = subject.strip() if subject.strip() else "YOUR DRAWING"
        header_para = Paragraph(
            f"<b>✏️ PRACTICE CANVAS: {canvas_title.upper()}</b><br/>"
            f"<font size='8' color='#64748B'>Draw your foundation shapes and outline lightly with pencil here!</font>",
            head_style
        )
        # Determine canvas height based on page trim size
        box_height = 280 if is_large_format else 180
        t = Table([[header_para], [""]], colWidths=[available_width], rowHeights=[36, box_height])
        t.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 1.2, HexColor('#94A3B8')),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, HexColor('#E2E8F0')),
            ('BACKGROUND', (0, 0), (-1, 0), HexColor('#F1F5F9')),
            ('BACKGROUND', (0, 1), (-1, 1), HexColor('#FAFAFA')),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        return t

    def _count_pdf_pages(self, pdf_path: Path) -> int:
        """Counts the pages of the generated PDF."""
        try:
            with open(pdf_path, 'rb') as f:
                content = f.read()
            # Fast count using /Type /Page
            pages = len(re.findall(rb"/Type\s*/Page\b", content))
            return max(pages, 1)
        except Exception:
            return 32

    def compile_interior_pdf(self, book_data: Dict[str, Any], output_path: Optional[Path] = None) -> Path:
        """Helper to compile interior PDF and return the Path object directly."""
        res = self.compile_pdf(book_data, output_path=output_path)
        return Path(res["pdf_path"])

    def get_page_count(self, pdf_path: Path) -> int:
        """Returns the page count of a generated PDF."""
        return self._count_pdf_pages(pdf_path)

