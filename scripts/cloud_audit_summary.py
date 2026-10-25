"""
PublisheR AI • Cloud Preflight Audit & Step Summary Reporter
Audits generated books in the cloud runner and produces a formatted GitHub Actions Step Summary.
"""

import os
import sys
import json
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.preflight_validator import PreflightValidator


def run_cloud_audit():
    out_dir = PROJECT_ROOT / "output"
    books = [p for p in out_dir.iterdir() if p.is_dir() and (p / "metadata.json").exists()]

    run_num = os.environ.get("RUN_NUMBER", "1")
    model_name = os.environ.get("CHOSEN_MODEL", "gemini-4-argon")

    summary_lines = [
        "# 📚 PublisheR AI • Cloud Publication Report",
        "",
        f"**Run Number:** `#{run_num}` | **Active Engine:** `{model_name}`",
        "",
        "| Book Title | Trim Size | Pages | Preflight Audit | Status |",
        "|---|---|---|---|---|"
    ]

    if not books:
        print("⚠️ No new books found to validate.")
        summary_lines.append("| None | - | - | - | ⚠️ No Books Found |")
    else:
        has_critical = False
        for b in books:
            print(f"Auditing {b.name}...")
            res = PreflightValidator.audit_book_directory(b)
            meta = {}
            try:
                meta = json.loads((b / "metadata.json").read_text(encoding="utf-8"))
            except Exception:
                pass

            title = meta.get("title", b.name)
            trim = meta.get("trim_size", "6x9")
            pages = meta.get("total_pages", "-")
            score = f"**{res.compliance_score}%**"
            status = "✅ Certified" if res.certified else "❌ Failed"

            summary_lines.append(f"| **{title}** | {trim} | {pages} | {score} | {status} |")
            print(f"Score: {res.compliance_score}% | Certified: {res.certified}")

            if not res.certified:
                print(f"Critical errors for {b.name}:", res.critical_errors)
                has_critical = True

        if has_critical:
            print("❌ One or more books failed Zero-Mistake Preflight Audit.")
            sys.exit(1)

    print("✅ All generated books passed Zero-Mistake Preflight Audit!")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write("\n".join(summary_lines) + "\n")


if __name__ == "__main__":
    run_cloud_audit()
