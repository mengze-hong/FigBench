"""Unified pipeline: download → extract → screen → analyze → store → cleanup.

Single entry point for all data processing. Supports:
  - Processing a specific ACL Anthology volume by ID
  - Processing a range of papers by numeric range
  - Processing already-downloaded PDFs
  - Retrying failed/pending figures
  - Full status reporting

Usage:
    # Process 50 papers from EMNLP 2025 main
    python -m pipeline.run --venue 2025.emnlp-main --range 1-50

    # Process 200 papers from ACL 2024 long
    python -m pipeline.run --venue 2024.acl-long --range 1-200

    # Retry all pending/error figures
    python -m pipeline.run --retry

    # Show status report
    python -m pipeline.run --status

    # Full cleanup (dedup + orphans)
    python -m pipeline.run --cleanup
"""

import sys
import os
import io
import json
import time
import hashlib
import uuid
import argparse
import re
from pathlib import Path
from typing import List, Optional, Tuple

# Fix encoding on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import pypdfium2 as pdfium
from PIL import Image

from config import (
    PDF_DIR, FIGURE_DIR, ACL_ANTHOLOGY_BASE,
    SCRAPE_DELAY, DOWNLOAD_TIMEOUT,
    PIPELINE_DELAY_BETWEEN_FIGURES, PIPELINE_DELAY_BETWEEN_PAPERS,
    MIN_FIGURE_WIDTH, MIN_FIGURE_HEIGHT, MIN_FIGURE_AREA,
    RENDER_SCALE, BLANK_THRESHOLD, MIN_FILE_SIZE,
)
from database import init_db, get_conn
from pipeline.analyzer import screen_and_analyze
from pipeline.extractor import extract_figures
from pipeline.maintenance import (
    dedup_figures, cleanup_orphans, cleanup_rejected,
    fix_venue_labels, print_status_report,
)
from log import get_logger

logger = get_logger("Pipeline")
init_db()


# ═══════════════════════════════════════════════════════════════════
# STEP 1: Download PDFs
# ═══════════════════════════════════════════════════════════════════

def _download_one(args) -> Optional[Path]:
    """Download a single PDF. Returns Path on success, None on failure."""
    paper_id, pdf_path, url = args
    try:
        r = requests.get(url, timeout=DOWNLOAD_TIMEOUT, stream=True,
                         headers={"User-Agent": "AcademicFigureGallery/1.0"})
        if r.status_code == 200 and "application/pdf" in r.headers.get("content-type", ""):
            with open(pdf_path, "wb") as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
            return pdf_path
        return None
    except Exception:
        return None


def download_papers(venue_id: str, start: int, end: int) -> List[Path]:
    """Download PDFs from ACL Anthology with concurrent threads.

    Uses ThreadPoolExecutor for ~8x speedup over sequential downloads.
    Already-cached files are skipped instantly.

    Args:
        venue_id: e.g. "2025.emnlp-main", "2024.acl-long"
        start: first paper number (inclusive)
        end: last paper number (inclusive)

    Returns:
        List of downloaded PDF paths (sorted by paper number).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    logger.info("Downloading %s papers %d-%d", venue_id, start, end)
    PDF_DIR.mkdir(parents=True, exist_ok=True)

    cached = []
    to_download = []

    for n in range(start, end + 1):
        paper_id = f"{venue_id}.{n}"
        pdf_path = PDF_DIR / f"{paper_id}.pdf"

        if pdf_path.exists() and pdf_path.stat().st_size > MIN_FILE_SIZE:
            cached.append(pdf_path)
        else:
            url = f"{ACL_ANTHOLOGY_BASE}/{paper_id}.pdf"
            to_download.append((paper_id, pdf_path, url))

    if cached:
        logger.info("  %d already cached, %d to download", len(cached), len(to_download))

    if not to_download:
        logger.info("  All %d papers already cached", len(cached))
        return sorted(cached)

    # Concurrent download with 8 threads
    WORKERS = 8
    new_downloads = []
    failed = 0

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(_download_one, args): args[0] for args in to_download}
        done = 0
        for future in as_completed(futures):
            done += 1
            result = future.result()
            if result:
                new_downloads.append(result)
            else:
                failed += 1
            # Progress every 50
            if done % 50 == 0:
                logger.info("  Progress: %d/%d downloaded...", done, len(to_download))

    elapsed = time.time() - t0
    all_pdfs = sorted(cached + new_downloads)
    logger.info("Download complete: %d total (%d new in %.1fs, %d cached, %d failed)",
                len(all_pdfs), len(new_downloads), elapsed, len(cached), failed)
    return all_pdfs


# ═══════════════════════════════════════════════════════════════════
# STEP 2: Extract title from PDF
# ═══════════════════════════════════════════════════════════════════

def extract_title(pdf_path: Path) -> str:
    """Extract paper title from the first page of a PDF.

    Skips conference headers, URLs, copyright notices.
    """
    try:
        doc = pdfium.PdfDocument(str(pdf_path))
        page = doc[0]
        tp = page.get_textpage()
        text = tp.get_text_range()
        doc.close()

        skip_prefixes = (
            "Proceedings", "https://", "http://", "November", "August",
            "January", "February", "March", "April", "May", "June", "July",
            "September", "October", "December", "Copyright", "\u00a9",
            "Association for", "Published by",
        )

        lines = [l.strip() for l in text.split("\n") if l.strip()]
        title_lines = []
        for line in lines:
            if any(line.startswith(p) for p in skip_prefixes):
                continue
            if len(line) < 5:
                continue
            title_lines.append(line)
            if len(" ".join(title_lines)) > 40:
                break

        title = " ".join(title_lines)[:300]
        return title if title else pdf_path.stem
    except Exception:
        return pdf_path.stem


# ═══════════════════════════════════════════════════════════════════
# STEP 3: Process a single paper (extract + screen + store)
# ═══════════════════════════════════════════════════════════════════

def process_single_paper(pdf_path: Path, dedup_hashes: set) -> dict:
    """Process one paper: extract figures → LLM screen each → store accepted.

    Args:
        pdf_path: Path to the PDF file
        dedup_hashes: Set of MD5 hashes for global deduplication

    Returns:
        dict: {paper_id, title, extracted, accepted, rejected, errors}
    """
    paper_id = pdf_path.stem
    result = {
        "paper_id": paper_id, "title": "", "venue": "", "year": 0,
        "extracted": 0, "accepted": 0, "rejected": 0, "errors": 0,
    }

    # Parse venue/year from paper_id (e.g. "2025.emnlp-main.42")
    m = re.match(r"(\d{4})\.(acl|emnlp|naacl|eacl)[-.](.*?)\.(\d+)", paper_id, re.IGNORECASE)
    if m:
        result["year"] = int(m.group(1))
        result["venue"] = m.group(2).upper()
    else:
        result["venue"] = "ACL"
        result["year"] = 2024

    # Check if already processed
    conn = get_conn()
    existing = conn.execute(
        "SELECT COUNT(*) FROM figures f JOIN papers p ON f.paper_id=p.id WHERE p.id=?",
        (paper_id,)
    ).fetchone()[0]
    conn.close()
    if existing > 0:
        return result  # Already done

    # Extract title
    title = extract_title(pdf_path)
    result["title"] = title
    logger.info("  Title: %s", title[:70])

    # Extract figures (precise cropping)
    try:
        figures = extract_figures(str(pdf_path), paper_id)
    except Exception as e:
        logger.error("  Extraction failed: %s", e)
        result["errors"] += 1
        return result

    result["extracted"] = len(figures)
    if not figures:
        logger.info("  No figures found")
        return result

    # Insert paper record
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO papers (id,title,authors,venue,year,url,pdf_url,pdf_path) VALUES (?,?,?,?,?,?,?,?)",
        (paper_id, title, "", result["venue"], result["year"],
         f"{ACL_ANTHOLOGY_BASE}/{paper_id}/",
         f"{ACL_ANTHOLOGY_BASE}/{paper_id}.pdf",
         str(pdf_path))
    )
    conn.commit()
    conn.close()

    # Screen + analyze each figure
    for fig in figures:
        fname = fig["filename"]
        caption = fig.get("caption", "")
        fig_path = FIGURE_DIR / fname

        # Global dedup check
        if fig_path.exists():
            h = hashlib.md5(fig_path.read_bytes()).hexdigest()
            if h in dedup_hashes:
                logger.info("    %s → DUPLICATE", fname[-30:])
                fig_path.unlink(missing_ok=True)
                continue
            dedup_hashes.add(h)

        # LLM screen + analyze
        logger.info("    %s → ", fname[-35:])
        analysis = screen_and_analyze(fname, caption)

        if analysis["accepted"]:
            # Store in DB
            fid = str(uuid.uuid4())[:8]
            conn = get_conn()
            conn.execute(
                """INSERT INTO figures (id,paper_id,filename,page_num,width,height,
                   description,tags,figure_type,caption,quality_score,layout_type) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (fid, paper_id, fname, fig["page_num"], fig["width"], fig["height"],
                 analysis["description"], json.dumps(analysis["tags"]),
                 analysis["figure_type"], caption,
                 analysis["quality_score"], analysis.get("layout_type", ""))
            )
            conn.commit()
            conn.close()
            result["accepted"] += 1
            logger.info("      ACCEPT (score=%.1f, type=%s, tags=%d)",
                        analysis["quality_score"], analysis["figure_type"], len(analysis["tags"]))
        else:
            # Delete rejected figure file
            fig_path.unlink(missing_ok=True)
            result["rejected"] += 1
            logger.info("      REJECT: %s", analysis["reason"][:60])

        time.sleep(PIPELINE_DELAY_BETWEEN_FIGURES)

    # If no figures were accepted, remove paper record
    if result["accepted"] == 0:
        conn = get_conn()
        conn.execute("DELETE FROM papers WHERE id=?", (paper_id,))
        conn.commit()
        conn.close()
        # Clean up empty directory
        paper_dir = FIGURE_DIR / paper_id
        if paper_dir.exists() and not any(paper_dir.iterdir()):
            paper_dir.rmdir()

    return result


# ═══════════════════════════════════════════════════════════════════
# MAIN: Batch processing
# ═══════════════════════════════════════════════════════════════════

def run_pipeline(venue_id: str, start: int = 1, end: int = 200):
    """Run the full pipeline on a range of papers from a venue.

    Steps:
      1. Download PDFs
      2. Extract figures (precise cropping via caption detection)
      3. LLM screen + analyze each figure
      4. Store accepted figures, delete rejected
      5. Cleanup orphans and duplicates
    """
    logger.info("=" * 60)
    logger.info("  AcademicFigureGallery Pipeline")
    logger.info("  Venue: %s  Range: %d–%d", venue_id, start, end)
    logger.info("=" * 60)

    # Step 1: Download
    pdfs = download_papers(venue_id, start, end)

    # Build global dedup set from existing figures
    conn = get_conn()
    dedup_hashes = set()
    for r in conn.execute("SELECT filename FROM figures").fetchall():
        fp = FIGURE_DIR / r["filename"]
        if fp.exists():
            dedup_hashes.add(hashlib.md5(fp.read_bytes()).hexdigest())
    conn.close()
    logger.info("Global dedup set: %d existing hashes", len(dedup_hashes))

    # Step 2-4: Process each paper
    totals = {"papers": 0, "extracted": 0, "accepted": 0, "rejected": 0, "errors": 0}

    for idx, pdf_path in enumerate(pdfs):
        logger.info("\n[%d/%d] %s", idx + 1, len(pdfs), pdf_path.stem)

        result = process_single_paper(pdf_path, dedup_hashes)
        totals["papers"] += 1
        totals["extracted"] += result["extracted"]
        totals["accepted"] += result["accepted"]
        totals["rejected"] += result["rejected"]
        totals["errors"] += result["errors"]

        if result["accepted"] > 0:
            logger.info("  → Saved %d/%d figures", result["accepted"], result["extracted"])

        # Progress report every 25 papers
        if (idx + 1) % 25 == 0:
            conn = get_conn()
            tp = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
            tf = conn.execute("SELECT COUNT(*) FROM figures").fetchone()[0]
            conn.close()
            logger.info("\n  ═══ Progress: %d papers, %d total figures in DB ═══\n", tp, tf)

        time.sleep(PIPELINE_DELAY_BETWEEN_PAPERS)

    # Step 5: Cleanup
    logger.info("\n" + "=" * 60)
    logger.info("  Post-processing cleanup")
    logger.info("=" * 60)
    fix_venue_labels()
    dedup_figures()
    cleanup_orphans()

    # Final report
    logger.info("\n" + "=" * 60)
    logger.info("  PIPELINE COMPLETE")
    logger.info("  Papers processed: %d", totals["papers"])
    logger.info("  Figures extracted: %d", totals["extracted"])
    logger.info("  Figures accepted:  %d", totals["accepted"])
    logger.info("  Figures rejected:  %d", totals["rejected"])
    logger.info("  Errors:            %d", totals["errors"])
    logger.info("=" * 60)

    print_status_report()


# ═══════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="AcademicFigureGallery — Unified Processing Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m pipeline.run --venue 2025.emnlp-main --range 1-200
  python -m pipeline.run --venue 2024.acl-long --range 1-100
  python -m pipeline.run --retry
  python -m pipeline.run --cleanup
  python -m pipeline.run --status
        """,
    )
    parser.add_argument("--venue", type=str, help="ACL Anthology venue ID (e.g. 2025.emnlp-main)")
    parser.add_argument("--range", type=str, default="1-50", help="Paper range: START-END (default: 1-50)")
    parser.add_argument("--retry", action="store_true", help="Retry all pending/error figures")
    parser.add_argument("--cleanup", action="store_true", help="Run cleanup (dedup + orphans)")
    parser.add_argument("--status", action="store_true", help="Print status report")

    args = parser.parse_args()

    if args.status:
        print_status_report()
        return

    if args.cleanup:
        logger.info("Running cleanup...")
        fix_venue_labels()
        dedup_figures()
        cleanup_orphans()
        cleanup_rejected()
        print_status_report()
        return

    if args.retry:
        from pipeline.maintenance import retry_failed
        retry_failed()
        cleanup_orphans()
        print_status_report()
        return

    if not args.venue:
        parser.print_help()
        print("\nError: --venue is required for processing")
        return

    # Parse range
    if "-" in args.range:
        start, end = args.range.split("-", 1)
        start, end = int(start), int(end)
    else:
        start, end = 1, int(args.range)

    run_pipeline(args.venue, start, end)


if __name__ == "__main__":
    main()
