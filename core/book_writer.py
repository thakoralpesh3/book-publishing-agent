"""Book Writer Engine
Coordinates the creation and assembly of complete non-fiction or instructional books,
including front matter, full chapters, and back matter.
"""

import json
import logging
import re
from pathlib import Path
from typing import Dict, Any, List, Optional
import config
from core.gemini_engine import GeminiBookEngine

logger = logging.getLogger(__name__)

class BookWriter:
    def __init__(self, gemini_engine: Optional[GeminiBookEngine] = None):
        self.engine = gemini_engine or GeminiBookEngine()

    def create_book(
        self,
        topic: str,
        target_audience: str = "General Reader",
        target_chapters: int = 5,
        custom_author: Optional[str] = None,
        custom_publisher: Optional[str] = None,
        book_type: Optional[str] = None,
        progress_callback: Optional[callable] = None
    ) -> Dict[str, Any]:
        """Creates a complete book package from topic to full manuscript."""
        # Auto-detect book type if not specified
        if not book_type or book_type == "auto":
            if any(k in topic.lower() for k in ["drawing", "draw", "coloring", "doodle", "tracing", "sketch"]):
                book_type = "activity_drawing"
            else:
                book_type = "standard"

        if progress_callback:
            progress_callback(10, f"Generating {book_type.replace('_', ' ')} blueprint for: {topic}...")

        outline = self.engine.generate_book_outline(
            topic=topic,
            target_audience=target_audience,
            target_chapters=target_chapters,
            book_type=book_type
        )

        title = outline.get("title", topic).strip()
        subtitle = outline.get("subtitle", "").strip()
        author = custom_author or outline.get("author_name") or config.DEFAULT_AUTHOR_NAME
        publisher = custom_publisher or outline.get("publisher_name") or config.DEFAULT_PUBLISHER_NAME

        slug = re.sub(r"[^\w\-]", "_", title.lower())[:50]
        book_dir = config.OUTPUT_DIR / slug
        book_dir.mkdir(parents=True, exist_ok=True)

        if progress_callback:
            progress_callback(25, "Generating front matter, dedication, and author bio...")

        front_back = self.engine.generate_front_and_back_matter({
            "title": title,
            "subtitle": subtitle,
            "author_name": author,
            "publisher_name": publisher
        })

        chapters_content = []
        raw_chapters = outline.get("chapters", [])
        total_chapters = len(raw_chapters)

        book_context = f"Title: {title}. Subtitle: {subtitle}. Hook: {outline.get('hook_summary', '')}. Type: {book_type}"

        for idx, ch_meta in enumerate(raw_chapters, start=1):
            pct = 30 + int((idx / max(total_chapters, 1)) * 45)
            if progress_callback:
                progress_callback(pct, f"Writing Module {idx}/{total_chapters}: {ch_meta.get('title')}...")

            ch_text = self.engine.generate_chapter_content(
                book_title=title,
                chapter_meta=ch_meta,
                context=book_context,
                book_type=book_type
            )
            chapters_content.append({
                "chapter_number": ch_meta.get("chapter_number", idx),
                "title": ch_meta.get("title", f"Chapter {idx}"),
                "content": ch_text
            })

        if progress_callback:
            progress_callback(80, "Assembling complete manuscript...")

        full_manuscript_md = self._assemble_markdown(
            title=title,
            subtitle=subtitle,
            author=author,
            publisher=publisher,
            front_back=front_back,
            chapters=chapters_content
        )

        # Save manuscript file
        manuscript_path = book_dir / "manuscript.md"
        with open(manuscript_path, "w", encoding="utf-8") as f:
            f.write(full_manuscript_md)

        # Calculate word count and estimated pages
        total_words = len(re.findall(r"\w+", full_manuscript_md))
        if book_type == "activity_drawing":
            # For drawing books, each drawing step & grid canvas takes substantial layout space
            estimated_pages = max(36, len(chapters_content) * 6 + 10)
        else:
            estimated_pages = max(24, int(total_words / 230) + len(chapters_content) * 2 + 10)

        book_data = {
            "title": title,
            "subtitle": subtitle,
            "author": author,
            "publisher": publisher,
            "slug": slug,
            "book_dir": str(book_dir),
            "manuscript_path": str(manuscript_path),
            "outline": outline,
            "front_back": front_back,
            "chapters": chapters_content,
            "total_words": total_words,
            "estimated_pages": estimated_pages,
            "genre": outline.get("genre", "Children's Activity" if book_type == "activity_drawing" else "Self-Help / Business"),
            "book_type": book_type,
            "hook_summary": outline.get("hook_summary", "")
        }

        with open(book_dir / "book_data.json", "w", encoding="utf-8") as f:
            json.dump(book_data, f, indent=2)

        if progress_callback:
            progress_callback(90, "Manuscript complete!")

        return book_data


    def _assemble_markdown(
        self,
        title: str,
        subtitle: str,
        author: str,
        publisher: str,
        front_back: Dict[str, str],
        chapters: List[Dict[str, Any]]
    ) -> str:
        """Assembles all sections into standard publishing markdown."""
        parts = []

        # Title Page
        parts.append(f"# {title}\n")
        if subtitle:
            parts.append(f"### *{subtitle}*\n")
        parts.append(f"\n**By {author}**\n\n*Published by {publisher}*\n\n---\n")

        # Copyright Page
        parts.append("## Copyright Notice\n")
        parts.append(f"Copyright © 2026 by {author}. All rights reserved.\n")
        parts.append(
            "No part of this publication may be reproduced, distributed, or transmitted in any form "
            "or by any means, including photocopying, recording, or other electronic or mechanical methods, "
            "without the prior written permission of the publisher, except in the case of brief quotations "
            "embodied in critical reviews and certain other noncommercial uses permitted by copyright law.\n"
        )
        parts.append(f"Published by: {publisher}\nFirst Edition\n\n---\n")

        # Dedication
        if front_back.get("dedication"):
            parts.append("## Dedication\n")
            parts.append(f"*{front_back['dedication']}*\n\n---\n")

        # Preface / Introduction
        if front_back.get("preface"):
            parts.append("## Preface\n")
            parts.append(f"{front_back['preface']}\n\n---\n")

        # Chapters
        for ch in chapters:
            parts.append(ch["content"])
            parts.append("\n\n---\n")

        # Back Matter: Conclusion / CTA
        if front_back.get("review_cta"):
            parts.append("## A Request From The Author\n")
            parts.append(f"{front_back['review_cta']}\n\n---\n")

        # About the Author
        if front_back.get("author_bio"):
            parts.append("## About the Author\n")
            parts.append(f"{front_back['author_bio']}\n\n---\n")

        if front_back.get("acknowledgements"):
            parts.append("## Acknowledgements\n")
            parts.append(f"{front_back['acknowledgements']}\n")

        return "\n".join(parts)
