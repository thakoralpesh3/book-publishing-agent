"""Main Entry Point for PublisheR AI
Run either the Web Studio UI or CLI commands for book generation & upload assistance.
"""

import sys
import argparse
import webbrowser
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

import uvicorn

import config
from core.gemini_engine import GeminiBookEngine
from core.book_writer import BookWriter
from core.manuscript_compiler import ManuscriptCompiler
from core.cover_generator import CoverGenerator
from core.metadata_engine import MetadataEngine
from core.catalog_exporter import CatalogExporter
from core.trend_radar import TrendRadar
from uploader.kdp_assistant import KDPAssistant
from uploader.flipkart_assistant import FlipkartAssistant

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("PublisheR")

def run_generate_cli(
    topic: str,
    chapters: int = 5,
    author: str = config.DEFAULT_AUTHOR_NAME,
    publisher: str = config.DEFAULT_PUBLISHER_NAME,
    trim_size: str = "6x9",
    book_type: str = "auto",
    audience: str = "General Reader",
    upload: str = "none"
):
    # Auto-detect book type
    if book_type == "auto":
        if any(k in topic.lower() for k in ["drawing", "draw", "coloring", "doodle", "tracing", "sketch"]):
            book_type = "activity_drawing"
        else:
            book_type = "standard"

    # Adaptive trim size: Kids activity and drawing books standard is 8.5x11
    if book_type == "activity_drawing" and trim_size == "6x9":
        trim_size = "8.5x11"

    logger.info(f"Starting generation for topic: '{topic}' [Type: {book_type}, Trim: {trim_size}]")
    engine = GeminiBookEngine()
    writer = BookWriter(engine)
    compiler = ManuscriptCompiler(trim_size=trim_size)
    cover_gen = CoverGenerator(trim_size=trim_size)
    meta_engine = MetadataEngine(engine)
    exporter = CatalogExporter()

    print(f"\n[1/5] Drafting {book_type.replace('_', ' ')} blueprint & chapters with Gemini...")
    book_data = writer.create_book(
        topic=topic,
        target_audience=audience,
        target_chapters=chapters,
        custom_author=author,
        custom_publisher=publisher,
        book_type=book_type
    )
    book_dir = Path(book_data["book_dir"])
    print(f"Manuscript drafted: {book_data['title']} ({book_data['total_words']} words, {book_data['estimated_pages']} est pages)")


    print("\n[2/5] Compiling print-ready interior PDF (ReportLab)...")
    pdf_res = compiler.compile_pdf(
        book_data=book_data,
        output_path=book_dir / "manuscript_interior.pdf"
    )
    final_pages = pdf_res["page_count"]
    print(f"PDF compiled: {pdf_res['pdf_path']} ({final_pages} pages)")

    print("\n[3/5] Generating front cover graphic & full-wrap print PDF...")
    front_jpg = book_dir / "cover_front.jpg"
    cover_gen.generate_front_cover_image(
        title=book_data["title"],
        subtitle=book_data.get("subtitle", ""),
        author=book_data["author"],
        output_path=front_jpg
    )
    wrap_res = cover_gen.generate_full_wrap_pdf(
        book_data=book_data,
        page_count=final_pages,
        front_cover_img_path=front_jpg,
        output_pdf_path=book_dir / "cover_full_wrap.pdf"
    )
    print(f"Cover wrap generated (Spine width: {wrap_res['spine_width_inches']} in)")

    print("\n[4/5] Generating Amazon KDP and Flipkart Seller Hub metadata...")
    dossier = meta_engine.generate_all_metadata(book_data, page_count=final_pages)

    print("\n[5/5] Exporting Flipkart bulk catalog (.xlsx) & Amazon listing dossier (.md)...")
    export_files = exporter.export_all(book_dir, dossier)

    print("\n" + "="*70)
    print("✨ BOOK & LISTINGS SUCCESSFULLY GENERATED! ✨")
    print("="*70)
    print(f"📁 Output Directory:      {book_dir.resolve()}")
    print(f"📄 Interior PDF:          {pdf_res['pdf_path']}")
    print(f"🎨 Full-Wrap Cover PDF:   {wrap_res['cover_wrap_pdf']}")
    print(f"📊 Flipkart Bulk Excel:   {export_files['flipkart_excel']}")
    print(f"📝 Amazon Listing Sheet:  {export_files['amazon_markdown']}")

    from core.preflight_validator import PreflightValidator
    validator = PreflightValidator(book_dir)
    audit = validator.run_full_audit()
    print(f"🛡️ Zero-Mistake Audit:    {audit.get('compliance_score')} ({audit.get('passed_checks_count')}/25 Checks Passed)")
    print("="*70 + "\n")

    # Post-generation upload if requested
    if upload and upload.lower() != "none":
        print("="*70)
        print(f"🚀 INITIATING POST-GENERATION UPLOAD ({upload.upper()})...")
        print("="*70)
        if upload.lower() in ["kdp", "amazon", "both"]:
            print("\nLaunching Amazon KDP Upload Assistant...")
            kdp = KDPAssistant()
            kdp.launch_assisted_session(book_dir, headless=False)
        if upload.lower() in ["flipkart", "both"]:
            print("\nLaunching Flipkart Seller Hub Assistant...")
            fk = FlipkartAssistant()
            fk.launch_assisted_session(book_dir, headless=False)

def _open_browser_after_healthy(url: str, port: int):
    """Waits until FastAPI is healthy before opening the browser to prevent 'Unable to connect' error."""
    import time
    import urllib.request
    for _ in range(40):
        time.sleep(0.3)
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/health", headers={"User-Agent": "HealthChecker/1.0"})
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status == 200:
                    time.sleep(0.5)
                    try:
                        # Prefer opening directly in default desktop browser
                        import subprocess
                        if Path("/usr/bin/firefox").exists():
                            subprocess.Popen(["firefox", "--new-window", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        else:
                            webbrowser.open(url)
                    except Exception:
                        webbrowser.open(url)
                    return
        except Exception:
            pass

def run_server(port: int = 8550, open_browser: bool = True, with_mobile_tunnel: bool = True):
    import socket
    import subprocess
    import threading

    url = f"http://127.0.0.1:{port}"
    print("\n" + "="*70)
    print(f"🚀 PublisheR AI Web Studio launching on: {url}")
    print("="*70 + "\n")

    # Check if port is already running
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        if s.connect_ex(("127.0.0.1", port)) == 0:
            import urllib.request
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1.0) as resp:
                    if resp.status == 200:
                        print(f"✅ Studio is already running and healthy on {url}!")
                        if open_browser:
                            webbrowser.open(url)
                        return
            except Exception:
                print(f"Port {port} is occupied by an unresponsive process. Freeing port...")
                subprocess.run(f"fuser -k {port}/tcp 2>/dev/null || true", shell=True)
                import time
                time.sleep(1)

    if open_browser:
        t = threading.Thread(target=_open_browser_after_healthy, args=(url, port), daemon=True)
        t.start()

    # Launch mobile tunnel in background if requested
    if with_mobile_tunnel:
        def _start_tunnel_async():
            try:
                from mobile_gateway import MobileGatewayWatchdog
                gw = MobileGatewayWatchdog(port=port)
                # Wait 3 seconds for server to bind
                import time
                time.sleep(3)
                gw.start_tunnel()
            except Exception as e:
                logger.debug(f"Mobile tunnel background init: {e}")
        t_tunnel = threading.Thread(target=_start_tunnel_async, daemon=True)
        t_tunnel.start()

    uvicorn.run("ui.app:app", host="0.0.0.0", port=port, reload=False)

def run_trends_cli(category: Optional[str] = None, query: Optional[str] = None):
    radar = TrendRadar()
    trends = radar.get_trends(category=category, search_query=query)
    print("\n" + "="*80)
    print("🔥 DAILY TREND RADAR — Top Amazon & Flipkart Book Niches 🔥")
    print("="*80)
    for idx, t in enumerate(trends, 1):
        print(f"\n[{idx}] {t.get('title')}")
        print(f"    ID:           {t.get('id')}")
        print(f"    Category:     {t.get('category_name')} ({t.get('category')}) | Badge: {t.get('badge', 'Bestseller')}")
        print(f"    Format:       {t.get('book_type')} | Trim: {t.get('suggested_trim_size')} | Chapters: {t.get('suggested_chapters', 5)}")
        print(f"    Demand:       {t.get('demand_score')}/100 | Competition: {t.get('competition_score')} | Profit: {t.get('profit_potential')}")
        print(f"    Audience:     {t.get('target_audience')}")
        if t.get('amazon_signals'):
            print(f"    Amazon:       {t['amazon_signals'][0]}")
        if t.get('flipkart_signals'):
            print(f"    Flipkart:     {t['flipkart_signals'][0]}")
    print("\n" + "="*80)
    print("💡 To generate a book from any trend above, run:")
    print("   python3 main.py generate --trend <ID>\n")

def run_refresh_trends_cli():
    print("\n🔍 Scouting live trends across Amazon and Flipkart via Gemini...")
    radar = TrendRadar()
    res = radar.scout_live_trends()
    print(f"✅ Refresh status: {res.get('status')} | Total trends active: {res.get('count', 0)}\n")

def main():
    parser = argparse.ArgumentParser(description="PublisheR AI — Amazon & Flipkart Publishing Agent")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Serve command
    serve_p = subparsers.add_parser("serve", help="Launch Web Studio Dashboard")
    serve_p.add_argument("--port", type=int, default=8550, help="Port to listen on (default: 8550)")
    serve_p.add_argument("--no-browser", action="store_true", help="Do not open browser automatically")

    # Trends command
    trends_p = subparsers.add_parser("trends", help="View daily trending book niches on Amazon & Flipkart")
    trends_p.add_argument("--category", "-c", type=str, default=None, choices=["all", "kids", "wealth", "mindset", "tech", "health"], help="Filter by niche category")
    trends_p.add_argument("--query", "-q", type=str, default=None, help="Search trends by keyword")

    # Refresh Trends command
    subparsers.add_parser("refresh-trends", help="Scout fresh daily trends from Amazon & Flipkart via Gemini")

    # Generate command
    gen_p = subparsers.add_parser("generate", help="Generate book and listings via CLI")
    gen_p.add_argument("--topic", type=str, default=None, help="Book topic or concept")
    gen_p.add_argument("--trend", type=str, default=None, help="ID of trend from trend radar to generate")
    gen_p.add_argument("--book-type", type=str, default="auto", choices=["auto", "standard", "activity_drawing", "workbook_journal"], help="Book structure type")
    gen_p.add_argument("--chapters", type=int, default=5, help="Number of chapters (default: 5)")
    gen_p.add_argument("--author", type=str, default=config.DEFAULT_AUTHOR_NAME, help="Author name")
    gen_p.add_argument("--publisher", type=str, default=config.DEFAULT_PUBLISHER_NAME, help="Publisher name")
    gen_p.add_argument("--trim-size", type=str, default="6x9", choices=["6x9", "5.5x8.5", "8.5x11"], help="Trim size")
    gen_p.add_argument("--upload", type=str, choices=["none", "kdp", "flipkart", "both"], default="none", help="Immediately launch upload assistant after generation")

    # Background execution commands
    bg_p = subparsers.add_parser("run-background", help="Run daily publishing pipeline autonomously in background")
    bg_p.add_argument("--force", action="store_true", help="Force execution even if daily quota is reached")
    bg_p.add_argument("--category", type=str, default=None, help="Preferred trend category (kids, wealth, etc.)")
    bg_p.add_argument("--topic", type=str, default=None, help="Custom topic override")
    bg_p.add_argument("--auto-upload", type=str, choices=["none", "kdp", "flipkart", "both"], default="none", help="Auto upload to platform after generation")

    watch_p = subparsers.add_parser("watch-and-run", help="Watch for Aradhya, YouTube & Social agents completion, then execute")
    watch_p.add_argument("--poll-interval", type=int, default=15, help="Poll interval in seconds (default: 15)")
    watch_p.add_argument("--timeout", type=int, default=1800, help="Max wait timeout in seconds (default: 1800)")

    # Validate command
    val_p = subparsers.add_parser("validate", help="Validate Flipkart listing data")
    val_p.add_argument("--slug", type=str, required=True, help="Book slug")


    # Upload commands
    kdp_p = subparsers.add_parser("upload-kdp", help="Launch Amazon KDP Playwright assistant")
    kdp_p.add_argument("--slug", type=str, required=True, help="Book slug")

    fk_p = subparsers.add_parser("upload-flipkart", help="Launch Flipkart Seller Hub assistant")
    fk_p.add_argument("--slug", type=str, required=True, help="Book slug")

    # Git sync commands
    sync_p = subparsers.add_parser("git-sync", help="Synchronize and push changes to GitHub")
    sync_p.add_argument("-m", "--message", type=str, default=None, help="Commit message")
    sync_p.add_argument("--pull", action="store_true", help="Pull upstream before pushing")

    status_p = subparsers.add_parser("git-status", help="Show GitHub cloud synchronization status")

    args = parser.parse_args()

    if args.command == "serve" or args.command is None:
        port = getattr(args, "port", 8550)
        no_b = getattr(args, "no_browser", False)
        run_server(port=port, open_browser=not no_b)

    elif args.command == "trends":
        run_trends_cli(category=args.category, query=args.query)

    elif args.command == "refresh-trends":
        run_refresh_trends_cli()

    elif args.command == "generate":
        topic = args.topic
        chapters = args.chapters
        trim_size = args.trim_size
        book_type = args.book_type
        audience = "General Reader"

        if args.trend:
            radar = TrendRadar()
            trend_obj = radar.get_trend_by_id(args.trend)
            if not trend_obj:
                print(f"❌ Error: Trend ID '{args.trend}' not found. Run 'python3 main.py trends' to see available trends.")
                return
            topic = topic or trend_obj.get("topic") or trend_obj.get("title")
            audience = trend_obj.get("target_audience", audience)
            if book_type == "auto":
                book_type = trend_obj.get("book_type", "auto")
            if trim_size == "6x9" and trend_obj.get("suggested_trim_size"):
                trim_size = trend_obj.get("suggested_trim_size")
            if args.chapters == 5 and trend_obj.get("suggested_chapters"):
                chapters = trend_obj.get("suggested_chapters")

        if not topic:
            print("❌ Error: Must specify --topic or --trend <ID>. Run 'python3 main.py trends' to see ideas.")
            return

        run_generate_cli(
            topic=topic,
            chapters=chapters,
            author=args.author,
            publisher=args.publisher,
            trim_size=trim_size,
            book_type=book_type,
            audience=audience,
            upload=getattr(args, "upload", "none")
        )

    elif args.command == "run-background":
        from core.background_orchestrator import BackgroundPublishingOrchestrator
        orchestrator = BackgroundPublishingOrchestrator()
        result = orchestrator.run_daily_publishing_pipeline(
            force=args.force,
            category=args.category,
            custom_topic=args.topic,
            auto_upload=getattr(args, "auto_upload", "none")
        )
        print(f"\nBackground Pipeline Result: {result.get('status')}")
        if result.get("book_slug"):
            print(f"Book Generated: {result.get('title')} ({result.get('book_slug')})")
            print(f"Output Directory: {result.get('output_dir')}")
        elif result.get("message"):
            print(f"Notice: {result.get('message')}")

    elif args.command == "watch-and-run":
        from core.background_orchestrator import BackgroundPublishingOrchestrator
        orchestrator = BackgroundPublishingOrchestrator()
        result = orchestrator.watch_and_run(
            poll_interval_seconds=args.poll_interval,
            max_wait_seconds=args.timeout
        )
        print(f"\nWatch and Run Result: {result.get('status')}")

    elif args.command == "validate":
        from core.preflight_validator import PreflightValidator
        book_dir = config.OUTPUT_DIR / args.slug
        if not book_dir.exists():
            print(f"❌ Error: Book directory not found: {book_dir}")
            return
        validator = PreflightValidator(book_dir)
        res = validator.run_full_audit()

        print("\n" + "="*75)
        print("🛡️  PUBLISHER AI — ZERO-MISTAKE PRE-FLIGHT PUBLISHING AUDIT  🛡️")
        print("="*75)
        status_str = "✅ ZERO-MISTAKE CERTIFIED" if res.get("zero_mistake_certified") else "⚠️ COMPLIANCE ATTENTION NEEDED"
        print(f"Status:             {status_str}")
        print(f"Compliance Score:   {res.get('compliance_score')} ({res.get('passed_checks_count')}/{res.get('total_checks_count')} checks passed)")
        readiness = res.get("platform_readiness", {})
        print(f"Amazon KDP Ready:   {'YES [✓]' if readiness.get('amazon_kdp_ready') else 'NO [✗]'}")
        print(f"Flipkart Ready:     {'YES [✓]' if readiness.get('flipkart_ready') else 'NO [✗]'}")
        print(f"POD Ready:          {'YES [✓]' if readiness.get('pod_aggregators_ready') else 'NO [✗]'}")
        print("-" * 75)

        print("\n[Passed Checks]:")
        for c in res.get("passed_checks", []):
            print(f"  [✓] {c.get('check')}: {c.get('detail')}")

        if res.get("warnings"):
            print("\n[Warnings]:")
            for w in res.get("warnings"):
                print(f"  [!] {w}")

        if res.get("issues"):
            print("\n[Blocking Issues]:")
            for err in res.get("issues"):
                print(f"  [✗] {err}")
        print("="*75 + "\n")

    elif args.command == "upload-kdp":
        book_dir = config.OUTPUT_DIR / args.slug
        assistant = KDPAssistant()
        res = assistant.launch_assisted_session(book_dir, headless=False)
        print("\nKDP Assistant Result:", res["status"])

    elif args.command == "upload-flipkart":
        book_dir = config.OUTPUT_DIR / args.slug
        assistant = FlipkartAssistant()
        res = assistant.launch_assisted_session(book_dir, headless=False)
        print("\nFlipkart Assistant Result:", res["status"])

    elif args.command == "git-sync":
        from core.git_manager import GitManager
        gm = GitManager()
        res = gm.sync(message=args.message, pull_first=args.pull)
        if res.get("success"):
            print(f"✅ {res.get('message')}")
            if res.get("last_commit"):
                lc = res["last_commit"]
                print(f"📌 Latest Commit: {lc.get('hash')} - \"{lc.get('message')}\" by {lc.get('author')}")
        else:
            print(f"❌ Error: {res.get('error')}")

    elif args.command == "git-status":
        from core.git_manager import GitManager
        gm = GitManager()
        status = gm.get_status()
        print(f"📦 Branch: {status.get('branch')}")
        print(f"🌐 Remote: {status.get('remote_url') or 'None'}")
        print(f"📊 Changes: {status.get('total_changes', 0)} files")
        if status.get("changed_files"):
            for cf in status["changed_files"]:
                print(f"  [{cf['status']}] {cf['path']}")
        if status.get("last_commit"):
            lc = status["last_commit"]
            print(f"📌 Last Commit: {lc.get('hash')} - {lc.get('message')} ({lc.get('date')})")

if __name__ == "__main__":
    main()

