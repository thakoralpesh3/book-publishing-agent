"""Catalog Exporter Engine
Generates official Flipkart Seller Hub bulk catalog spreadsheets (.xlsx),
Amazon KDP listing dossiers (.md and .json), and Print-on-Demand aggregator packages.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

logger = logging.getLogger(__name__)

class CatalogExporter:
    def export_all(self, book_dir: Path, dossier: Dict[str, Any]) -> Dict[str, str]:
        """Generates all export files inside the book's output directory."""
        book_dir = Path(book_dir)
        book_dir.mkdir(parents=True, exist_ok=True)

        flipkart_excel = self.export_flipkart_excel(book_dir, dossier)
        flipkart_card = self.export_flipkart_listing_card(book_dir, dossier)
        amazon_md = self.export_amazon_dossier_markdown(book_dir, dossier)
        pod_manifest = self.export_pod_manifest(book_dir, dossier)

        return {
            "flipkart_excel": str(flipkart_excel),
            "flipkart_listing_card": str(flipkart_card),
            "amazon_markdown": str(amazon_md),
            "pod_manifest": str(pod_manifest)
        }

    export_all_catalogs = export_all

    def export_flipkart_excel(self, book_dir: Path, dossier: Dict[str, Any]) -> Path:
        """Generates an official Flipkart Seller Hub Books Bulk Listing Excel spreadsheet (.xlsx)."""
        fk = dossier.get("flipkart", {})
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Flipkart Books Listing"

        # Ensure grid lines are visible
        ws.views.sheetView[0].showGridLines = True

        # Header definitions matching Flipkart Books catalog schema
        headers = [
            ("Seller SKU ID", "SKU-001"),
            ("Product ID Type", "ISBN-13"),
            ("Product ID (ISBN)", "978..."),
            ("Book Title", "Title"),
            ("Author Name", "Author"),
            ("Publisher Name", "Publisher"),
            ("Language", "English"),
            ("Binding Type", "Paperback"),
            ("Number of Pages", "120"),
            ("Edition", "1st Edition"),
            ("Publishing Year", "2026"),
            ("Genre / Category", "Books > Non-Fiction"),
            ("HSN Code", "4901.10.00"),
            ("GST Rate (%)", "0"),
            ("MRP (INR)", "499"),
            ("Selling Price (INR)", "389"),
            ("Procurement SLA (Days)", "2"),
            ("Stock Inventory", "50"),
            ("Package Length (cm)", "22.86"),
            ("Package Breadth (cm)", "15.24"),
            ("Package Height (cm)", "1.5"),
            ("Package Weight (kg)", "0.25"),
            ("Key Highlights", "Bullet points"),
            ("Description / Synopsis", "Full synopsis"),
            ("Search Keywords", "Tags"),
            ("Listing Status", "ACTIVE")
        ]

        # Row 1: Banner / Title
        ws.merge_cells("A1:Z1")
        title_cell = ws["A1"]
        title_cell.value = "FLIPKART SELLER HUB — BOOKS VERTICAL BULK CATALOG TEMPLATE"
        title_cell.font = Font(name="Calibri", size=13, bold=True, color="FFFFFF")
        title_cell.fill = PatternFill(start_color="2874F0", end_color="2874F0", fill_type="solid") # Flipkart Blue
        title_cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[1].height = 32

        # Row 2: Column Headers
        header_fill = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
        header_font = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
        thin_border = Border(
            left=Side(style='thin', color='D0D0D0'),
            right=Side(style='thin', color='D0D0D0'),
            top=Side(style='thin', color='D0D0D0'),
            bottom=Side(style='thin', color='D0D0D0')
        )

        for col_idx, (header_name, _) in enumerate(headers, start=1):
            cell = ws.cell(row=2, column=col_idx, value=header_name)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = thin_border
        ws.row_dimensions[2].height = 28

        # Row 3: Data row populated with book metadata
        dims = fk.get("dimensions_cm", {})
        weight_kg = round(fk.get("weight_grams", 250) / 1000.0, 3)
        highlights_str = " | ".join(fk.get("highlights", []))
        keywords_str = ", ".join(fk.get("search_keywords", []))

        row_data = [
            str(fk.get("sku_id", "FP-BK-001")),
            "ISBN-13",
            str(fk.get("isbn_13", "9789300000000")),
            str(fk.get("title", "")),
            str(fk.get("author", "")),
            str(fk.get("publisher", "")),
            str(fk.get("language", "English")),
            str(fk.get("binding", "Paperback")),
            int(fk.get("number_of_pages", 120)),
            str(fk.get("edition", "1st Edition")),
            int(fk.get("publication_year", 2026)),
            str(fk.get("flipkart_category", "Books > Non-Fiction")),
            str(fk.get("hsn_code", "4901.10.00")),
            int(fk.get("gst_rate_percent", 0)),
            int(fk.get("mrp_inr", 499)),
            int(fk.get("selling_price_inr", 389)),
            int(fk.get("procurement_sla_days", 2)),
            50, # Initial stock
            float(dims.get("length", 22.86)),
            float(dims.get("breadth", 15.24)),
            float(dims.get("height", 1.5)),
            float(weight_kg),
            highlights_str,
            str(fk.get("synopsis", "")),
            keywords_str,
            "ACTIVE"
        ]

        data_font = Font(name="Calibri", size=10, color="1E293B")
        data_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

        for col_idx, val in enumerate(row_data, start=1):
            cell = ws.cell(row=3, column=col_idx, value=val)
            cell.font = data_font
            cell.fill = data_fill
            cell.alignment = Alignment(vertical="center", wrap_text=(col_idx in [23, 24]))
            cell.border = thin_border
        ws.row_dimensions[3].height = 40

        # Auto-adjust column widths
        for col in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                val_str = str(cell.value or "")
                if len(val_str) > max_len and cell.row > 1:
                    max_len = len(val_str)
            # Set width between 14 and 45
            ws.column_dimensions[col_letter].width = min(max(max_len + 3, 14), 45)

        excel_path = book_dir / "flipkart_bulk_catalog.xlsx"
        wb.save(str(excel_path))
        return excel_path

    def export_flipkart_listing_card(self, book_dir: Path, dossier: Dict[str, Any]) -> Path:
        """Exports a single-listing JSON card specifically tailored for Flipkart Seller Hub."""
        fk = dossier.get("flipkart", {})
        card_data = {
            "platform": "Flipkart Seller Hub",
            "vertical": "Books",
            "listing_mode": "Single Listing / Bulk Upload",
            "sku_id": fk.get("sku_id"),
            "product_id_type": "ISBN-13",
            "isbn_13": fk.get("isbn_13"),
            "title": fk.get("title"),
            "author": fk.get("author"),
            "publisher": fk.get("publisher"),
            "language": fk.get("language"),
            "binding": fk.get("binding"),
            "pages": fk.get("number_of_pages"),
            "hsn_code": fk.get("hsn_code"),
            "gst_rate": f"{fk.get('gst_rate_percent')}%",
            "mrp": f"₹{fk.get('mrp_inr')}",
            "selling_price": f"₹{fk.get('selling_price_inr')}",
            "procurement_sla": f"{fk.get('procurement_sla_days')} Days",
            "package_dimensions": f"{fk.get('dimensions_cm', {}).get('length')} cm x {fk.get('dimensions_cm', {}).get('breadth')} cm x {fk.get('dimensions_cm', {}).get('height')} cm",
            "package_weight": f"{fk.get('weight_grams')} grams ({round(fk.get('weight_grams', 250)/1000.0, 3)} kg)",
            "highlights": fk.get("highlights", []),
            "synopsis": fk.get("synopsis", ""),
            "search_keywords": fk.get("search_keywords", []),
            "listing_status": "ACTIVE"
        }
        card_path = book_dir / "flipkart_listing_card.json"
        card_path.write_text(json.dumps(card_data, indent=2), encoding="utf-8")
        return card_path

    def export_amazon_dossier_markdown(self, book_dir: Path, dossier: Dict[str, Any]) -> Path:
        """Generates an organized, 1-click copy Markdown listing sheet for Amazon KDP."""
        amz = dossier.get("amazon_kdp", {})
        pricing = amz.get("pricing", {})
        inr_p = pricing.get("inr", {})
        usd_p = pricing.get("usd", {})
        specs = amz.get("print_specifications", {})

        keywords = amz.get("backend_keywords", [])
        categories = amz.get("browse_categories", [])

        md_content = f"""# Amazon KDP Publishing Dossier
**Book Title:** {amz.get('title')}
**Subtitle:** {amz.get('subtitle')}
**Author:** {amz.get('author_first_name', '')} {amz.get('author_last_name', '')}

---

## 1. Book Details (Step 1 of KDP Wizard)

### Primary Title
```text
{amz.get('title')}
```

### Subtitle
```text
{amz.get('subtitle')}
```

### Primary Author
- **First Name:** `{amz.get('author_first_name', '')}`
- **Last Name:** `{amz.get('author_last_name', '')}`

### Publishing Rights
- Select: **`I own the copyright and I hold the necessary publishing rights.`**

### Formatted HTML Book Description (Copy & Paste into KDP Description box)
```html
{amz.get('html_description')}
```

---

## 2. 7 Amazon Backend Search Keywords (Exact Slots)
*These 7 slots are specifically engineered for Amazon KDP search engine indexing:*

1. `{keywords[0] if len(keywords) > 0 else ''}`
2. `{keywords[1] if len(keywords) > 1 else ''}`
3. `{keywords[2] if len(keywords) > 2 else ''}`
4. `{keywords[3] if len(keywords) > 3 else ''}`
5. `{keywords[4] if len(keywords) > 4 else ''}`
6. `{keywords[5] if len(keywords) > 5 else ''}`
7. `{keywords[6] if len(keywords) > 6 else ''}`

---

## 3. Categories & BISAC Codes (Target 3 Categories)
{chr(10).join(f"- **Category {idx+1}:** `{cat}`" for idx, cat in enumerate(categories))}

---

## 4. Paperback Print Specifications (Step 2 of KDP Wizard)
- **Print Options:** Black & white interior with white paper
- **Trim Size:** `{specs.get('trim_size', '6x9')} inches`
- **Bleed Settings:** `{specs.get('bleed', 'No Bleed')}`
- **Paperback Cover Finish:** `{specs.get('cover_finish', 'Matte')}`
- **Interior File:** Upload `manuscript_interior.pdf`
- **Cover File:** Upload `cover_full_wrap.pdf`

---

## 5. Rights & Pricing Strategy (Step 3 of KDP Wizard)
- **Territories:** Worldwide rights (all territories)
- **Primary Marketplace:** `Amazon.in` (or `Amazon.com`)
- **Royalty Plan:** `70%` (eBook) / `60%` (Paperback)
- **India (INR Pricing):**
  - Kindle eBook List Price: **₹{inr_p.get('ebook_list_price', 199)}**
  - Paperback List Price: **₹{inr_p.get('paperback_list_price', 499)}**
- **US (USD Pricing):**
  - Kindle eBook List Price: **${usd_p.get('ebook_list_price', 4.99)}**
  - Paperback List Price: **${usd_p.get('paperback_list_price', 14.99)}**
"""

        md_path = book_dir / "amazon_kdp_listing_sheet.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        return md_path

    def export_pod_manifest(self, book_dir: Path, dossier: Dict[str, Any]) -> Path:
        """Generates a complete bundle manifest for zero-inventory Print-On-Demand platforms (Notion Press, Pothi)."""
        manifest = {
            "platform_support": [
                "Notion Press (notionpress.com)",
                "Pothi (pothi.com)",
                "Amazon KDP (kdp.amazon.com)",
                "Flipkart Seller Hub (seller.flipkart.com)"
            ],
            "book_identity": {
                "title": dossier.get("book_title"),
                "subtitle": dossier.get("book_subtitle"),
                "author": dossier.get("author"),
                "publisher": dossier.get("publisher"),
                "page_count": dossier.get("page_count")
            },
            "files": {
                "interior_pdf": "manuscript_interior.pdf",
                "cover_wrap_pdf": "cover_full_wrap.pdf",
                "front_cover_jpg": "cover_front.jpg",
                "manuscript_markdown": "manuscript.md",
                "flipkart_catalog_excel": "flipkart_bulk_catalog.xlsx",
                "amazon_dossier_markdown": "amazon_kdp_listing_sheet.md"
            },
            "distribution_notes": {
                "flipkart_distribution_options": [
                    "Option A (Direct Seller): Upload 'flipkart_bulk_catalog.xlsx' to seller.flipkart.com with your GSTIN.",
                    "Option B (Zero-Inventory POD): Upload interior PDF & Cover to Notion Press or Pothi. They automatically list the book on Flipkart and Amazon India, print each copy on demand, and deposit royalties directly into your bank account."
                ]
            }
        }
        manifest_path = book_dir / "pod_distribution_manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        return manifest_path
