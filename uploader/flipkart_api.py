"""Flipkart Marketplace Seller API v3 Client
Provides OAuth 2.0 authentication and Listing Management v3 API upload
as the automated fallback when Flipkart Seller Hub browser upload is unavailable.
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import requests

import config

logger = logging.getLogger(__name__)


class FlipkartSellerAPI:
    """Client for Flipkart Marketplace Seller API (api.flipkart.net)."""

    def __init__(
        self,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        location_id: Optional[str] = None,
        sandbox: Optional[bool] = None,
        shipping_provider: Optional[str] = None,
    ):
        self.app_id = (app_id if app_id is not None else config.FLIPKART_APP_ID).strip()
        self.app_secret = (app_secret if app_secret is not None else config.FLIPKART_APP_SECRET).strip()
        self.location_id = (location_id if location_id is not None else config.FLIPKART_LOCATION_ID).strip()
        self.sandbox = config.FLIPKART_SANDBOX if sandbox is None else bool(sandbox)
        self.shipping_provider = (shipping_provider or config.FLIPKART_SHIPPING_PROVIDER or "FLIPKART").strip()
        self.base_url = "https://sandbox-api.flipkart.net" if self.sandbox else "https://api.flipkart.net"
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

    def is_configured(self) -> bool:
        """Returns True when Flipkart Seller API OAuth credentials are present."""
        return bool(self.app_id and self.app_secret)

    def authenticate(self, timeout: float = 20.0) -> str:
        """Fetches or returns a cached OAuth 2.0 client_credentials Bearer token."""
        if not self.is_configured():
            raise ValueError("Flipkart Seller API credentials (FLIPKART_APP_ID, FLIPKART_APP_SECRET) are not configured.")

        if self._access_token and time.time() < (self._token_expires_at - 60):
            return self._access_token

        url = f"{self.base_url}/oauth-service/oauth/token"
        resp = requests.get(
            url,
            params={"grant_type": "client_credentials"},
            auth=(self.app_id, self.app_secret),
            headers={"Accept": "application/json"},
            timeout=timeout,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"Flipkart OAuth failed ({resp.status_code}): {resp.text[:300]}")

        data = resp.json()
        token = data.get("access_token")
        if not token:
            raise RuntimeError(f"Flipkart OAuth response missing access_token: {data}")

        expires_in = int(data.get("expires_in", 3600) or 3600)
        self._access_token = str(token)
        self._token_expires_at = time.time() + expires_in
        return self._access_token

    def build_listing_payload(
        self,
        dossier: Dict[str, Any],
        location_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Builds a Flipkart Listings v3 payload from listing_metadata.json."""
        fk = dossier.get("flipkart", {})
        title = str(fk.get("title") or dossier.get("book_title") or "Book").strip()
        sku_id = str(fk.get("sku_id") or "").strip()
        if not sku_id:
            clean_slug = re.sub(r"[^\w]", "", title.upper())[:8] or "BOOK01"
            sku_id = f"FP-BK-{clean_slug}-01"

        product_id = str(fk.get("fsn") or fk.get("product_id") or fk.get("isbn_13") or "").strip()
        if not product_id:
            raise ValueError("Flipkart API listing requires product_id (FSN or ISBN-13) in listing_metadata.json.")

        mrp = int(float(fk.get("mrp_inr", 499) or 499))
        selling_price = min(int(float(fk.get("selling_price_inr", mrp) or mrp)), mrp)
        if mrp <= 0 or selling_price <= 0:
            raise ValueError(f"Invalid Flipkart pricing: MRP={mrp}, selling_price={selling_price}")

        hsn_digits = re.sub(r"\D", "", str(fk.get("hsn_code", "49011000"))) or "49011000"
        gst_rate = int(fk.get("gst_rate_percent", 0) or 0)
        tax_code = f"GST_{gst_rate}"

        dims = fk.get("dimensions_cm", {})
        weight_grams = max(float(fk.get("weight_grams", 180) or 180), 40.0)
        weight_kg = round(weight_grams / 1000.0, 3)

        sla = max(1, int(fk.get("procurement_sla_days", 2) or 2))
        stock_count = max(1, int(fk.get("stock_count", 50) or 50))
        loc = (location_id if location_id is not None else self.location_id).strip()

        listing_obj: Dict[str, Any] = {
            "product_id": product_id,
            "listing_status": "ACTIVE",
            "price": {
                "mrp": mrp,
                "selling_price": selling_price,
                "currency": "INR",
            },
            "tax": {
                "hsn": hsn_digits,
                "tax_code": tax_code,
            },
            "packages": [
                {
                    "name": sku_id,
                    "length": float(dims.get("length", 22.86) or 22.86),
                    "breadth": float(dims.get("breadth", 15.24) or 15.24),
                    "height": float(dims.get("height", 1.2) or 1.2),
                    "weight": weight_kg,
                    "units_per_package": 1,
                }
            ],
            "fulfillment": {
                "dispatch_sla": sla,
                "shipping_provider": self.shipping_provider,
                "procurement_type": "REGULAR",
            },
        }
        if loc:
            listing_obj["locations"] = [
                {
                    "id": loc,
                    "status": "ACTIVE",
                    "inventory": stock_count,
                }
            ]

        return {sku_id: listing_obj}

    def upload_listing(
        self,
        book_dir: Path,
        progress_cb: Optional[Callable[[str, int], None]] = None,
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        """Creates or updates a book listing via Flipkart Seller API POST /sellers/listings/v3."""
        book_dir = Path(book_dir)
        metadata_file = book_dir / "listing_metadata.json"
        if not metadata_file.exists():
            return {
                "status": "failed",
                "platform": "flipkart",
                "mode": "api",
                "error_code": "metadata_missing",
                "message": f"listing_metadata.json not found in {book_dir}",
            }

        def log(msg: str, pct: int = -1):
            logger.info(f"[FlipkartSellerAPI] {msg}")
            if progress_cb:
                progress_cb(msg, pct)

        if not self.is_configured():
            msg = (
                "api_credentials_missing: Flipkart Seller API credentials "
                "(FLIPKART_APP_ID, FLIPKART_APP_SECRET) are not configured in .env."
            )
            log(msg, 85)
            return {
                "status": "failed",
                "platform": "flipkart",
                "mode": "api",
                "error_code": "api_credentials_missing",
                "message": msg,
            }

        dossier = json.loads(metadata_file.read_text(encoding="utf-8"))
        try:
            payload = self.build_listing_payload(dossier)
        except Exception as e:
            return {
                "status": "failed",
                "platform": "flipkart",
                "mode": "api",
                "error_code": "invalid_payload",
                "message": f"Invalid Flipkart API listing payload: {e}",
            }

        sku_id = next(iter(payload.keys()))
        product_id = payload[sku_id]["product_id"]

        try:
            log("Authenticating with Flipkart Marketplace Seller API (OAuth 2.0)...", 70)
            token = self.authenticate(timeout=timeout)
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
            }

            log(f"Submitting SKU '{sku_id}' (Product ID: {product_id}) to Flipkart Listings v3 API...", 82)
            resp = requests.post(
                f"{self.base_url}/sellers/listings/v3",
                headers=headers,
                json=payload,
                timeout=timeout,
            )

            try:
                resp_data = resp.json()
            except Exception:
                resp_data = {"raw": resp.text[:500]}

            if resp.status_code >= 400:
                return {
                    "status": "failed",
                    "platform": "flipkart",
                    "mode": "api",
                    "sku_id": sku_id,
                    "product_id": product_id,
                    "error_code": f"http_{resp.status_code}",
                    "message": f"Flipkart API rejected listing ({resp.status_code}): {json.dumps(resp_data)[:300]}",
                    "api_response": resp_data,
                }

            sku_result = resp_data.get(sku_id, resp_data) if isinstance(resp_data, dict) else {}
            sku_status = str(sku_result.get("status", "")).upper() if isinstance(sku_result, dict) else ""
            sku_errors = sku_result.get("errors", []) if isinstance(sku_result, dict) else []

            if sku_status in ("FAILURE", "FAILED", "ERROR") or sku_errors:
                return {
                    "status": "failed",
                    "platform": "flipkart",
                    "mode": "api",
                    "sku_id": sku_id,
                    "product_id": product_id,
                    "error_code": "api_listing_rejected",
                    "message": f"Flipkart API listing error for SKU {sku_id}: {json.dumps(sku_errors or sku_result)[:300]}",
                    "api_response": resp_data,
                }

            # Sync warehouse inventory explicitly if location_id is configured
            if self.location_id:
                inv_payload = {
                    sku_id: {
                        "product_id": product_id,
                        "locations": [
                            {
                                "id": self.location_id,
                                "inventory": payload[sku_id]["locations"][0]["inventory"],
                            }
                        ],
                    }
                }
                requests.post(
                    f"{self.base_url}/sellers/listings/v3/update/inventory",
                    headers=headers,
                    json=inv_payload,
                    timeout=timeout,
                )

            log(f"✅ Flipkart listing '{sku_id}' uploaded successfully via Seller API v3!", 100)
            return {
                "status": "completed",
                "platform": "flipkart",
                "mode": "api",
                "sku_id": sku_id,
                "product_id": product_id,
                "api_response": resp_data,
            }
        except Exception as e:
            logger.warning(f"[FlipkartSellerAPI] Request failed: {e}")
            return {
                "status": "failed",
                "platform": "flipkart",
                "mode": "api",
                "sku_id": sku_id,
                "product_id": product_id,
                "error_code": "api_request_error",
                "message": f"Flipkart Seller API request failed: {e}",
            }
