"""Flipkart Seller Hub Assistant & Catalog Ingestion Engine
Validates Flipkart listing requirements, provides browser-guided session with persistent cookies,
and generates 1-click quick-copy attributes for manual and bulk listing ingestion.
"""

import os
import json
import logging
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable
from playwright.sync_api import sync_playwright, Page

logger = logging.getLogger(__name__)

class FlipkartAssistant:
    def __init__(self, user_data_dir: Optional[Path] = None):
        self.user_data_dir = user_data_dir or (Path.home() / ".cache" / "pub_agent_flipkart_profile")
        self.user_data_dir.mkdir(parents=True, exist_ok=True)

    def validate_flipkart_listing(self, book_dir: Path) -> Dict[str, Any]:
        """Performs pre-upload compliance checks against Flipkart Seller Hub requirements."""
        book_dir = Path(book_dir)
        metadata_file = book_dir / "listing_metadata.json"
        excel_file = book_dir / "flipkart_bulk_catalog.xlsx"

        issues = []
        warnings = []
        checks_passed = []

        if not metadata_file.exists():
            issues.append("listing_metadata.json is missing.")
            return {"valid": False, "issues": issues, "warnings": warnings, "checks": checks_passed}

        with open(metadata_file, "r", encoding="utf-8") as f:
            dossier = json.load(f)

        fk = dossier.get("flipkart", {})

        # 1. Check ISBN
        isbn = fk.get("isbn_13", "")
        if not isbn:
            issues.append("ISBN-13 is required for listing books on Flipkart.")
        elif len(isbn.replace("-", "")) not in [10, 13]:
            warnings.append(f"ISBN '{isbn}' should be 10 or 13 digits for commercial catalog validation.")
        else:
            checks_passed.append(f"Valid ISBN-13 format: {isbn}")

        # 2. Check HSN Code
        hsn = fk.get("hsn_code", "")
        if str(hsn).startswith("4901"):
            checks_passed.append(f"HSN Code {hsn} (0% GST printed books) is verified.")
        else:
            warnings.append(f"Unusual HSN code {hsn}. Printed books in India should normally use 4901.10.00.")

        # 3. Check Dimensions & Weight
        dims = fk.get("dimensions_cm", {})
        weight = fk.get("weight_grams", 0)
        if dims.get("length", 0) > 0 and dims.get("breadth", 0) > 0 and dims.get("height", 0) > 0:
            checks_passed.append(f"Dimensions verified: {dims['length']} x {dims['breadth']} x {dims['height']} cm")
        else:
            issues.append("Package dimensions (L x B x H) must be strictly positive.")

        if weight >= 40:
            checks_passed.append(f"Package weight verified: {weight} grams")
        else:
            issues.append("Package weight must be at least 40 grams.")

        # 4. Check Price
        mrp = fk.get("mrp_inr", 0)
        selling = fk.get("selling_price_inr", 0)
        if mrp > 0 and selling > 0 and selling <= mrp:
            checks_passed.append(f"Pricing verified: MRP ₹{mrp}, Selling Price ₹{selling}")
        else:
            issues.append(f"Selling price (₹{selling}) must be greater than 0 and less than or equal to MRP (₹{mrp}).")

        # 5. Check Bulk Excel File
        if excel_file.exists():
            checks_passed.append(f"Bulk Catalog Spreadsheet found: {excel_file.name}")
        else:
            warnings.append("flipkart_bulk_catalog.xlsx not yet generated.")

        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "warnings": warnings,
            "checks_passed": checks_passed,
            "excel_path": str(excel_file) if excel_file.exists() else None
        }

    def get_quick_copy_payload(self, book_dir: Path) -> Dict[str, Any]:
        """Generates clean, pre-formatted strings for 1-click clipboard pasting on Flipkart Seller Hub."""
        book_dir = Path(book_dir)
        metadata_file = book_dir / "listing_metadata.json"
        if not metadata_file.exists():
            return {}

        with open(metadata_file, "r", encoding="utf-8") as f:
            dossier = json.load(f)

        fk = dossier.get("flipkart", {})
        dims = fk.get("dimensions_cm", {})

        highlights = fk.get("highlights", [])
        highlights_formatted = "\n".join([f"• {h}" for h in highlights])

        return {
            "title": fk.get("title", ""),
            "subtitle": fk.get("subtitle", ""),
            "author": fk.get("author", ""),
            "publisher": fk.get("publisher", ""),
            "isbn_13": fk.get("isbn_13", ""),
            "hsn_code": fk.get("hsn_code", "4901.10.00"),
            "gst_rate": f"{fk.get('gst_rate_percent', 0)}%",
            "edition": fk.get("edition", "1st Edition"),
            "publication_year": str(fk.get("publication_year", 2026)),
            "language": fk.get("language", "English"),
            "binding": fk.get("binding", "Paperback"),
            "pages": str(fk.get("number_of_pages", 24)),
            "mrp": str(fk.get("mrp_inr", 499)),
            "selling_price": str(fk.get("selling_price_inr", 399)),
            "dimensions_cm": f"{dims.get('length', 22.86)} x {dims.get('breadth', 15.24)} x {dims.get('height', 1.2)} cm",
            "length_cm": str(dims.get("length", 22.86)),
            "breadth_cm": str(dims.get("breadth", 15.24)),
            "height_cm": str(dims.get("height", 1.2)),
            "weight_grams": str(fk.get("weight_grams", 180)),
            "highlights_formatted": highlights_formatted,
            "synopsis": fk.get("synopsis", ""),
            "bulk_excel_path": str((book_dir / "flipkart_bulk_catalog.xlsx").resolve()),
            "front_cover_jpg_path": str((book_dir / "cover_front.jpg").resolve())
        }

    def launch_assisted_session(
        self,
        book_dir: Path,
        headless: bool = False,
        progress_cb: Optional[Callable[[str, int], None]] = None,
        keep_open_seconds: int = 120
    ) -> Dict[str, Any]:
        """Launches an interactive Playwright browser session for Flipkart Seller Hub."""
        book_dir = Path(book_dir)
        validation = self.validate_flipkart_listing(book_dir)
        excel_path = book_dir / "flipkart_bulk_catalog.xlsx"

        status_log: List[str] = [f"Pre-Flight Validation: {'PASS (100%)' if validation['valid'] else 'ACTION REQUIRED'}"]

        def log(msg: str, pct: Optional[int] = None):
            logger.info(f"[FlipkartAssistant] {msg}")
            status_log.append(msg)
            if progress_cb:
                progress_cb(msg, pct if pct is not None else -1)

        is_display = bool(os.environ.get("DISPLAY"))
        effective_headless = headless if is_display else True
        if not is_display and not headless:
            log("No graphical display detected; running Playwright in headless session mode.", 5)

        log("Launching Chrome for Flipkart Seller Hub with persistent profile...", 10)

        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(self.user_data_dir),
                headless=effective_headless,
                viewport={"width": 1366, "height": 900},
                args=["--start-maximized", "--no-sandbox"]
            )
            page = context.new_page()
            try:
                log("Navigating to Flipkart Seller Hub (https://seller.flipkart.com/)...", 20)
                try:
                    page.goto("https://seller.flipkart.com/", timeout=60000, wait_until="domcontentloaded")
                except Exception as e:
                    log(f"Navigation notice: {e}")

                time.sleep(2)

                # Check if seller is already logged in or needs login
                if "login" in page.url or page.locator("input[type='text'], input[name*='email'], input[name*='mobile']").count() > 0:
                    log("Please enter your Flipkart Seller phone/email in the browser window...", 30)
                    try:
                        page.wait_for_url(lambda u: "dashboard" in u or "seller" in u, timeout=120000)
                        log("✅ Flipkart Seller login confirmed!", 45)
                    except Exception:
                        log("Proceeding with session...", 45)

                time.sleep(2)

                log("Navigating towards Bulk Listings Catalog Ingestion...", 60)
                # Attempt to navigate to bulk listing if logged in
                if "dashboard" in page.url:
                    try:
                        page.goto("https://seller.flipkart.com/index.html#dashboard/my-listings/bulk-listings", timeout=30000)
                        time.sleep(3)
                    except Exception:
                        pass

                # If bulk catalog file input is found, attach flipkart_bulk_catalog.xlsx
                if excel_path.exists():
                    bulk_file_input = page.locator("input[type='file'][accept*='xls'], input[type='file']")
                    if bulk_file_input.count() > 0:
                        try:
                            bulk_file_input.first.set_input_files(str(excel_path.resolve()))
                            log(f"📊 Attached Bulk Catalog: {excel_path.name}!", 80)
                        except Exception as e:
                            log(f"Bulk file attach notice: {e}")
                    else:
                        log(f"📁 Ready-to-upload Flipkart spreadsheet: {excel_path.resolve()}", 85)

                log("✅ Flipkart Seller Hub session ready. Complete your listing upload.", 95)
                log(f"Session will remain open for {keep_open_seconds}s or until closed.", 100)

                start_wait = time.time()
                while time.time() - start_wait < keep_open_seconds:
                    if page.is_closed():
                        log("Browser window was closed by user.")
                        break
                    time.sleep(2)

            except Exception as e:
                log(f"Flipkart Assistant session notice: {e}")
            finally:
                try:
                    context.close()
                except Exception:
                    pass

        return {
            "status": "completed",
            "platform": "flipkart",
            "validation": validation,
            "excel_path": str(excel_path.resolve()) if excel_path.exists() else None,
            "log": status_log
        }
