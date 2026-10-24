"""Gemini AI Engine for Book Generation and Listing Metadata
Utilizes the official Google GenAI SDK to generate book outlines, chapters,
Amazon KDP compliant descriptions/keywords, and Flipkart catalog attributes.
"""

import json
import logging
import re
from typing import Dict, Any, List, Optional
from google import genai
from google.genai import types
import config

logger = logging.getLogger(__name__)

class GeminiBookEngine:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or config.GEMINI_API_KEY
        self.model = model or config.GEMINI_MODEL
        self._client = None

    @property
    def client(self) -> genai.Client:
        if self._client is None:
            if not self.api_key:
                raise ValueError("GEMINI_API_KEY is not configured.")
            self._client = genai.Client(
                api_key=self.api_key,
                http_options=types.HttpOptions(
                    retry_options=types.HttpRetryOptions(attempts=1)
                )
            )
        return self._client

    def get_model_status(self) -> Dict[str, Any]:
        """Returns details about the active primary model, Gemini 4 Argon specifications, and fallbacks."""
        is_argon = ("argon" in self.model.lower() or "4" in self.model.lower())
        return {
            "primary_model": self.model,
            "is_gemini_4_argon": is_argon,
            "active_specifications": config.GEMINI_4_ARGON_SPECS if is_argon else {
                "model_name": self.model,
                "display_name": self.model,
                "context_window_tokens": 1048576,
                "max_output_tokens": 8192
            },
            "fallback_cascade": [m for m in config.DEFAULT_MODELS if m != self.model]
        }

    def generate_text(self, prompt: str, system_instruction: Optional[str] = None) -> str:
        """Standard text generation call with retries, exponential backoff, and model fallback."""
        models_to_try = [self.model] + [m for m in config.DEFAULT_MODELS if m != self.model]
        last_error = None
        for model_name in models_to_try:
            # Set high output tokens for Gemini 4 Argon (32K capacity)
            max_tokens = 16384 if ("argon" in model_name or "4" in model_name) else 4096
            for attempt in range(3):
                try:
                    cfg = types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.7,
                        max_output_tokens=max_tokens,
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
                    ) if system_instruction else types.GenerateContentConfig(
                        temperature=0.7,
                        max_output_tokens=max_tokens,
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
                    )

                    response = self.client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=cfg
                    )
                    return response.text or ""
                except Exception as e:
                    err_str = str(e)
                    last_error = e

                    # If model has 0 quota or quota is completely exhausted, immediately cascade to next model
                    if "limit: 0" in err_str or "limit:0" in err_str or "quota exceeded for metric" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                        logger.info(f"Model {model_name} quota unavailable on current key ({err_str[:80]}...). Cascading to next fallback model...")
                        break

                    if "503" in err_str or "429" in err_str or "high demand" in err_str:
                        sleep_time = (attempt + 1) * 2
                        logger.warning(f"Model {model_name} busy (attempt {attempt+1}/3: {err_str[:80]}...). Waiting {sleep_time}s...")
                        import time
                        time.sleep(sleep_time)
                        continue
                    else:
                        logger.warning(f"Model {model_name} failed: {e}. Trying next model fallback...")
                        break
        raise RuntimeError(f"All Gemini models failed. Last error: {last_error}")

    def generate_json(self, prompt: str, system_instruction: Optional[str] = None) -> Dict[str, Any]:
        """Generates structured JSON with retries, exponential backoff, and fallback."""
        models_to_try = [self.model] + [m for m in config.DEFAULT_MODELS if m != self.model]
        last_error = None
        for model_name in models_to_try:
            max_tokens = 8192 if ("argon" in model_name or "4" in model_name) else 4096
            for attempt in range(3):
                try:
                    cfg = types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        response_mime_type="application/json",
                        temperature=0.4,
                        max_output_tokens=max_tokens,
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
                    ) if system_instruction else types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.4,
                        max_output_tokens=max_tokens,
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
                    )

                    response = self.client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=cfg
                    )
                    text = (response.text or "").strip()
                    if text.startswith("```"):
                        text = re.sub(r"^```(?:json)?\n?", "", text)
                        text = re.sub(r"\n?```$", "", text)
                    return json.loads(text)
                except Exception as e:
                    err_str = str(e)
                    last_error = e

                    # Fast cascade on quota exhaustion
                    if "limit: 0" in err_str or "limit:0" in err_str or "quota exceeded for metric" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                        logger.info(f"Model {model_name} JSON quota unavailable. Cascading to next fallback model...")
                        break

                    if "503" in err_str or "429" in err_str or "high demand" in err_str:
                        sleep_time = (attempt + 1) * 2
                        logger.warning(f"Model {model_name} busy for JSON (attempt {attempt+1}/3). Waiting {sleep_time}s...")
                        import time
                        time.sleep(sleep_time)
                        continue
                    else:
                        logger.warning(f"Model {model_name} failed JSON gen: {e}. Trying next fallback...")
                        break
        raise RuntimeError(f"All Gemini models failed for JSON. Last error: {last_error}")

    def generate_book_outline(
        self,
        topic: str,
        target_audience: str = "General",
        target_chapters: int = 7,
        book_type: str = "standard"
    ) -> Dict[str, Any]:
        """Generates a structured, high-depth book outline powered by Gemini 4 Argon."""
        if book_type == "activity_drawing" or any(k in topic.lower() for k in ["drawing", "draw", "coloring", "doodle", "tracing", "sketch"]):
            return self.generate_activity_drawing_outline(topic, target_audience, target_chapters)

        sys_prompt = (
            "You are a master non-fiction publishing director, bestselling author, and intellectual architect. "
            "Design authoritative, deeply engaging book structures that combine rigorous first-principles thinking, "
            "practical frameworks, and real-world case studies optimized for Amazon KDP and Flipkart bestsellers."
        )
        prompt = f"""
Create an advanced, high-impact book blueprint based on the topic: "{topic}".
Target Audience: {target_audience}
Target Chapter Count: {target_chapters}

Return JSON with this exact schema:
{{
    "title": "Main Title (catchy, powerful, under 80 chars)",
    "subtitle": "Subtitle (clear value proposition & outcome, under 120 chars)",
    "author_name": "{config.DEFAULT_AUTHOR_NAME}",
    "publisher_name": "{config.DEFAULT_PUBLISHER_NAME}",
    "genre": "Specific Genre (e.g., Self-Help, Wealth & Finance, Technology, Personal Growth)",
    "hook_summary": "1-2 sentence hook explaining why this book is indispensable",
    "target_reader": "Who this book is for and the exact transformation it delivers",
    "paradigm_shift": "The foundational breakthrough or mental model this book introduces",
    "chapters": [
        {{
            "chapter_number": 1,
            "title": "Chapter Title",
            "subtitle": "Chapter Focus & Transformation",
            "key_takeaways": ["Takeaway 1", "Takeaway 2", "Takeaway 3"],
            "core_concepts": ["Concept 1", "Concept 2"],
            "practical_exercise": "Hands-on diagnostic or implementation drill for this chapter",
            "case_study_topic": "Real-world scenario or historical precedent analyzed"
        }}
    ]
}}
"""
        return self.generate_json(prompt, system_instruction=sys_prompt)

    def generate_activity_drawing_outline(
        self,
        topic: str,
        target_audience: str = "Kids Ages 4-9",
        target_chapters: int = 5
    ) -> Dict[str, Any]:
        """Generates a specialized drawing & activity book blueprint with progressive drawing lessons."""
        sys_prompt = (
            "You are a master children's book illustrator, art educator, and bestselling activity book author for Amazon KDP & Flipkart. "
            "Create structured, easy-to-follow, step-by-step drawing lesson blueprints designed for children and beginner artists."
        )
        prompt = f"""
Create a complete Kids Step-by-Step Drawing & Activity Book blueprint based on: "{topic}".
Target Audience: {target_audience}
Number of Tutorial Chapters/Sections: {target_chapters}

Each chapter must group 2-3 delightful drawing lessons (e.g., Chapter 1: Cute Pets & Companions, Chapter 2: Safari & Jungle Animals, etc.).

Return JSON with this exact schema:
{{
    "title": "Main Title (fun, encouraging, e.g. How to Draw Cute Animals)",
    "subtitle": "Subtitle (clear value: Step-by-Step Drawing for Kids Ages 4-8 with Practice Grids)",
    "author_name": "{config.DEFAULT_AUTHOR_NAME}",
    "publisher_name": "{config.DEFAULT_PUBLISHER_NAME}",
    "genre": "Children's Activity / Drawing & Coloring",
    "book_type": "activity_drawing",
    "hook_summary": "An easy, fun, step-by-step drawing book that builds artistic confidence using simple basic shapes and practice spaces.",
    "target_reader": "{target_audience}",
    "chapters": [
        {{
            "chapter_number": 1,
            "title": "Module Title (e.g., Cute Farm & Home Friends)",
            "subtitle": "Drawing Lessons Overview",
            "key_takeaways": ["Shapes: Circles, Ovals, Curved lines", "Lessons: Puppy, Kitten, Bunny"],
            "core_concepts": ["Basic Shape Breakdown", "Expression Doodling", "Practice Grids"]
        }}
    ]
}}
"""
        return self.generate_json(prompt, system_instruction=sys_prompt)

    def generate_chapter_content(
        self,
        book_title: str,
        chapter_meta: Dict[str, Any],
        context: str = "",
        book_type: str = "standard"
    ) -> str:
        """Writes deep, multi-section chapter content powered by Gemini 4 Argon.
        Routes to activity drawing generator if book_type is activity_drawing.
        """
        if book_type == "activity_drawing" or any(k in book_title.lower() for k in ["drawing", "draw", "coloring", "doodle", "tracing", "sketch"]):
            return self.generate_activity_drawing_chapter(book_title, chapter_meta, context)

        sys_prompt = (
            "You are a world-class non-fiction author, researcher, and master educator writing with the depth, clarity, and authority "
            "of Gemini 4 Argon. Craft rich, comprehensive, beautifully structured chapters of substantial depth (1,500 to 2,500 words). "
            "Structure every chapter with clear markdown headings (## and ###), narrative vignettes, first-principles cognitive models, "
            "tactical step-by-step frameworks, field case studies, and actionable reader exercises. "
            "Never use filler or superficial meta-commentary. Output raw, print-ready Markdown."
        )
        prompt = f"""
Book Title: "{book_title}"
Chapter {chapter_meta.get('chapter_number', 1)}: {chapter_meta.get('title', '')}
Subtitle: {chapter_meta.get('subtitle', '')}
Key Learning Objectives: {', '.join(chapter_meta.get('key_takeaways', []))}
Core Concepts: {', '.join(chapter_meta.get('core_concepts', []))}
Practical Exercise: {chapter_meta.get('practical_exercise', 'Self-audit worksheet')}
Case Study Context: {chapter_meta.get('case_study_topic', 'Applied real-world execution')}
Book Arc Context: {context}

Write a comprehensive, publication-grade chapter of approximately 1,500-2,500 words structured into the following 6 essential sections:

1. Opening Hook: An immersive narrative vignette illustrating the stakes of this chapter.
2. ## First Principles & Cognitive Models: The core paradigm, psychological mechanisms, and root causes.
3. ## The 3-Tier Tactical Action Blueprint: A concrete step-by-step implementation system (Phase 1: Diagnosis, Phase 2: Execution, Phase 3: Compounding).
4. ## Case Study: Applied Execution in the Field: A concrete case study showing this framework in action.
5. ## Critical Pitfalls & Counter-Intuitive Truths: Common traps 90% of people fall into and how to avoid them.
6. ## Executive Implementation Worksheet & Action Checklist: A practical checklist and action items the reader can immediately complete.

Begin immediately with:
# Chapter {chapter_meta.get('chapter_number', 1)}: {chapter_meta.get('title', '')}
"""
        return self.generate_text(prompt, system_instruction=sys_prompt)

    def generate_activity_drawing_chapter(
        self,
        book_title: str,
        chapter_meta: Dict[str, Any],
        context: str = ""
    ) -> str:
        """Writes an advanced, 5-stage progressive step-by-step drawing instruction chapter with practice grid markers."""
        sys_prompt = (
            "You are an acclaimed children's book illustrator, drawing pedagogue, and bestselling activity book author. "
            "Create crystal-clear, highly engaging, step-by-step drawing lessons that teach children and beginner artists "
            "how to build complex figures from basic geometric shapes with artistic confidence. "
            "Always include 2 complete drawing lessons per chapter, complete with pro artist tips and practice grid markers."
        )
        prompt = f"""
Book Title: "{book_title}"
Chapter {chapter_meta.get('chapter_number', 1)}: {chapter_meta.get('title', '')}
Topic & Subjects: {', '.join(chapter_meta.get('key_takeaways', []))}

Write a structured Drawing & Activity Chapter containing 2 distinct drawing subjects.
For EACH drawing subject, provide:
1. Subject Name & Cheerful Welcome
2. **Basic Foundation Shapes**: (e.g., 1 large oval for torso, 1 circle for head, 2 small triangles for ears)
3. **Step 1: The Base Wireframe**: Draw the light foundation shapes and balance lines
4. **Step 2: Anatomical Poses & Curves**: Connect head to torso, add legs, paws, or wings
5. **Step 3: Facial Features & Expressions**: Position eyes, nose, snout, and joyful expression
6. **Step 4: Textures, Fur & Shading**: Add fur strokes, markings, spots, scales, and dimensional depth
7. **Step 5: Final Inking & Clean-up**: Darken outline edges and erase light construction guide lines
8. **🎨 Creative Color Palette & Shading Guide**: Suggestions for vibrant colored pencils or markers
9. Practice canvas instruction: Include the exact token `[DRAWING_PRACTICE_GRID: <Subject Name>]` which instructs the compiler to print a full-page drawing practice grid box!

Begin immediately with:
# Chapter {chapter_meta.get('chapter_number', 1)}: {chapter_meta.get('title', '')}
"""
        return self.generate_text(prompt, system_instruction=sys_prompt)


    def generate_front_and_back_matter(self, book_meta: Dict[str, Any]) -> Dict[str, str]:
        """Generates copyright, dedication, preface, and author bio / CTA."""
        prompt = f"""
Generate standard book publishing front matter and back matter for:
Title: {book_meta.get('title')}
Subtitle: {book_meta.get('subtitle')}
Author: {book_meta.get('author_name', config.DEFAULT_AUTHOR_NAME)}
Publisher: {book_meta.get('publisher_name', config.DEFAULT_PUBLISHER_NAME)}

Return JSON with exact keys:
{{
    "dedication": "A heartfelt, inspiring dedication paragraph",
    "preface": "A 2-3 paragraph preface introducing the book's mission and how to read it",
    "author_bio": "A credible, engaging 150-word author bio",
    "acknowledgements": "Brief acknowledgements paragraph",
    "review_cta": "A polite, friendly call-to-action asking the reader to leave an honest review on Amazon and Flipkart."
}}
"""
        return self.generate_json(prompt)
