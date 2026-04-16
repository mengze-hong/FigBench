"""FastAPI backend for AcademicFigureGallery."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, Query, HTTPException, BackgroundTasks, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pathlib import Path
from typing import Optional, List

import database as db
from config import FIGURE_DIR, DATA_DIR

app = FastAPI(title="AcademicFigureGallery API", version="1.0.0")

# CORS for frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve figure images
app.mount("/figures", StaticFiles(directory=str(FIGURE_DIR)), name="figures")


# ── Search & Browse ────────────────────────────────────────────────────

@app.get("/api/figures")
def list_figures(
    q: str = "",
    tags: Optional[str] = None,
    figure_type: str = "",
    layout_type: str = "",
    venue: str = "",
    year: int = 0,
    sort: str = "created_at",
    order: str = "DESC",
    page: int = 1,
    per_page: int = 24,
):
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    result = db.search_figures(
        query=q, tags=tag_list, figure_type=figure_type,
        layout_type=layout_type,
        venue=venue, year=year,
        sort=sort, order=order, page=page, per_page=per_page,
    )
    # Add image URL to each item
    for item in result["items"]:
        item["image_url"] = f"/figures/{item['filename']}"
        if item.get("tags") and isinstance(item["tags"], str):
            import json
            try:
                item["tags"] = json.loads(item["tags"])
            except Exception:
                item["tags"] = []
    return result


@app.get("/api/figures/{figure_id}")
def get_figure(figure_id: str):
    conn = db.get_conn()
    row = conn.execute(
        """SELECT f.*, p.title as paper_title, p.authors, p.venue, p.year, p.url as paper_url
           FROM figures f JOIN papers p ON f.paper_id=p.id WHERE f.id=?""",
        (figure_id,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Figure not found")
    item = dict(row)
    item["image_url"] = f"/figures/{item['filename']}"
    import json
    if isinstance(item.get("tags"), str):
        try:
            item["tags"] = json.loads(item["tags"])
        except Exception:
            item["tags"] = []
    return item


# ── Tags & Types ───────────────────────────────────────────────────────

@app.get("/api/tags")
def list_tags():
    return {"tags": db.get_all_tags()}


@app.get("/api/figure-types")
def list_figure_types():
    return {"types": db.get_all_figure_types()}


@app.get("/api/stats")
def get_stats():
    return db.get_stats()


# ── Pipeline Control ───────────────────────────────────────────────────

@app.delete("/api/figures/{figure_id}")
def flag_bad_figure(figure_id: str):
    """Flag a figure as bad — move to bad_figures/ and remove from DB."""
    import shutil
    conn = db.get_conn()
    row = conn.execute("SELECT filename, paper_id FROM figures WHERE id=?", (figure_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Figure not found")

    filename = row["filename"]
    paper_id = row["paper_id"]

    # Move file to bad_figures/
    src = FIGURE_DIR / filename
    bad_dir = DATA_DIR / "bad_figures"
    bad_dir.mkdir(parents=True, exist_ok=True)
    dst = bad_dir / filename.replace("/", "_")
    if src.exists():
        shutil.move(str(src), str(dst))

    # Delete from DB
    conn.execute("DELETE FROM figures WHERE id=?", (figure_id,))
    conn.commit()

    # If paper has no more figures, delete paper too
    remaining = conn.execute("SELECT COUNT(*) FROM figures WHERE paper_id=?", (paper_id,)).fetchone()[0]
    if remaining == 0:
        conn.execute("DELETE FROM papers WHERE id=?", (paper_id,))
        conn.commit()
    conn.close()

    return {"status": "deleted", "id": figure_id, "moved_to": str(dst)}


@app.post("/api/ingest")
def trigger_ingest(
    background_tasks: BackgroundTasks,
    venue: str = "2025.emnlp-main",
    start: int = 1,
    end: int = 50,
):
    """Trigger background ingestion of papers from ACL Anthology."""
    from pipeline.run import run_pipeline

    def _run():
        run_pipeline(venue, start, end)

    background_tasks.add_task(_run)
    return {"status": "started", "venue": venue, "range": f"{start}-{end}"}


# ── Edit figure metadata ──────────────────────────────────────────────

from pydantic import BaseModel

class FigureUpdate(BaseModel):
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    figure_type: Optional[str] = None
    layout_type: Optional[str] = None

@app.patch("/api/figures/{figure_id}")
def update_figure(figure_id: str, body: FigureUpdate):
    """Update figure metadata (description, tags, figure_type, layout_type)."""
    import json as _json
    conn = db.get_conn()
    row = conn.execute("SELECT id FROM figures WHERE id=?", (figure_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Figure not found")

    updates = []
    params = []
    if body.description is not None:
        updates.append("description=?")
        params.append(body.description)
    if body.tags is not None:
        updates.append("tags=?")
        params.append(_json.dumps(body.tags))
    if body.figure_type is not None:
        updates.append("figure_type=?")
        params.append(body.figure_type)
    if body.layout_type is not None:
        updates.append("layout_type=?")
        params.append(body.layout_type)

    if not updates:
        conn.close()
        return {"status": "no changes"}

    params.append(figure_id)
    conn.execute(f"UPDATE figures SET {', '.join(updates)} WHERE id=?", params)
    conn.commit()
    conn.close()
    return {"status": "updated", "id": figure_id}


# ── Crop figure image ─────────────────────────────────────────────────

class CropRequest(BaseModel):
    x: int
    y: int
    width: int
    height: int

@app.post("/api/figures/{figure_id}/crop")
def crop_figure(figure_id: str, body: CropRequest):
    """Crop a figure image to the specified region. Overwrites the original."""
    from PIL import Image
    import shutil

    conn = db.get_conn()
    row = conn.execute("SELECT filename FROM figures WHERE id=?", (figure_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Figure not found")

    fig_path = FIGURE_DIR / row["filename"]
    if not fig_path.exists():
        raise HTTPException(404, "Image file not found")

    # Backup original before cropping
    backup_dir = DATA_DIR / "crop_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_name = row["filename"].replace("/", "_")
    backup_path = backup_dir / backup_name
    if not backup_path.exists():
        shutil.copy2(str(fig_path), str(backup_path))

    # Crop
    img = Image.open(fig_path)
    crop_box = (body.x, body.y, body.x + body.width, body.y + body.height)

    # Validate
    if (crop_box[0] < 0 or crop_box[1] < 0 or
        crop_box[2] > img.width or crop_box[3] > img.height or
        body.width < 50 or body.height < 50):
        raise HTTPException(400, "Invalid crop dimensions")

    cropped = img.crop(crop_box)
    cropped.save(fig_path, "PNG", optimize=True)

    # Update dimensions in DB
    conn = db.get_conn()
    conn.execute("UPDATE figures SET width=?, height=? WHERE id=?",
                 (cropped.width, cropped.height, figure_id))
    conn.commit()
    conn.close()

    return {
        "status": "cropped", "id": figure_id,
        "new_width": cropped.width, "new_height": cropped.height,
        "backup": str(backup_path),
    }


@app.post("/api/figures/{figure_id}/replace")
async def replace_figure(figure_id: str, request: Request):
    """Replace a figure image with a new one (base64 PNG/JPEG from clipboard paste)."""
    from PIL import Image
    import base64
    import shutil

    body = await request.json()
    image_data = body.get("image_data", "")

    if not image_data:
        raise HTTPException(400, "No image data provided")

    # Strip data URL prefix if present
    if "," in image_data:
        image_data = image_data.split(",", 1)[1]

    conn = db.get_conn()
    row = conn.execute("SELECT filename FROM figures WHERE id=?", (figure_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Figure not found")

    fig_path = FIGURE_DIR / row["filename"]

    # Backup original
    backup_dir = DATA_DIR / "replace_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_name = row["filename"].replace("/", "_")
    if fig_path.exists():
        shutil.copy2(str(fig_path), str(backup_dir / backup_name))

    # Decode and save new image
    import io
    img_bytes = base64.b64decode(image_data)
    img = Image.open(io.BytesIO(img_bytes))
    if img.mode == "RGBA":
        img = img.convert("RGB")
    img.save(fig_path, "PNG", optimize=True)

    # Update dimensions
    conn = db.get_conn()
    conn.execute("UPDATE figures SET width=?, height=? WHERE id=?",
                 (img.width, img.height, figure_id))
    conn.commit()
    conn.close()

    return {
        "status": "replaced", "id": figure_id,
        "new_width": img.width, "new_height": img.height,
    }


# ── Frontend serving ───────────────────────────────────────────────────

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
FRONTEND_DIST = FRONTEND_DIR / "dist"

# Prefer built dist, fall back to raw dev files
_frontend_root = FRONTEND_DIST if FRONTEND_DIST.exists() else FRONTEND_DIR

if _frontend_root.exists():
    # Serve CSS/JS/assets as static
    for static_name in ("assets",):
        static_dir = _frontend_root / static_name
        if static_dir.exists():
            app.mount(f"/{static_name}", StaticFiles(directory=str(static_dir)), name=f"frontend-{static_name}")

    @app.get("/style.css")
    async def serve_css():
        return FileResponse(str(_frontend_root / "style.css"), media_type="text/css")

    @app.get("/app.js")
    async def serve_js():
        return FileResponse(str(_frontend_root / "app.js"), media_type="application/javascript")

    @app.get("/")
    async def serve_index():
        return FileResponse(str(_frontend_root / "index.html"))

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        # Don't intercept /api or /figures routes (already handled above)
        file_path = _frontend_root / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(_frontend_root / "index.html"))
