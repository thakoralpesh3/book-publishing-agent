# PublisheR AI — Amazon KDP & Flipkart Book Publishing Agent

An autonomous agent that generates complete publication-ready books, formats them into print-ready interior PDFs and full-wrap covers with exact spine thickness calculations, generates comprehensive listing metadata compliant with **Amazon KDP** and **Flipkart Seller Hub**, and assists in uploading them for sale.

---

## Key Capabilities

1. **Book Drafting & Typesetting Engine**:
   - Researches and drafts full books (outline, front matter, body chapters, back matter, reader reviews CTA).
   - Compiles print-ready interior PDFs using ReportLab matching 6"x9" or 5.5"x8.5" trim standards, inner gutter margins, running headers, and page numbering.
   - Generates high-resolution front cover artwork (1600x2560 px JPG) and full-wrap paperback print cover PDFs (Front + Spine + Back + 0.125" bleed) with barcode zones.
   - Accurately calculates spine thickness using page count: `Page Count * 0.002252 inches`.

2. **Listing Metadata Intelligence**:
   - **Amazon KDP**:
     - KDP-compliant HTML book description (using allowed `<h3>`, `<b>`, `<i>`, `<ul><li>` tags).
     - Exactly 7 backend search keyword slots targeted to purchase intent.
     - 3 Amazon Browse Categories and BISAC codes.
     - India (INR) & US (USD) pricing tables with 70% royalty breakdowns.
   - **Flipkart Seller Hub**:
     - SKU ID, ISBN-13 format, vertical mapping (`Books`).
     - HSN Code `4901.10.00` (Printed books attract 0% GST in India).
     - Package dimensions (L x B x H in cm) and packaged courier weight in grams (used by Ekart logistics for shipping fee tiers).
     - 6 Key Highlights formatted for Flipkart mobile app product cards.
     - MRP and Selling Price with optimal margin calculations.

3. **Upload & Export Formats**:
   - **Flipkart Bulk Catalog (.xlsx)**: Official 26-column spreadsheet formatted according to Flipkart Seller Hub's Books vertical requirements.
   - **Amazon KDP Dossier (.md & .json)**: One-click copy markdown sheet for fast manual or assisted entry.
   - **Zero-Inventory Print-on-Demand (POD) Bundle**: Pre-packaged manifest for platforms like Notion Press and Pothi, which automatically print and ship books on each Flipkart/Amazon customer order without holding stock.
   - **Playwright Browser Upload Assistant**: Automates KDP and Flipkart listing workflows in a persistent Chrome session.

---

## Quick Start

### 1. Launch the Web Studio (Local Desktop)
```bash
cd /home/alpesh/book-publishing-agent
./launch.sh
```
Open **http://localhost:8550** in your browser.

### 2. Launch Mobile Gateway (Project Chhaya 24/7 Remote Access)
Access both **Amazon KDP Agent** and **Flipkart Agent** on any smartphone anywhere (WiFi or 4G/5G):
```bash
cd /home/alpesh/book-publishing-agent
./launch_mobile.sh
```
- Establishes an encrypted Cloudflare HTTPS tunnel (`https://*.trycloudflare.com`).
- Prints an ASCII QR code in your terminal and generates `ui/static/mobile_qr.png`.
- Simply scan the QR code with your mobile camera to control both agents from your phone!
- Optional 24/7 background systemd service: `sudo cp publisher-chhaya.service /etc/systemd/system/ && sudo systemctl enable --now publisher-chhaya`.

### 3. Generate a Book via CLI
```bash
python3 main.py generate --topic "The 7-Day Mindset Reset" --chapters 5 --author "Alpesh Patel"
```

### 3. Validate Listing Compliance
```bash
python3 main.py validate --slug the_7-day_mindset_reset
```

### 4. Launch Browser Upload Assistants
- Amazon KDP:
  ```bash
  python3 main.py upload-kdp --slug the_7-day_mindset_reset
  ```
- Flipkart Seller Hub:
  ```bash
  python3 main.py upload-flipkart --slug the_7-day_mindset_reset
  ```

---

## Publishing Pathways Explained

### Pathway A: Amazon KDP (Direct Global Publishing)
1. Log in to [kdp.amazon.com](https://kdp.amazon.com).
2. Click **+ Create** -> Choose **Paperback** or **Kindle eBook**.
3. Use the **Copy HTML** button in the Web Studio to paste the description.
4. Paste the 7 backend search keywords into KDP's 7 keyword slots.
5. Upload `manuscript_interior.pdf` and `cover_full_wrap.pdf`.
6. Set India (`amazon.in`) and US (`amazon.com`) list prices. Amazon handles print-on-demand printing, shipping, and direct royalty payout.

### Pathway B: Flipkart Seller Hub (Direct Merchant Listing)
1. Log in to [seller.flipkart.com](https://seller.flipkart.com).
2. Go to **Listings** -> **Add New Listings** -> **Add in Bulk**.
3. Select Vertical: **Books**.
4. Upload the generated `flipkart_bulk_catalog.xlsx`.
5. Enter HSN code `4901.10.00` and confirm package weight and dimensions.

### Pathway C: Zero-Inventory Print-On-Demand (Flipkart + Amazon Combined)
If you do not hold physical inventory or an Indian GSTIN for courier pickup, you can upload the generated interior PDF and cover wrap to **Notion Press** (`notionpress.com`) or **Pothi** (`pothi.com`). These distributors automatically list your book on **both Flipkart and Amazon India**, print each copy on demand when an order comes in, and deposit the profit directly into your bank account!

---

## Project Structure
```
book-publishing-agent/
├── config.py                     # Rules, dimensions, spine math, and platform standards
├── core/
│   ├── gemini_engine.py          # Resilient Google GenAI engine with model fallbacks & backoff
│   ├── book_writer.py            # Drafts outline, chapters, and front/back matter
│   ├── manuscript_compiler.py    # ReportLab print-ready PDF typesetter (6x9, gutters, headers)
│   ├── cover_generator.py        # Front cover art & full-wrap PDF with exact spine math
│   ├── metadata_engine.py        # Amazon KDP & Flipkart Seller Hub listing generator
│   ├── catalog_exporter.py       # Flipkart bulk Excel (.xlsx) & Amazon markdown (.md) exporter
│   ├── git_manager.py            # Automated git commit, stage, pull, and push engine
│   └── git_watcher.py            # 24/7 filesystem watcher & debounced Antigravity auto-sync
├── uploader/
│   ├── kdp_assistant.py          # Playwright KDP browser helper
│   ├── flipkart_assistant.py     # Flipkart compliance validator & browser assistant
│   ├── upload_manager.py         # Asynchronous upload worker pool and status tracker
│   └── pending_queue.py          # Store-and-forward upload queue with platform health prober
├── ui/
│   ├── app.py                    # FastAPI server
│   └── templates/index.html      # Modern Glassmorphism Web Studio & Mobile Gateway
├── main.py                       # Unified CLI and server runner
├── mobile_gateway.py             # 24/7 watchdog supervisor & Cloudflare tunnel gateway
├── .github/workflows/
│   ├── ci.yml                    # CI test suite runner (Python 3.11 & 3.12)
│   └── daily_publisher.yml       # Cloud book publishing pipeline with releases
└── output/                       # Output workspace for books, covers, and catalogs
```

---

## 🚀 Running PublisheR AI Directly From GitHub (Cloud Execution)

PublisheR AI can execute completely in the cloud on GitHub Actions runners without requiring local hardware or an active computer:

1. **GitHub Repository**: [**`thakoralpesh3/book-publishing-agent`**](https://github.com/thakoralpesh3/book-publishing-agent)
2. **On-Demand Execution**:
   - Go to the **Actions** tab $\rightarrow$ select **PublisheR AI • Cloud Book Publishing Pipeline**.
   - Click **Run workflow**.
   - Choose:
     - **Custom Topic** (or leave blank to auto-pick from daily Amazon & Flipkart trends).
     - **Trending Category**: `kids`, `wealth`, `self-help`, `tech`, `business`.
     - **Gemini Model**: `gemini-4-argon`, `gemini-3.7-flash`, `gemini-3.8-flash`.
     - **Trim Size**: `6x9`, `8.5x11`, `5.5x8.5`.
     - **Chapters** & **Book Structure Type**.
     - **Author** & **Publisher** names.
   - Click **Run workflow**.
3. **Automated Verification & Release**:
   - The runner drafts the entire book, typesets the ReportLab interior PDF and full-wrap cover, generates Flipkart bulk Excel and Amazon KDP listings, and runs the 25-Point Zero-Mistake Preflight Audit.
   - Automatically publishes a **GitHub Release** (`book-run-<RUN_NUMBER>`) attaching the downloadable PDF interior, cover PDF, cover artwork JPG, and Flipkart catalog spreadsheet.

4. **Scheduled Cloud Runs**:
   - Automatically runs every day at **02:00 UTC** (07:30 AM IST) scouting trending niches and generating fresh publication-ready books.

---

## ⚡ Autonomous Antigravity $\leftrightarrow$ GitHub Synchronization

PublisheR AI features an autonomous, real-time filesystem watcher ([`core/git_watcher.py`](file:///home/alpesh/book-publishing-agent/core/git_watcher.py)) that seamlessly keeps GitHub up to date:

- **24/7 Watchdog Integration**: Runs continuously in the background under `publisher-ai.service`.
- **Zero-Touch Sync**: Whenever Antigravity or the user modifies, creates, or refactors any code or documentation, the watcher automatically debounces the edits (10s window), stages the files, generates a structured commit message, and pushes to `origin/main`.
- **Safety Shielding**: Ignores temporary logs, build outputs, `.env` API keys, and cache directories.
- **Manual CLI Commands**:
  ```bash
  # Check cloud sync status
  python3 main.py git-status

  # Manual sync and push
  python3 main.py git-sync -m "Your commit message"

  # Run standalone watcher
  python3 main.py watch-git --debounce 10
  ```

---

## 💾 Resilient Store-and-Forward Upload Queue

If an upload to Amazon KDP or Flipkart encounters platform downtime, network dropouts, or Captcha prompts:
- All generated files are preserved in `output/<slug>/`.
- The upload is tracked in `data/pending_uploads.json` with exponential backoff (`[2m, 5m, 15m, 30m, 60m]`).
- The 24/7 background watchdog checks platform reachability (`kdp.amazon.com`, `seller.flipkart.com`) and automatically retries pending uploads once the connection is healthy.
- **CLI Commands**:
  ```bash
  python3 main.py pending-uploads
  python3 main.py retry-pending [--force]
  ```

