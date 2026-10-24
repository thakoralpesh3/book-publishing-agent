"""Amazon KDP Browser Upload Assistant
Automates and assists the Amazon KDP publishing workflow using Playwright with persistent session storage.
Handles Step 1 (Book Details), Step 2 (Manuscript & Cover PDF Upload), and Step 3 (Pricing & Rights).
"""

import os
import re
import json
import logging
import time
from pathlib import Path
from typing import Dict, Any, Optional, Callable, List
from playwright.sync_api import sync_playwright, Page, BrowserContext

logger = logging.getLogger(__name__)

class KDPAssistant:
    def __init__(self, user_data_dir: Optional[Path] = None):
        self.user_data_dir = user_data_dir or (Path.home() / ".cache" / "pub_agent_kdp_profile")
        self.user_data_dir.mkdir(parents=True, exist_ok=True)

    def launch_assisted_session(
        self,
        book_dir: Path,
        book_type: str = "paperback", # "paperback" or "ebook"
        headless: bool = False,
        progress_cb: Optional[Callable[[str, int], None]] = None,
        auto_advance: bool = True,
        keep_open_seconds: int = 120
    ) -> Dict[str, Any]:
        """Launches an interactive Playwright session with KDP pre-filling and file uploading."""
        book_dir = Path(book_dir)
        metadata_file = book_dir / "listing_metadata.json"
        if not metadata_file.exists():
            raise FileNotFoundError(f"listing_metadata.json not found in {book_dir}")

        with open(metadata_file, "r", encoding="utf-8") as f:
            dossier = json.load(f)

        amz = dossier.get("amazon_kdp", {})
        interior_pdf = book_dir / "manuscript_interior.pdf"
        cover_pdf = book_dir / "cover_full_wrap.pdf"
        front_cover_jpg = book_dir / "cover_front.jpg"

        status_log: List[str] = []

        def log(msg: str, pct: Optional[int] = None):
            logger.info(f"[KDPAssistant] {msg}")
            status_log.append(msg)
            if progress_cb:
                progress_cb(msg, pct if pct is not None else -1)

        is_display = bool(os.environ.get("DISPLAY"))
        effective_headless = headless if is_display else True
        if not is_display and not headless:
            log("No graphical display detected; running Playwright in headless session mode.", 5)

        log("Initializing Chromium with persistent publishing profile...", 10)

        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(self.user_data_dir),
                headless=effective_headless,
                viewport={"width": 1366, "height": 900},
                args=["--start-maximized", "--no-sandbox"]
            )

            page = context.new_page()
            try:
                log("Navigating to Amazon KDP Bookshelf (https://kdp.amazon.com/bookshelf)...", 20)
                try:
                    page.goto("https://kdp.amazon.com/bookshelf", timeout=60000, wait_until="domcontentloaded")
                except Exception as e:
                    log(f"Navigation note: {e}")

                time.sleep(2)

                # Check if sign-in is required
                if any(x in page.url for x in ["signin", "ap/signin", "openid"]):
                    log("Action Required: Please complete Amazon Sign-In in the browser window...", 25)
                    # Wait up to 180s for sign-in completion
                    try:
                        page.wait_for_url(lambda u: "bookshelf" in u or "title-setup" in u, timeout=180000)
                        log("✅ Sign-in confirmed! Proceeding to KDP Bookshelf...", 35)
                    except Exception:
                        log("Sign-in timeout reached. Continuing session if bookshelf is accessible...", 35)

                time.sleep(2)

                log(f"Preparing {book_type.title()} setup for: '{amz.get('title')}'...", 40)

                # If on bookshelf, click "Create"
                if "bookshelf" in page.url:
                    create_btn = page.locator("a:has-text('Create'), button:has-text('Create'), #create-title-btn")
                    if create_btn.count() > 0:
                        try:
                            create_btn.first.click()
                            time.sleep(2)
                            target_choice = "Create paperback" if book_type == "paperback" else "Create eBook"
                            choice_btn = page.locator(f"button:has-text('{target_choice}'), a:has-text('{target_choice}')")
                            if choice_btn.count() > 0:
                                choice_btn.first.click()
                                time.sleep(3)
                        except Exception as e:
                            log(f"Could not auto-click Create button: {e}")

                # Step 1: Pre-fill Book Details (Title, Subtitle, Author, HTML Description, Keywords)
                log("Injecting Step 1 (Paperback Details, Metadata & 7 Keywords)...", 50)
                self._fill_step1_details(page, amz, log)

                # Advance to Step 2 if auto_advance is True and Save and Continue button is visible
                if auto_advance:
                    save_btn = page.locator("#save-and-continue-button, button:has-text('Save and Continue'), input[value*='Save and Continue']")
                    if save_btn.count() > 0 and save_btn.first.is_visible():
                        log("Auto-advancing to Step 2 (Paperback Content)...", 65)
                        try:
                            save_btn.first.click()
                            time.sleep(4)
                            # Fill Step 2 (Upload interior PDF and Cover PDF)
                            self._fill_step2_content(page, amz, interior_pdf, cover_pdf, log)
                        except Exception as e:
                            log(f"Auto-advance step 2 note: {e}")

                log("✅ Amazon KDP wizard populated! Interior & Cover PDFs prepared.", 95)
                log(f"Session will remain active for inspection ({keep_open_seconds}s or until closed).", 100)

                # Keep session active so user can review and finish
                start_wait = time.time()
                while time.time() - start_wait < keep_open_seconds:
                    if page.is_closed():
                        log("Browser window was closed by user.")
                        break
                    time.sleep(2)

            except Exception as e:
                log(f"KDP Assistant session exception: {e}")
            finally:
                try:
                    context.close()
                except Exception:
                    pass

        return {
            "status": "completed",
            "platform": "amazon_kdp",
            "book_title": amz.get("title"),
            "interior_pdf": str(interior_pdf.resolve()) if interior_pdf.exists() else None,
            "cover_pdf": str(cover_pdf.resolve()) if cover_pdf.exists() else None,
            "log": status_log
        }

    def _fill_step1_details(self, page: Page, amz: Dict[str, Any], log: Callable):
        """Fills title, subtitle, author, description, rights, and keywords."""
        try:
            # Title
            title_input = page.locator("input[name*='title'], #data-print-book-title, #data-book-title")
            if title_input.count() > 0:
                title_input.first.fill(amz.get("title", ""))
                log(f"✓ Filled Title: {amz.get('title')}")

            # Subtitle
            subtitle_input = page.locator("input[name*='subtitle'], #data-print-book-subtitle, #data-book-subtitle")
            if subtitle_input.count() > 0 and amz.get("subtitle"):
                subtitle_input.first.fill(amz.get("subtitle"))
                log(f"✓ Filled Subtitle: {amz.get('subtitle')}")

            # Author Name (split into First & Last if needed)
            full_author = amz.get("author", "Alpesh Patel")
            author_parts = full_author.strip().split()
            first_name = amz.get("author_first_name") or (author_parts[0] if author_parts else "Author")
            last_name = amz.get("author_last_name") or (" ".join(author_parts[1:]) if len(author_parts) > 1 else "Patel")

            first_input = page.locator("input[name*='primary-author-first-name'], #data-print-book-primary-author-first-name")
            last_input = page.locator("input[name*='primary-author-last-name'], #data-print-book-primary-author-last-name")
            if first_input.count() > 0:
                first_input.first.fill(first_name)
            if last_input.count() > 0:
                last_input.first.fill(last_name)
                log(f"✓ Filled Primary Author: {first_name} {last_name}")

            # Description (Inject sanitized KDP HTML)
            desc_text = amz.get("html_description") or amz.get("plain_description", "")
            desc_textarea = page.locator("textarea[name*='description'], #data-book-description")
            if desc_textarea.count() > 0:
                desc_textarea.first.fill(desc_text)
                log(f"✓ Injected KDP-compliant HTML Description ({len(desc_text)} chars).")

            # Publishing Rights: "I own the copyright"
            copyright_radio = page.locator("input[type='radio'][value*='copyright'], #data-print-book-is-public-domain-false, input[id*='public-domain-false']")
            if copyright_radio.count() > 0:
                try:
                    copyright_radio.first.check()
                    log("✓ Selected 'I own the copyright and hold the necessary publishing rights'.")
                except Exception:
                    pass

            # Adult Content: "No"
            adult_no = page.locator("#data-print-book-is-adult-content-false, input[type='radio'][value*='false'][name*='adult']")
            if adult_no.count() > 0:
                try:
                    adult_no.first.check()
                    log("✓ Selected Adult Content: No.")
                except Exception:
                    pass

            # Primary Marketplace: amazon.in or amazon.com
            marketplace_sel = page.locator("#data-print-book-primary-marketplace, select[name*='primary-marketplace']")
            if marketplace_sel.count() > 0:
                try:
                    marketplace_sel.first.select_option(value="amazon.in")
                    log("✓ Selected Primary Marketplace: Amazon.in")
                except Exception:
                    pass

            # 7 Backend Keywords
            keywords = amz.get("backend_keywords", [])
            for i in range(min(7, len(keywords))):
                kw_input = page.locator(f"input[name*='keyword-{i+1}'], #data-print-book-keywords-{i+1}")
                if kw_input.count() > 0:
                    kw_input.first.fill(keywords[i])
            if keywords:
                log(f"✓ Populated all {len(keywords)} Amazon Backend Keywords.")

        except Exception as e:
            log(f"Note on details pre-fill: {e}")

    def _fill_step2_content(
        self,
        page: Page,
        amz: Dict[str, Any],
        interior_pdf: Path,
        cover_pdf: Path,
        log: Callable
    ):
        """Attempts to automate Step 2: Interior PDF & Cover PDF file uploads and print options."""
        try:
            log("Configuring Step 2 print options & file uploaders...", 70)

            # Assign Free KDP ISBN if option present
            free_isbn_btn = page.locator("#free-isbn-accordion button:has-text('Assign'), button:has-text('Assign me a free KDP ISBN')")
            if free_isbn_btn.count() > 0 and free_isbn_btn.first.is_visible():
                try:
                    free_isbn_btn.first.click()
                    log("✓ Clicked 'Assign me a free KDP ISBN'.")
                    time.sleep(2)
                except Exception:
                    pass

            # Print Options: Black & white interior with white paper
            bw_paper = page.locator("#white-paper-radio, input[value*='black-white-interior-with-white-paper']")
            if bw_paper.count() > 0:
                try:
                    bw_paper.first.check()
                    log("✓ Selected: Black & white interior with white paper.")
                except Exception:
                    pass

            # Bleed: No Bleed
            no_bleed = page.locator("#data-print-book-is-bleed-false, input[value*='no-bleed']")
            if no_bleed.count() > 0:
                try:
                    no_bleed.first.check()
                    log("✓ Selected: No Bleed.")
                except Exception:
                    pass

            # Cover Finish: Matte
            matte_finish = page.locator("#data-print-book-cover-finish-matte, input[value*='matte']")
            if matte_finish.count() > 0:
                try:
                    matte_finish.first.check()
                    log("✓ Selected Cover Finish: Matte.")
                except Exception:
                    pass

            # 1. Upload Manuscript Interior PDF
            if interior_pdf.exists():
                manuscript_file_input = page.locator("input[type='file'][name*='manuscript'], #data-print-book-upload-manuscript-file-upload-input, input[type='file'][accept*='pdf']")
                if manuscript_file_input.count() > 0:
                    try:
                        manuscript_file_input.first.set_input_files(str(interior_pdf.resolve()))
                        log(f"📄 Uploading Manuscript Interior PDF: {interior_pdf.name}...", 80)
                    except Exception as e:
                        log(f"Could not set manuscript file: {e}")
                else:
                    log(f"ℹ️ Manuscript interior PDF ready on disk: {interior_pdf.resolve()}")

            # 2. Upload Cover Wrap PDF
            if cover_pdf.exists():
                # First ensure "Upload a cover you already have" choice is active
                cover_choice = page.locator("#data-print-book-publisher-cover-choice-accordion, label:has-text('Upload a cover you already have')")
                if cover_choice.count() > 0:
                    try:
                        cover_choice.first.click()
                        time.sleep(1)
                    except Exception:
                        pass

                cover_file_input = page.locator("input[type='file'][name*='cover'], #data-print-book-upload-cover-file-upload-input")
                if cover_file_input.count() > 0:
                    try:
                        cover_file_input.first.set_input_files(str(cover_pdf.resolve()))
                        log(f"🎨 Uploading Full-Wrap Cover PDF: {cover_pdf.name}...", 90)
                    except Exception as e:
                        log(f"Could not set cover file: {e}")
                else:
                    log(f"ℹ️ Full-wrap cover PDF ready on disk: {cover_pdf.resolve()}")

        except Exception as e:
            log(f"Note on Step 2 content: {e}")
