"""Database maintenance utilities.

Consolidates cleanup, deduplication, retry, and status reporting logic
that was previously scattered across 6+ one-off scripts.
"""

import hashlib
import os
import time
from pathlib import Path
from typing import Optional

from config import FIGURE_DIR, PIPELINE_DELAY_BETWEEN_FIGURES
from database import get_conn
from log import get_logger

logger = get_logger("Maintenance")


# ── Deduplication ────────────────────────────────────────────────────

def dedup_figures() -> int:
    """Remove duplicate figures based on MD5 hash of image files.

    Keeps the first occurrence (by rowid), deletes duplicates.
    Returns number of duplicates removed.
    """
    conn = get_conn()
    rows = conn.execute("SELECT id, filename FROM figures ORDER BY rowid").fetchall()

    seen_hashes = {}
    to_delete = []

    for row in rows:
        fpath = FIGURE_DIR / row["filename"]
        if not fpath.exists():
            to_delete.append(row["id"])
            continue

        file_hash = hashlib.md5(fpath.read_bytes()).hexdigest()[:12]
        if file_hash in seen_hashes:
            to_delete.append(row["id"])
            # Delete the duplicate file
            fpath.unlink(missing_ok=True)
        else:
            seen_hashes[file_hash] = row["id"]

    if to_delete:
        conn.executemany("DELETE FROM figures WHERE id=?", [(fid,) for fid in to_delete])
        conn.commit()

    conn.close()
    logger.info("Dedup: removed %d duplicates (kept %d unique)", len(to_delete), len(seen_hashes))
    return len(to_delete)


# ── Orphan Cleanup ───────────────────────────────────────────────────

def cleanup_orphans() -> dict:
    """Remove orphaned records: papers without figures, figures without papers.

    Also removes figure files that have no DB entry, and DB entries whose
    files are missing.

    Returns dict with counts of removed items.
    """
    conn = get_conn()
    stats = {"orphan_papers": 0, "orphan_figures": 0, "missing_files": 0}

    # 1. Remove figures whose files don't exist
    rows = conn.execute("SELECT id, filename FROM figures").fetchall()
    missing = []
    for row in rows:
        if not (FIGURE_DIR / row["filename"]).exists():
            missing.append(row["id"])
    if missing:
        conn.executemany("DELETE FROM figures WHERE id=?", [(fid,) for fid in missing])
        stats["missing_files"] = len(missing)

    # 2. Remove papers with no figures
    orphan_papers = conn.execute(
        "DELETE FROM papers WHERE id NOT IN (SELECT DISTINCT paper_id FROM figures)"
    ).rowcount
    stats["orphan_papers"] = orphan_papers

    # 3. Remove figures referencing non-existent papers
    orphan_figs = conn.execute(
        "DELETE FROM figures WHERE paper_id NOT IN (SELECT id FROM papers)"
    ).rowcount
    stats["orphan_figures"] = orphan_figs

    conn.commit()
    conn.close()

    logger.info("Cleanup: %d orphan papers, %d orphan figures, %d missing files",
                stats["orphan_papers"], stats["orphan_figures"], stats["missing_files"])
    return stats


def cleanup_rejected() -> int:
    """Delete figures marked as 'pending' or 'error' and their image files.

    Returns count of deleted figures.
    """
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, filename FROM figures WHERE figure_type IN ('pending', 'error')"
    ).fetchall()

    for row in rows:
        fpath = FIGURE_DIR / row["filename"]
        fpath.unlink(missing_ok=True)

    conn.execute("DELETE FROM figures WHERE figure_type IN ('pending', 'error')")
    conn.commit()
    conn.close()

    logger.info("Cleaned %d pending/error figures", len(rows))
    return len(rows)


# ── Retry Failed ─────────────────────────────────────────────────────

def retry_failed(max_retries: int = 2) -> dict:
    """Re-analyze figures with 'error' or 'pending' status.

    Returns dict with accept/reject/error counts.
    """
    from pipeline.analyzer import screen_and_analyze

    conn = get_conn()
    figures = conn.execute(
        "SELECT id, filename, caption FROM figures WHERE figure_type IN ('pending', 'error')"
    ).fetchall()
    conn.close()

    if not figures:
        logger.info("No pending/error figures to retry")
        return {"total": 0, "accepted": 0, "rejected": 0, "errors": 0}

    logger.info("Retrying %d pending/error figures", len(figures))
    stats = {"total": len(figures), "accepted": 0, "rejected": 0, "errors": 0}

    for i, row in enumerate(figures):
        fid, filename, caption = row["id"], row["filename"], row["caption"] or ""
        logger.info("[%d/%d] %s", i + 1, len(figures), filename)

        result = screen_and_analyze(filename, caption)

        conn = get_conn()
        if result["accepted"]:
            conn.execute(
                """UPDATE figures SET description=?, tags=?, figure_type=?, quality_score=?
                   WHERE id=?""",
                (result["description"], str(result["tags"]), result["figure_type"],
                 result["quality_score"], fid)
            )
            stats["accepted"] += 1
        elif "Error" in result["reason"]:
            conn.execute("UPDATE figures SET figure_type='error' WHERE id=?", (fid,))
            stats["errors"] += 1
        else:
            # Rejected — delete
            conn.execute("DELETE FROM figures WHERE id=?", (fid,))
            fpath = FIGURE_DIR / filename
            fpath.unlink(missing_ok=True)
            stats["rejected"] += 1
        conn.commit()
        conn.close()

        time.sleep(PIPELINE_DELAY_BETWEEN_FIGURES)

    logger.info("Retry complete: %s", stats)
    return stats


# ── Venue Label Fix ──────────────────────────────────────────────────

def fix_venue_labels() -> int:
    """Auto-detect and fix venue labels based on paper IDs or PDF filenames.

    Detects ACL, EMNLP, NAACL, EACL patterns from ACL Anthology IDs.
    Returns number of papers updated.
    """
    conn = get_conn()
    papers = conn.execute("SELECT id, url, pdf_url FROM papers").fetchall()

    updated = 0
    for p in papers:
        url = (p["url"] or "") + (p["pdf_url"] or "")
        venue, year = None, None

        # Try to detect from URL: "2024.acl-long", "2025.emnlp-main", etc.
        import re
        m = re.search(r"(\d{4})\.(acl|emnlp|naacl|eacl)[-.]", url, re.IGNORECASE)
        if m:
            year = int(m.group(1))
            venue = m.group(2).upper()

        if venue:
            conn.execute(
                "UPDATE papers SET venue=?, year=? WHERE id=?",
                (venue, year, p["id"])
            )
            updated += 1

    conn.commit()
    conn.close()
    logger.info("Fixed venue labels for %d papers", updated)
    return updated


# ── Status Report ────────────────────────────────────────────────────

def get_status_report() -> dict:
    """Generate comprehensive database status report."""
    conn = get_conn()

    report = {}

    # Overall counts
    report["total_papers"] = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    report["total_figures"] = conn.execute("SELECT COUNT(*) FROM figures").fetchone()[0]

    # Figures by status
    report["curated_figures"] = conn.execute(
        "SELECT COUNT(*) FROM figures WHERE figure_type NOT IN ('pending', 'error')"
    ).fetchone()[0]
    report["pending_figures"] = conn.execute(
        "SELECT COUNT(*) FROM figures WHERE figure_type='pending'"
    ).fetchone()[0]
    report["error_figures"] = conn.execute(
        "SELECT COUNT(*) FROM figures WHERE figure_type='error'"
    ).fetchone()[0]

    # By venue
    venues = conn.execute(
        "SELECT venue, COUNT(*) as cnt FROM papers GROUP BY venue ORDER BY cnt DESC"
    ).fetchall()
    report["by_venue"] = {r["venue"]: r["cnt"] for r in venues}

    # By figure type
    types = conn.execute(
        "SELECT figure_type, COUNT(*) as cnt FROM figures GROUP BY figure_type ORDER BY cnt DESC"
    ).fetchall()
    report["by_figure_type"] = {r["figure_type"]: r["cnt"] for r in types}

    # Quality score distribution
    avg_score = conn.execute(
        "SELECT AVG(quality_score) FROM figures WHERE quality_score > 0"
    ).fetchone()[0]
    report["avg_quality_score"] = round(avg_score, 2) if avg_score else 0

    # Top tags
    tag_rows = conn.execute("SELECT tags FROM figures WHERE tags != '[]' AND tags IS NOT NULL").fetchall()
    import json
    tag_counts = {}
    for r in tag_rows:
        try:
            for t in json.loads(r["tags"]):
                tag_counts[t] = tag_counts.get(t, 0) + 1
        except Exception:
            pass
    report["top_tags"] = dict(sorted(tag_counts.items(), key=lambda x: -x[1])[:15])

    conn.close()
    return report


def print_status_report():
    """Print a formatted status report to the console."""
    r = get_status_report()

    print("\n" + "=" * 60)
    print("  AcademicFigureGallery — Status Report")
    print("=" * 60)
    print(f"  Papers:           {r['total_papers']}")
    print(f"  Figures (total):  {r['total_figures']}")
    print(f"  Figures (curated):{r['curated_figures']}")
    print(f"  Figures (pending):{r['pending_figures']}")
    print(f"  Figures (error):  {r['error_figures']}")
    print(f"  Avg quality:      {r['avg_quality_score']}")

    if r["by_venue"]:
        print("\n  Papers by venue:")
        for v, c in r["by_venue"].items():
            print(f"    {v or '(unknown)':12s} {c}")

    if r["by_figure_type"]:
        print("\n  Figures by type:")
        for t, c in r["by_figure_type"].items():
            print(f"    {t or '(unknown)':24s} {c}")

    if r["top_tags"]:
        print("\n  Top tags:")
        for t, c in list(r["top_tags"].items())[:10]:
            print(f"    {t:30s} {c}")

    print("=" * 60 + "\n")
