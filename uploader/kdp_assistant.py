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

        # Clear stale Singleton locks to prevent browser startup hangs on recovery
        for lock_f in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
            try:
                (self.user_data_dir / lock_f).unlink(missing_ok=True)
            except Exception:
                pass

        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(self.user_data_dir),
                headless=effective_headless,
                viewport={"width": 1366, "height": 900},
                args=["--start-maximized", "--no-sandbox", "--disable-gpu", "--disable-software-rasterizer", "--disable-dev-shm-usage"]
            )

            page = context.new_page()
            session_error = None
            try:
                log("Navigating to Amazon KDP Bookshelf (https://kdp.amazon.com/bookshelf)...", 20)
                try:
                    page.goto("https://kdp.amazon.com/en_US/bookshelf", timeout=60000, wait_until="domcontentloaded")
                except Exception as e:
                    log(f"Navigation note: {e}")

                time.sleep(2)

                # Check if sign-in is required
                if any(x in page.url for x in ["signin", "ap/signin", "openid"]):
                    if not effective_headless:
                        log("Action Required: Please complete Amazon Sign-In in the browser window...", 25)
                        try:
                            page.wait_for_url(lambda u: "bookshelf" in u or "title-setup" in u, timeout=180000)
                            log("✅ Sign-in confirmed! Proceeding to KDP Bookshelf...", 35)
                        except Exception:
                            log("Sign-in timeout reached. Continuing session if bookshelf is accessible...", 35)

                time.sleep(2)

                log(f"Preparing {book_type.title()} setup for: '{amz.get('title')}'...", 40)

                # If on bookshelf, navigate directly to Title Setup or click "Create" without waiting on tracker pixels
                if "title-setup" not in page.url:
                    if "bookshelf" in page.url:
                        create_btn = page.locator("#create-title-btn, a[href*='createnew/create'], a:has-text('Create'), button:has-text('Create')")
                        if create_btn.count() > 0:
                            try:
                                create_btn.first.click(no_wait_after=True)
                                target_choice = "Create paperback" if book_type == "paperback" else "Create eBook"
                                choice_btn = page.locator(f"button:has-text('{target_choice}'), a:has-text('{target_choice}')")
                                choice_btn.first.wait_for(state="visible", timeout=25000)
                                choice_btn.first.click(no_wait_after=True)
                                for _ in range(25):
                                    time.sleep(1)
                                    if "title-setup" in page.url or any(x in page.url for x in ["signin", "ap/signin", "openid"]):
                                        break
                            except Exception as e:
                                log(f"Could not auto-click Create button: {e}")
                    if "title-setup" not in page.url and not any(x in page.url for x in ["signin", "ap/signin", "openid"]):
                        try:
                            page.goto("https://kdp.amazon.com/en_US/title-setup/paperback/new/details", timeout=45000, wait_until="domcontentloaded")
                            time.sleep(2)
                        except Exception:
                            pass

                # Check if Amazon redirected to login / password verification (e.g., max_auth_age=0 elevation)
                if any(x in page.url for x in ["signin", "ap/signin", "openid"]):
                    if not effective_headless:
                        log("Action Required: Please complete Amazon Sign-In / Password Verification in the browser window...", 25)
                        try:
                            page.wait_for_url(lambda u: "title-setup" in u or "bookshelf" in u, timeout=120000)
                            log("✅ Sign-in confirmed! Proceeding with title setup...", 35)
                        except Exception:
                            pass
                    if any(x in page.url for x in ["signin", "ap/signin", "openid"]):
                        session_error = "login_required: Amazon KDP password/OTP verification is required for title setup. Please run 'python3 uploader/login_seller_portals.py kdp' to authenticate."
                        log(f"🔑 {session_error}", 30)

                if not session_error:
                    # Step 1: Pre-fill Book Details (Title, Subtitle, Author, Description, Rights, Categories, 7 Keywords)
                    log("Injecting Step 1 (Paperback Details, Metadata, Categories & 7 Keywords)...", 50)
                    filled_ok = self._fill_step1_details(page, amz, log)
                    if not filled_ok:
                        session_error = "form_not_ready: Amazon KDP paperback form was not found on current page. Please verify your KDP account login via 'python3 uploader/login_seller_portals.py kdp'."
                        log(f"⚠️ {session_error}", 50)

                # Advance to Step 2 if auto_advance is True and Save and Continue button is visible
                if not session_error and auto_advance:
                    save_btn = page.locator("#save-and-continue-announce, #save-and-continue-button, button:has-text('Save and Continue'), input[value*='Save and Continue']")
                    if save_btn.count() > 0 and save_btn.first.is_visible():
                        log("Auto-advancing to Step 2 (Paperback Content)...", 65)
                        try:
                            save_btn.first.click(no_wait_after=True)
                            for _ in range(25):
                                time.sleep(1)
                                if "/content" in page.url or any(x in page.url for x in ["signin", "ap/signin", "openid"]):
                                    break
                            if any(x in page.url for x in ["signin", "ap/signin", "openid"]):
                                session_error = "login_required: Amazon KDP requested re-authentication when saving Step 1. Run 'python3 uploader/login_seller_portals.py kdp'."
                                log(f"🔑 {session_error}", 65)
                            elif "/content" not in page.url:
                                err_texts = self._collect_visible_alerts(page)
                                detail = f" Validation: {' | '.join(err_texts[:3])}" if err_texts else ""
                                session_error = f"step1_save_failed: KDP Step 1 did not advance to Step 2 ({page.url}).{detail}"
                                log(f"⚠️ {session_error}", 70)
                            else:
                                page.wait_for_load_state("domcontentloaded", timeout=15000)
                                time.sleep(3)
                                files_ok = self._fill_step2_content(page, amz, interior_pdf, cover_pdf, log)
                                if not files_ok:
                                    session_error = "content_upload_not_ready: KDP Step 2 manuscript/cover PDF uploaders were not accessible."
                                    log(f"⚠️ {session_error}", 85)
                                else:
                                    # Attempt saving draft / advancing to Step 3 pricing if previewer check already allows it
                                    if "/rights-and-pricing" in page.url:
                                        self._fill_step3_pricing(page, amz, log)
                        except Exception as e:
                            session_error = f"step2_advance_failed: {e}"
                            log(f"Auto-advance step 2 note: {e}")
                    else:
                        session_error = "step1_save_not_found: Could not find 'Save and Continue' button after filling Step 1."

                if not session_error:
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
                session_error = str(e)
                log(f"KDP Assistant session exception: {e}")
            finally:
                try:
                    context.close()
                except Exception:
                    pass

        if session_error:
            return {
                "status": "failed",
                "platform": "amazon_kdp",
                "message": f"Amazon KDP upload interrupted: {session_error}",
                "error": session_error,
                "book_title": amz.get("title"),
                "interior_pdf": str(interior_pdf.resolve()) if interior_pdf.exists() else None,
                "cover_pdf": str(cover_pdf.resolve()) if cover_pdf.exists() else None,
                "log": status_log
            }

        return {
            "status": "completed",
            "platform": "amazon_kdp",
            "book_title": amz.get("title"),
            "interior_pdf": str(interior_pdf.resolve()) if interior_pdf.exists() else None,
            "cover_pdf": str(cover_pdf.resolve()) if cover_pdf.exists() else None,
            "log": status_log
        }

    @staticmethod
    def _resolve_marketplace_code(available_values: List[str], preferred: str = "amazon.in") -> str:
        """Maps marketplace string to live KDP Paperback select option values (fallback to 'us')."""
        mapping = {
            "amazon.com": "us", "us": "us",
            "amazon.co.uk": "uk", "uk": "uk",
            "amazon.de": "de", "de": "de",
            "amazon.fr": "fr", "fr": "fr",
            "amazon.es": "es", "es": "es",
            "amazon.it": "it", "it": "it",
            "amazon.nl": "nl", "nl": "nl",
            "amazon.pl": "pl", "pl": "pl",
            "amazon.se": "se", "se": "se",
            "amazon.com.be": "be", "be": "be",
            "amazon.ie": "ie", "ie": "ie",
            "amazon.co.jp": "jp", "jp": "jp",
            "amazon.ca": "ca", "ca": "ca",
            "amazon.com.au": "au", "au": "au",
            "amazon.in": "in", "in": "in",
        }
        want = mapping.get((preferred or "").strip().lower(), "us")
        if want in available_values:
            return want
        return "us" if "us" in available_values else (available_values[0] if available_values else want)

    @staticmethod
    def _match_category_option_label(segment: str, options: List[str]) -> Optional[str]:
        """Matches a metadata category segment (e.g. 'Business') against live KDP dropdown labels."""
        clean_opts = [o for o in options if o and o.strip().lower() not in {"select one", "select", ""}]
        if not clean_opts or not segment:
            return None
        seg_l = segment.strip().lower()
        for o in clean_opts:
            if o.strip().lower() == seg_l:
                return o
        for o in clean_opts:
            if seg_l in o.strip().lower() or o.strip().lower() in seg_l:
                return o
        alias_hints = {
            "nonfiction": "",
            "books": "",
            "tech": "Computers & Technology",
            "technology": "Computers & Technology",
            "wealth": "Business & Money",
            "finance": "Business & Money",
            "money": "Business & Money",
            "mindset": "Self-Help",
            "productivity": "Self-Help",
            "personal growth": "Self-Help",
            "health": "Health, Fitness & Dieting",
            "drawing": "Arts, Music & Photography",
            "children": "Children's Books",
            "kids": "Children's Books",
        }
        hint = alias_hints.get(seg_l)
        if hint:
            for o in clean_opts:
                if hint.lower() in o.strip().lower():
                    return o
        seg_words = {w for w in re.findall(r"[a-z0-9]+", seg_l) if len(w) > 2}
        best_opt, best_score = None, 0
        for o in clean_opts:
            opt_words = {w for w in re.findall(r"[a-z0-9]+", o.lower()) if len(w) > 2}
            score = len(seg_words & opt_words)
            if score > best_score:
                best_opt, best_score = o, score
        return best_opt if best_score > 0 else None

    @staticmethod
    def _collect_visible_alerts(page: Page) -> List[str]:
        try:
            return page.evaluate("""() => {
                const out = [];
                for (const el of document.querySelectorAll("[class*='error'], [class*='alert-error'], [role='alert'], .a-color-error")) {
                    if (el.offsetParent !== null) {
                        const t = (el.innerText || '').trim().replace(/\\s+/g, ' ');
                        if (t && t.length > 3) out.push(t.slice(0, 140));
                    }
                }
                return Array.from(new Set(out));
            }""")
        except Exception:
            return []

    def _fill_kdp_description(self, page: Page, amz: Dict[str, Any], log: Callable) -> bool:
        """Fills KDP CKEditor 4 iframe / source view and verifies hidden field binding."""
        html_desc = (amz.get("html_description") or amz.get("plain_description") or "").strip()[:3900]
        plain_desc = (amz.get("plain_description") or re.sub(r"<[^>]+>", " ", html_desc)).strip()[:3900]
        if not html_desc and not plain_desc:
            return False

        # 1. Preferred: CKEditor Source view (preserves KDP HTML formatting) or iframe body typing
        src_btn = page.locator("a.cke_button__source")
        if src_btn.count() > 0 and src_btn.first.is_visible():
            try:
                src_btn.first.click()
                src_area = page.locator("textarea.cke_source")
                src_area.first.wait_for(state="visible", timeout=3000)
                src_area.first.fill(html_desc)
                src_btn.first.click()
                time.sleep(0.5)
            except Exception:
                pass

        # 2. Check whether KDP hidden input synced; if empty, type directly into WYSIWYG iframe body + blur
        def _hid_len() -> int:
            try:
                return page.evaluate("() => (document.querySelector(\"input[name='data[print_book][description]']\")?.value || '').trim().length")
            except Exception:
                return 0

        if _hid_len() == 0 and page.locator("iframe.cke_wysiwyg_frame").count() > 0:
            try:
                fb = page.frame_locator("iframe.cke_wysiwyg_frame").locator("body")
                fb.wait_for(state="visible", timeout=5000)
                fb.click()
                page.keyboard.insert_text(plain_desc)
                page.keyboard.press("Space")
                page.locator("#data-print-book-title").click()
                time.sleep(0.4)
            except Exception:
                pass

        # 3. Legacy visible textarea or CKEditor5 fallback
        if _hid_len() == 0:
            desc_textarea = page.locator("textarea#data-print-book-description:visible, textarea[name*='description']:visible, #data-book-description:visible")
            if desc_textarea.count() > 0:
                try:
                    desc_textarea.first.fill(html_desc)
                    log(f"✓ Injected KDP HTML Description ({len(html_desc)} chars).")
                    return True
                except Exception:
                    pass

        synced_len = _hid_len()
        if synced_len > 0:
            log(f"✓ Injected KDP Description ({synced_len} chars).")
            return True
        return False

    def _select_kdp_categories(self, page: Page, browse_categories: List[str], log: Callable) -> bool:
        """Selects KDP Step 1 Categories via #categories-modal-button after Adult Content is enabled."""
        btn = page.locator("#categories-modal-button")
        if btn.count() == 0:
            return False
        try:
            for _ in range(10):
                if btn.first.is_enabled():
                    break
                time.sleep(0.4)
            if not btn.first.is_enabled():
                return False

            btn.first.click()
            dlg = page.locator(".a-popover-modal:visible, [role='dialog']:visible").first
            dlg.wait_for(state="visible", timeout=8000)
            time.sleep(1)

            paths = list(browse_categories or [])
            if not paths:
                paths = ["Children's Books > Activities, Crafts & Games > Activity Books"]

            selected_any = False
            for path in paths[:1]:
                raw_parts = [s.strip() for s in str(path).split(">") if s.strip() and s.strip().lower() not in {"books", "nonfiction"}]
                # Walk cascading selects as long as matching option resolves
                for idx in range(5):
                    sels = dlg.locator("select")
                    if sels.count() <= idx:
                        break
                    opts = sels.nth(idx).evaluate("s => Array.from(s.options).map(o => o.text.trim())")
                    target_label = None
                    if idx < len(raw_parts):
                        target_label = self._match_category_option_label(raw_parts[idx], opts)
                    if not target_label:
                        valid_opts = [o for o in opts if o and o.lower() not in {"select one", "select", ""}]
                        if not valid_opts:
                            break
                        target_label = valid_opts[0]
                    sels.nth(idx).select_option(label=target_label)
                    time.sleep(0.9)
                    if dlg.locator("label:has(input[type='checkbox'])").count() > 0:
                        # Prefer leaf selection once deeper dropdowns finish populating (or after last path part)
                        if idx >= len(raw_parts) - 1 or sels.count() <= idx + 1:
                            break

                # Click placement checkbox label (Amazon AUI hides raw input under <i class='a-icon-checkbox'>)
                chk_labels = dlg.locator("label:has(input[type='checkbox'])")
                if chk_labels.count() > 0:
                    leaf_target = raw_parts[-1] if raw_parts else ""
                    chosen_idx = 0
                    for ci in range(min(chk_labels.count(), 15)):
                        ltxt = (chk_labels.nth(ci).inner_text() or "").strip()
                        if leaf_target and leaf_target.lower() in ltxt.lower():
                            chosen_idx = ci
                            break
                        if "general" in ltxt.lower():
                            chosen_idx = ci
                    chk_labels.nth(chosen_idx).click()
                    time.sleep(0.5)
                    selected_any = True

            save_cats = dlg.locator("button:has-text('Save categories')")
            if selected_any and save_cats.count() > 0 and save_cats.first.is_enabled():
                save_cats.first.click()
                time.sleep(1.5)
                log("✓ Selected and saved KDP Categories.")
                return True
        except Exception as e:
            log(f"Category selection note: {e}")
        return False

    def _fill_step1_details(self, page: Page, amz: Dict[str, Any], log: Callable) -> bool:
        """Fills title, subtitle, author, description, rights, adult content, marketplace, categories, and 7 keywords."""
        try:
            # Title (wait briefly for React/SPA form controls and skip hidden matching inputs)
            title_input = page.locator("#data-print-book-title, #data-book-title, input[id*='book-title'], input[name*='title']:visible")
            try:
                title_input.first.wait_for(state="visible", timeout=10000)
            except Exception:
                pass
            if title_input.count() == 0 or not title_input.first.is_visible():
                log(f"⚠️ Title input field not found or not visible on current page ({page.url}).")
                return False

            title_input.first.fill(amz.get("title", ""))
            log(f"✓ Filled Title: {amz.get('title')}")

            # Subtitle
            subtitle_input = page.locator("#data-print-book-subtitle, #data-book-subtitle, input[name*='subtitle']")
            if subtitle_input.count() > 0 and amz.get("subtitle"):
                subtitle_input.first.fill(amz.get("subtitle"))
                log(f"✓ Filled Subtitle: {amz.get('subtitle')}")

            # Author Name (split into First & Last if needed)
            full_author = amz.get("author", "Alpesh Patel")
            author_parts = full_author.strip().split()
            first_name = amz.get("author_first_name") or (author_parts[0] if author_parts else "Author")
            last_name = amz.get("author_last_name") or (" ".join(author_parts[1:]) if len(author_parts) > 1 else "Patel")

            first_input = page.locator("#data-print-book-primary-author-first-name, input[name*='primary_author][first_name']")
            last_input = page.locator("#data-print-book-primary-author-last-name, input[name*='primary_author][last_name']")
            if first_input.count() > 0:
                first_input.first.fill(first_name)
            if last_input.count() > 0:
                last_input.first.fill(last_name)
                log(f"✓ Filled Primary Author: {first_name} {last_name}")

            # Description (CKEditor 4 iframe / source)
            self._fill_kdp_description(page, amz, log)

            # Publishing Rights: "I own the copyright" (#non-public-domain in live KDP)
            copyright_label = page.locator("label:has(#non-public-domain), label:has(input[name='data-print-book-is-public-domain'][value='false'])")
            copyright_radio = page.locator("#non-public-domain, input[name='data-print-book-is-public-domain'][value='false'], input[type='radio'][value*='copyright']")
            if copyright_label.count() > 0:
                try:
                    copyright_label.first.click()
                    log("✓ Selected 'I own the copyright and hold the necessary publishing rights'.")
                except Exception:
                    pass
            elif copyright_radio.count() > 0:
                try:
                    copyright_radio.first.check(force=True)
                    log("✓ Selected 'I own the copyright and hold the necessary publishing rights'.")
                except Exception:
                    pass

            # Adult Content: "No" (MUST be selected BEFORE Choose Categories button becomes enabled)
            adult_label = page.locator("label:has(input[name='data[print_book][is_adult_content]-radio'][value='false'])")
            adult_no = page.locator("#data-print-book-is-adult-content-false, input[name='data[print_book][is_adult_content]-radio'][value='false']")
            if adult_label.count() > 0:
                try:
                    adult_label.first.click()
                    log("✓ Selected Adult Content: No.")
                except Exception:
                    pass
            elif adult_no.count() > 0:
                try:
                    adult_no.first.check(force=True)
                    log("✓ Selected Adult Content: No.")
                except Exception:
                    pass

            # Reading Interest Age (optional for Children's titles)
            title_lower = (amz.get("title") or "").lower()
            cats_joined = " ".join(amz.get("browse_categories", [])).lower()
            if any(k in title_lower or k in cats_joined for k in ["kids", "children", "juvenile", "preschool"]):
                age_min = page.locator("#data-print-book-reading-interest-age-start-input-native")
                age_max = page.locator("#data-print-book-reading-interest-age-end-input-native")
                try:
                    if age_min.count() > 0 and age_min.first.is_visible():
                        age_min.first.select_option(value="4")
                    if age_max.count() > 0 and age_max.first.is_visible():
                        age_max.first.select_option(value="9")
                except Exception:
                    pass

            # Primary Marketplace (Paperback home_marketplace uses 'us', 'uk', etc.)
            marketplace_sel = page.locator("select[name='data[print_book][home_marketplace]'], #data-print-book-primary-marketplace")
            if marketplace_sel.count() > 0:
                try:
                    opts = marketplace_sel.first.evaluate("s => Array.from(s.options).map(o => o.value)")
                    mkt_val = self._resolve_marketplace_code(opts, preferred="amazon.in")
                    marketplace_sel.first.select_option(value=mkt_val)
                    log(f"✓ Selected Primary Marketplace: {mkt_val.upper()}")
                except Exception:
                    pass

            # Categories Modal
            self._select_kdp_categories(page, amz.get("browse_categories", []), log)

            # 7 Backend Keywords (live KDP is 0-indexed: #data-print-book-keywords-0..6)
            keywords = amz.get("backend_keywords", [])
            filled_kw = 0
            for i in range(min(7, len(keywords))):
                kw_input = page.locator(f"#data-print-book-keywords-{i}, input[name='data[print_book][keywords][{i}]'], #data-print-book-keywords-{i+1}")
                if kw_input.count() > 0:
                    kw_input.first.fill(keywords[i])
                    filled_kw += 1
            if filled_kw:
                log(f"✓ Populated {filled_kw} Amazon Backend Keywords.")

            return True
        except Exception as e:
            log(f"Note on details pre-fill: {e}")
            return False

    def _fill_step3_pricing(self, page: Page, amz: Dict[str, Any], log: Callable) -> bool:
        """Pre-fills Step 3 Paperback Rights & Pricing (All Territories + INR/USD list price) if reached."""
        try:
            all_terr = page.locator("#worldwide-rights-radio, input[name*='territory'][value='WORLDWIDE']")
            if all_terr.count() > 0:
                all_terr.first.check(force=True)
            usd_price = amz.get("pricing", {}).get("usd", {}).get("paperback_list_price", 14.99)
            us_input = page.locator("#data-pricing-print-us-price-input, input[name*='price'][name*='us']")
            if us_input.count() > 0:
                us_input.first.fill(str(usd_price))
                log(f"✓ Set US Paperback List Price: ${usd_price}")
            save_draft = page.locator("#save-announce")
            if save_draft.count() > 0 and save_draft.first.is_visible():
                save_draft.first.click(no_wait_after=True)
                time.sleep(2)
            return True
        except Exception as e:
            log(f"Step 3 pricing note: {e}")
            return False

    def _fill_step2_content(
        self,
        page: Page,
        amz: Dict[str, Any],
        interior_pdf: Path,
        cover_pdf: Path,
        log: Callable
    ) -> bool:
        """Attempts to automate Step 2: Interior PDF & Cover PDF file uploads and print options. Returns True if files were attached."""
        manuscript_attached = not interior_pdf.exists()
        cover_attached = not cover_pdf.exists()
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
                    bw_paper.first.check(force=True)
                    log("✓ Selected: Black & white interior with white paper.")
                except Exception:
                    pass

            # Bleed: No Bleed
            no_bleed = page.locator("#data-print-book-is-bleed-false, input[value*='no-bleed']")
            if no_bleed.count() > 0:
                try:
                    no_bleed.first.check(force=True)
                    log("✓ Selected: No Bleed.")
                except Exception:
                    pass

            # Cover Finish: Matte
            matte_finish = page.locator("#data-print-book-cover-finish-matte, input[value*='matte']")
            if matte_finish.count() > 0:
                try:
                    matte_finish.first.check(force=True)
                    log("✓ Selected Cover Finish: Matte.")
                except Exception:
                    pass

            # 1. Upload Manuscript Interior PDF
            if interior_pdf.exists():
                manuscript_file_input = page.locator("input[type='file'][name*='manuscript'], #data-print-book-upload-manuscript-file-upload-input, input[type='file'][accept*='pdf']")
                if manuscript_file_input.count() > 0:
                    try:
                        manuscript_file_input.first.set_input_files(str(interior_pdf.resolve()))
                        manuscript_attached = True
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
                        cover_attached = True
                        log(f"🎨 Uploading Full-Wrap Cover PDF: {cover_pdf.name}...", 90)
                    except Exception as e:
                        log(f"Could not set cover file: {e}")
                else:
                    log(f"ℹ️ Full-wrap cover PDF ready on disk: {cover_pdf.resolve()}")

            if manuscript_attached and cover_attached:
                time.sleep(5)
                save_draft = page.locator("#save-announce")
                if save_draft.count() > 0 and save_draft.first.is_visible():
                    try:
                        save_draft.first.click(no_wait_after=True)
                        time.sleep(2)
                        log("✓ Saved KDP Step 2 files as draft.")
                    except Exception:
                        pass
            return manuscript_attached and cover_attached
        except Exception as e:
            log(f"Note on Step 2 content: {e}")
            return False
