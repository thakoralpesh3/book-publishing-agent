"""Web Studio Backend (FastAPI)
Provides REST and download endpoints for the Book Publishing & Listing Agent.
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

import config
from core.gemini_engine import GeminiBookEngine
from core.book_writer import BookWriter
from core.manuscript_compiler import ManuscriptCompiler
from core.cover_generator import CoverGenerator
from core.metadata_engine import MetadataEngine
from core.catalog_exporter import CatalogExporter
from core.trend_radar import TrendRadar
from core.preflight_validator import PreflightValidator
from uploader.kdp_assistant import KDPAssistant
from uploader.flipkart_assistant import FlipkartAssistant

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="PublisheR AI - Amazon & Flipkart Publishing Studio")

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Mount static folder for mobile QR code and assets
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/api/health")
async def health_check():
    """Health check endpoint for Chhaya watchdog supervision."""
    return {"status": "healthy", "service": "PublisheR AI", "version": "1.0.0"}

@app.get("/api/model_info")
async def get_model_info():
    """Returns active AI model architecture (Gemini 4 Argon), context limits, and capabilities."""
    try:
        engine = GeminiBookEngine()
        return {
            "status": "success",
            "model_info": engine.get_model_status(),
            "gemini_4_argon_specs": config.GEMINI_4_ARGON_SPECS
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/mobile/status")
async def mobile_gateway_status():
    """Returns mobile access status, Cloudflare public URL, and QR code image."""
    try:
        from mobile_gateway import get_mobile_status
        return get_mobile_status()
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}

@app.get("/api/trends")
async def get_daily_trends(category: Optional[str] = None, q: Optional[str] = None):
    """Returns curated & live daily trends for Amazon KDP and Flipkart Seller Hub."""
    try:
        radar = TrendRadar()
        trends = radar.get_trends(category=category, search_query=q)
        return {
            "status": "success",
            "total": len(trends),
            "category": category or "all",
            "trends": trends
        }
    except Exception as e:
        logger.exception("Failed to load trends")
        return {"status": "error", "message": str(e), "trends": []}

@app.post("/api/trends/refresh")
async def refresh_daily_trends():
    """Scouts fresh trends from Amazon and Flipkart with Gemini market intelligence."""
    try:
        radar = TrendRadar()
        res = radar.scout_live_trends()
        return res
    except Exception as e:
        logger.exception("Failed to refresh trends")
        return {"status": "error", "message": str(e)}

class BookGenerationRequest(BaseModel):
    topic: str
    target_audience: Optional[str] = "General Reader / Professional"
    target_chapters: Optional[int] = 5
    author_name: Optional[str] = None
    publisher_name: Optional[str] = None
    trim_size: Optional[str] = "6x9"
    book_type: Optional[str] = "auto"
    trend_id: Optional[str] = None
    auto_upload: Optional[str] = None  # None, 'kdp', 'flipkart', or 'both'

class BackgroundRunRequest(BaseModel):
    force: bool = False
    category: Optional[str] = None
    topic: Optional[str] = None

@app.get("/api/background/status")
async def get_background_status():
    """Returns background autonomous publishing pipeline status, daily quota, and prerequisites."""
    try:
        from core.background_orchestrator import BackgroundPublishingOrchestrator
        orchestrator = BackgroundPublishingOrchestrator()
        tracker = orchestrator.get_tracker_data()
        prereqs = orchestrator.check_prerequisite_agents_status()
        return {
            "status": "success",
            "tracker": tracker,
            "prerequisites": prereqs,
            "is_due": orchestrator.is_daily_run_due()
        }
    except Exception as e:
        logger.exception("Error checking background status")
        return {"status": "error", "message": str(e)}

@app.post("/api/background/run")
async def trigger_background_run(req: BackgroundRunRequest, background_tasks: BackgroundTasks):
    """Triggers background autonomous daily book generation."""
    try:
        from core.background_orchestrator import BackgroundPublishingOrchestrator
        orchestrator = BackgroundPublishingOrchestrator()
        
        background_tasks.add_task(
            orchestrator.run_daily_publishing_pipeline,
            force=req.force,
            category=req.category,
            custom_topic=req.topic
        )
        return {
            "status": "queued",
            "message": "Autonomous background publishing pipeline queued successfully",
            "force": req.force
        }
    except Exception as e:
        logger.exception("Error triggering background run")
        return {"status": "error", "message": str(e)}


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"default_author": config.DEFAULT_AUTHOR_NAME, "default_publisher": config.DEFAULT_PUBLISHER_NAME}
    )

@app.get("/api/books")
async def list_books():
    """Lists all generated books in output directory."""
    books = []
    if config.OUTPUT_DIR.exists():
        for sub in config.OUTPUT_DIR.iterdir():
            if sub.is_dir():
                meta_file = sub / "listing_metadata.json"
                book_file = sub / "book_data.json"
                if meta_file.exists() or book_file.exists():
                    info = {"slug": sub.name, "folder": str(sub)}
                    if book_file.exists():
                        try:
                            with open(book_file, "r", encoding="utf-8") as f:
                                b_data = json.load(f)
                                info["title"] = b_data.get("title", sub.name)
                                info["author"] = b_data.get("author", "")
                                info["chapters_count"] = len(b_data.get("chapters", []))
                                info["pages"] = b_data.get("estimated_pages", 0)
                        except Exception:
                            pass
                    books.append(info)
    return {"books": books}

@app.get("/api/book/{slug}")
async def get_book_details(slug: str):
    """Returns the full book data, dossier, and generated file URLs."""
    book_dir = config.OUTPUT_DIR / slug
    if not book_dir.exists():
        raise HTTPException(status_code=404, detail=f"Book '{slug}' not found")

    meta_file = book_dir / "listing_metadata.json"
    book_file = book_dir / "book_data.json"

    meta_data = {}
    book_data = {}
    if meta_file.exists():
        with open(meta_file, "r", encoding="utf-8") as f:
            meta_data = json.load(f)
    if book_file.exists():
        with open(book_file, "r", encoding="utf-8") as f:
            book_data = json.load(f)

    files = {
        "manuscript_interior_pdf": (book_dir / "manuscript_interior.pdf").exists(),
        "cover_full_wrap_pdf": (book_dir / "cover_full_wrap.pdf").exists(),
        "cover_front_jpg": (book_dir / "cover_front.jpg").exists(),
        "flipkart_bulk_catalog_xlsx": (book_dir / "flipkart_bulk_catalog.xlsx").exists(),
        "amazon_kdp_listing_sheet_md": (book_dir / "amazon_kdp_listing_sheet.md").exists(),
        "pod_distribution_manifest_json": (book_dir / "pod_distribution_manifest.json").exists(),
        "manuscript_md": (book_dir / "manuscript.md").exists(),
    }

    # Pre-Flight Zero-Mistake Audit report
    audit_file = book_dir / "zero_mistake_audit.json"
    audit_data = {}
    if audit_file.exists():
        try:
            audit_data = json.loads(audit_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    if not audit_data and files.get("manuscript_interior_pdf"):
        try:
            validator = PreflightValidator(book_dir)
            audit_data = validator.run_full_audit()
        except Exception:
            pass

    return {
        "slug": slug,
        "book_data": book_data,
        "listing_metadata": meta_data,
        "files": files,
        "audit": audit_data
    }

@app.get("/api/validate/{slug}")
async def validate_book_api(slug: str):
    """Runs the 25-point Zero-Mistake Pre-Flight verification audit."""
    book_dir = config.OUTPUT_DIR / slug
    if not book_dir.exists():
        raise HTTPException(status_code=404, detail="Book directory not found")
    validator = PreflightValidator(book_dir)
    return validator.run_full_audit()

@app.post("/api/create_book")
async def create_book_endpoint(req: BookGenerationRequest):
    """End-to-end generator: outline -> write chapters -> compile PDF & cover -> generate Amazon & Flipkart metadata -> export spreadsheets."""
    try:
        engine = GeminiBookEngine()
        writer = BookWriter(engine)

        # Determine book_type
        b_type = req.book_type or "auto"
        if b_type == "auto":
            if any(k in req.topic.lower() for k in ["drawing", "draw", "coloring", "doodle", "tracing", "sketch"]):
                b_type = "activity_drawing"
            else:
                b_type = "standard"

        # Determine trim size (default 8.5x11 for kids drawing books, 6x9 for standard non-fiction/wealth)
        trim_size = req.trim_size or ("8.5x11" if b_type == "activity_drawing" else "6x9")
        if b_type == "activity_drawing" and req.trim_size in ["6x9", None]:
            trim_size = "8.5x11"

        compiler = ManuscriptCompiler(trim_size=trim_size)
        cover_gen = CoverGenerator(trim_size=trim_size)
        meta_engine = MetadataEngine(engine)
        exporter = CatalogExporter()

        # 1. Generate & Write Book
        book_data = writer.create_book(
            topic=req.topic,
            target_audience=req.target_audience or "General Reader",
            target_chapters=req.target_chapters or 5,
            custom_author=req.author_name,
            custom_publisher=req.publisher_name,
            book_type=b_type
        )
        book_dir = Path(book_data["book_dir"])

        # 2. Compile Interior PDF
        pdf_res = compiler.compile_pdf(
            book_data=book_data,
            output_path=book_dir / "manuscript_interior.pdf"
        )
        final_pages = pdf_res["page_count"]
        book_data["final_page_count"] = final_pages

        # 3. Generate Front Cover Graphic & Full-Wrap PDF
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

        # 4. Generate Amazon KDP & Flipkart Listing Metadata
        dossier = meta_engine.generate_all_metadata(book_data, page_count=final_pages, trim_size=trim_size)

        # 5. Export Flipkart Bulk Catalog (.xlsx) and Amazon KDP Markdown
        export_files = exporter.export_all(book_dir, dossier)

        # 6. Run 25-Point Pre-Flight Zero-Mistake Audit
        validator = PreflightValidator(book_dir)
        audit_report = validator.run_full_audit()

        # 7. Optional: Launch Auto-Upload Assistant immediately if requested
        auto_upload_job_id = None
        if req.auto_upload and req.auto_upload.lower() in ["kdp", "amazon", "flipkart", "both"]:
            try:
                from uploader.upload_manager import start_upload_job
                target_platform = "kdp" if req.auto_upload.lower() in ["kdp", "amazon", "both"] else "flipkart"
                auto_upload_job_id = start_upload_job(
                    slug=book_data["slug"],
                    platform=target_platform,
                    headless=False,
                    auto_advance=True
                )
                logger.info(f"Auto-upload assistant triggered for {target_platform.upper()} (Job ID: {auto_upload_job_id})")
            except Exception as e:
                logger.warning(f"Could not auto-start upload job: {e}")

        return {
            "status": "success",
            "slug": book_data["slug"],
            "title": book_data["title"],
            "pages": final_pages,
            "trim_size": trim_size,
            "pdf_interior": pdf_res["pdf_path"],
            "cover_wrap_pdf": wrap_res["cover_wrap_pdf"],
            "front_cover_jpg": wrap_res["front_cover_jpg"],
            "flipkart_excel": export_files["flipkart_excel"],
            "amazon_markdown": export_files["amazon_markdown"],
            "dossier": dossier,
            "audit": audit_report,
            "auto_upload_job_id": auto_upload_job_id
        }
    except Exception as e:
        logger.exception("Book creation failed")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/download/{slug}/{filename}")
async def download_file(slug: str, filename: str):
    """Download generated artifacts."""
    book_dir = config.OUTPUT_DIR / slug
    target = book_dir / filename
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path=str(target), filename=filename)

class UploadStartRequest(BaseModel):
    slug: str
    platform: str  # "kdp" or "flipkart"
    headless: Optional[bool] = False
    auto_advance: Optional[bool] = True

@app.post("/api/upload/start")
async def start_upload_endpoint(req: UploadStartRequest):
    """Launches an asynchronous upload job for Amazon KDP or Flipkart Seller Hub."""
    from uploader.upload_manager import start_upload_job
    try:
        job_id = start_upload_job(
            slug=req.slug,
            platform=req.platform,
            headless=req.headless or False,
            auto_advance=req.auto_advance if req.auto_advance is not None else True
        )
        return {"status": "started", "job_id": job_id, "platform": req.platform, "slug": req.slug}
    except Exception as e:
        logger.exception("Failed to start upload job")
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/upload/status/{job_id}")
async def get_upload_status_endpoint(job_id: str):
    """Returns current status, progress, and logs for an upload job."""
    from uploader.upload_manager import get_upload_job
    job = get_upload_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Upload job '{job_id}' not found")
    return job

@app.get("/api/upload/quick_copy/{slug}")
async def get_quick_copy_endpoint(slug: str):
    """Returns pre-formatted copy-paste attributes for Flipkart single listing."""
    book_dir = config.OUTPUT_DIR / slug
    if not book_dir.exists():
        raise HTTPException(status_code=404, detail="Book directory not found")
    try:
        assistant = FlipkartAssistant()
        return assistant.get_quick_copy_payload(book_dir)
    except Exception as e:
        logger.exception("Error extracting quick copy payload")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/upload/kdp")
async def trigger_kdp_upload(slug: str):
    """Launches Playwright KDP browser helper in background."""
    from uploader.upload_manager import start_upload_job
    book_dir = config.OUTPUT_DIR / slug
    if not book_dir.exists():
        raise HTTPException(status_code=404, detail="Book directory not found")
    try:
        job_id = start_upload_job(slug=slug, platform="kdp", headless=False, auto_advance=True)
        return {"status": "started", "job_id": job_id, "platform": "kdp", "slug": slug}
    except Exception as e:
        logger.exception("KDP assistant error")
        return {"status": "error", "message": str(e)}

@app.post("/api/upload/flipkart")
async def trigger_flipkart_upload(slug: str):
    """Validates Flipkart listing requirements and opens Flipkart Seller Hub in background."""
    from uploader.upload_manager import start_upload_job
    book_dir = config.OUTPUT_DIR / slug
    if not book_dir.exists():
        raise HTTPException(status_code=404, detail="Book directory not found")
    try:
        job_id = start_upload_job(slug=slug, platform="flipkart", headless=False)
        return {"status": "started", "job_id": job_id, "platform": "flipkart", "slug": slug}
    except Exception as e:
        logger.exception("Flipkart assistant error")
        return {"status": "error", "message": str(e)}

class GitSyncRequest(BaseModel):
    message: Optional[str] = None
    pull_first: bool = False

@app.get("/api/git/status")
async def get_git_status():
    """Returns current git repository and GitHub cloud sync status."""
    from core.git_manager import GitManager
    gm = GitManager()
    return gm.get_status()

@app.post("/api/git/sync")
async def trigger_git_sync(req: Optional[GitSyncRequest] = None):
    """Executes auto-stage, commit, and push to GitHub."""
    from core.git_manager import GitManager
    gm = GitManager()
    message = req.message if req else None
    pull_first = req.pull_first if req else False
    result = gm.sync(message=message, pull_first=pull_first)
    if not result.get("success") and "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result
