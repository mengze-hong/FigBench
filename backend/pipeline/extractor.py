"""Extract figures from PDF with PRECISE cropping.

Strategy:
1. Find figure captions ("Figure N" / "Fig. N") on each page with Y positions
2. For each caption, locate the figure region ABOVE it:
   a. Embedded IMAGE objects → use their exact bounds
   b. Vector graphics → cluster PATH objects between previous text block and caption
3. Render page at high DPI, crop the exact figure region
4. Validate: skip too-small, near-blank, or badly-proportioned crops
"""

import pypdfium2 as pdfium
import pypdfium2.raw as raw
import hashlib
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from PIL import Image
import io

from config import (
    FIGURE_DIR, MIN_FIGURE_WIDTH, MIN_FIGURE_HEIGHT, MIN_FIGURE_AREA,
    RENDER_SCALE, BLANK_THRESHOLD, CROP_PADDING,
)


def extract_figures(pdf_path: str, paper_id: str) -> List[Dict]:
    """Extract precisely-cropped figures from a PDF.

    Returns list of dicts: {filename, page_num, width, height, caption}
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    doc = pdfium.PdfDocument(str(pdf_path))
    figures = []
    seen_hashes = set()
    seen_fig_nums = set()  # avoid duplicate fig numbers across pages

    paper_fig_dir = FIGURE_DIR / paper_id
    paper_fig_dir.mkdir(parents=True, exist_ok=True)

    n_pages = min(len(doc), 15)  # First 15 pages (figures rarely beyond that)

    for page_idx in range(n_pages):
        page = doc[page_idx]
        page_w, page_h = page.get_size()

        # Step 1: Find figure captions
        captions = _find_figure_captions(page, page_h)
        if not captions:
            continue

        # Step 2: Find embedded image objects
        image_objects = _find_image_objects(page, page_h)

        # Step 3: Render full page at high DPI
        bitmap = page.render(scale=RENDER_SCALE)
        page_img = bitmap.to_pil()
        render_w, render_h = page_img.size

        # Step 4: For each caption, crop the figure
        for cap_info in captions:
            fig_num = cap_info["fig_num"]

            # Skip duplicate figure numbers (same fig referenced on multiple pages)
            if fig_num in seen_fig_nums:
                continue

            caption_text = cap_info["text"]
            caption_y = cap_info["y_top"]

            # Try strategy 1: Embedded image object above caption
            crop_box = None
            if image_objects:
                crop_box = _match_image_to_caption(image_objects, caption_y, page_w, page_h)

            # Try strategy 2: Estimate from vector paths
            if crop_box is None:
                crop_box = _estimate_figure_region(page, caption_y, page_w, page_h)

            if crop_box is None:
                continue

            # Convert PDF points to pixels and crop
            fig_img = _crop_figure(page_img, crop_box, render_w, render_h)
            if fig_img is None:
                continue

            w, h = fig_img.size

            # Validate crop quality
            if not _validate_crop(fig_img, w, h):
                continue

            # Deduplicate by content hash
            img_bytes = io.BytesIO()
            fig_img.save(img_bytes, format="PNG", optimize=True)
            img_data = img_bytes.getvalue()
            img_hash = hashlib.md5(img_data).hexdigest()[:12]
            if img_hash in seen_hashes:
                continue
            seen_hashes.add(img_hash)
            seen_fig_nums.add(fig_num)

            # Save
            filename = f"{paper_id}_fig{fig_num}.png"
            out_path = paper_fig_dir / filename
            with open(out_path, "wb") as f:
                f.write(img_data)

            figures.append({
                "filename": f"{paper_id}/{filename}",
                "page_num": page_idx + 1,
                "width": w,
                "height": h,
                "caption": caption_text,
            })

    doc.close()
    if figures:
        print(f"[Extractor] Extracted {len(figures)} figures from {pdf_path.name}")
    return figures


# ── Caption Detection ────────────────────────────────────────────────

def _find_figure_captions(page, page_h: float) -> List[Dict]:
    """Find figure captions with Y positions on this page."""
    captions = []
    try:
        tp = page.get_textpage()
        text = tp.get_text_range()

        # Normalize broken text
        normalized = text.replace('\u00ad', '').replace('\ufffe', '').replace('\uffbe', '')
        normalized = re.sub(r'(Fig)\s*\n\s*(ure)', r'\1\2', normalized, flags=re.IGNORECASE)

        lines = normalized.split('\n')

        for i, line in enumerate(lines):
            stripped = line.strip()
            # Match: "Figure 1:", "Fig. 2:", "Figure 1.", "Figure 1 -"
            m = re.match(r'(?:Figure|Fig\.?)\s*(\d+)\s*[:.:\-–—]?', stripped, re.IGNORECASE)
            if not m:
                continue

            fig_num = int(m.group(1))

            # Build full caption (may span multiple lines)
            caption_lines = [stripped]
            for j in range(1, 5):
                if i + j < len(lines):
                    next_line = lines[i + j].strip()
                    if next_line and not re.match(r'(?:Figure|Fig\.?|Table)\s*\d+', next_line, re.IGNORECASE):
                        caption_lines.append(next_line)
                    else:
                        break
            caption_text = " ".join(caption_lines)

            # Find Y position
            y_pos = _find_text_y_position(tp, stripped[:40], page_h)

            captions.append({
                "text": caption_text[:500],
                "y_top": y_pos,
                "fig_num": fig_num,
            })
    except Exception:
        pass

    return captions


def _find_text_y_position(textpage, search_text: str, page_h: float) -> float:
    """Find Y position (from page top, in PDF points) of a text string."""
    try:
        searcher = textpage.search(search_text, match_case=False)
        if searcher:
            idx, count = searcher.get_next()
            if idx is not None and count > 0:
                rects = textpage.get_rectboxes(index=idx, count=min(count, 10))
                for rect in rects:
                    left, bottom, right, top = rect
                    return page_h - top
    except Exception:
        pass
    return page_h * 0.6  # Fallback


# ── Image Object Detection ──────────────────────────────────────────

def _find_image_objects(page, page_h: float) -> List[Dict]:
    """Find all embedded IMAGE objects with bounds (top-down coords)."""
    images = []
    try:
        for obj in page.get_objects():
            if obj.type == raw.FPDF_PAGEOBJ_IMAGE:
                left, bottom, right, top = obj.get_bounds()
                w = right - left
                h = top - bottom
                if w > 30 and h > 20:  # skip tiny decorations
                    images.append({
                        "left": left,
                        "top": page_h - top,
                        "right": right,
                        "bottom": page_h - bottom,
                        "width": w,
                        "height": h,
                    })
    except Exception:
        pass
    return images


# ── Figure Region Matching ───────────────────────────────────────────

def _match_image_to_caption(image_objects: List[Dict], caption_y: float,
                            page_w: float, page_h: float) -> Optional[Tuple]:
    """Find the image object directly above a caption.

    Returns (left, top, right, bottom) in PDF points (top-down), or None.
    """
    best = None
    best_dist = float('inf')

    for img in image_objects:
        # Image bottom should be at or above the caption
        if img["bottom"] <= caption_y + 30:
            dist = abs(img["bottom"] - caption_y)
            area = img["width"] * img["height"]
            if dist < best_dist and area > 2000:
                best_dist = dist
                best = img

    if best and best_dist < page_h * 0.5:
        return (best["left"], best["top"], best["right"], best["bottom"])
    return None


def _estimate_figure_region(page, caption_y: float,
                            page_w: float, page_h: float) -> Optional[Tuple]:
    """Estimate figure region for vector-drawn figures.

    Clusters PATH/FORM objects between previous text and caption.
    Returns (left, top, right, bottom) in PDF points (top-down), or None.
    """
    try:
        path_bounds = []
        for obj in page.get_objects():
            if obj.type in (raw.FPDF_PAGEOBJ_PATH, raw.FPDF_PAGEOBJ_SHADING,
                            raw.FPDF_PAGEOBJ_IMAGE, raw.FPDF_PAGEOBJ_FORM):
                left, bottom, right, top = obj.get_bounds()
                obj_top = page_h - top
                obj_bottom = page_h - bottom
                w = right - left
                h = obj_bottom - obj_top

                # Must be above caption, not tiny, within page
                if (obj_bottom <= caption_y + 10 and w > 8 and h > 8
                        and left >= -5 and right <= page_w + 5):
                    path_bounds.append({
                        "left": max(0, left),
                        "top": obj_top,
                        "right": min(page_w, right),
                        "bottom": obj_bottom,
                    })

        if len(path_bounds) < 3:
            return None

        # Only consider objects in the upper portion relative to caption
        # (figure should be between ~40% above caption and caption itself)
        max_look_up = page_h * 0.55
        nearby = [p for p in path_bounds
                  if caption_y - p["top"] < max_look_up and caption_y - p["top"] > -20]

        if len(nearby) < 3:
            return None

        # Bounding box of clustered objects
        left = min(p["left"] for p in nearby)
        top = min(p["top"] for p in nearby)
        right = max(p["right"] for p in nearby)
        bottom = max(p["bottom"] for p in nearby)

        width = right - left
        height = bottom - top

        # Sanity: figure should be reasonable size
        if width < 80 or height < 60:
            return None
        if width > page_w * 0.95 and height > page_h * 0.85:
            # Probably captured entire page content, not just figure
            return None

        # Clamp to page margins
        left = max(left, 20)
        right = min(right, page_w - 20)

        return (left, top, right, bottom)

    except Exception:
        return None


# ── Cropping & Validation ────────────────────────────────────────────

def _crop_figure(page_img: Image.Image, crop_box: Tuple,
                 render_w: int, render_h: int) -> Optional[Image.Image]:
    """Crop a figure from the rendered page image."""
    left, top, right, bottom = crop_box

    pad = CROP_PADDING * RENDER_SCALE
    px_left = max(0, int(left * RENDER_SCALE) - pad)
    px_top = max(0, int(top * RENDER_SCALE) - pad)
    px_right = min(render_w, int(right * RENDER_SCALE) + pad)
    px_bottom = min(render_h, int(bottom * RENDER_SCALE) + pad)

    if px_right <= px_left + 50 or px_bottom <= px_top + 30:
        return None

    return page_img.crop((px_left, px_top, px_right, px_bottom))


def _validate_crop(fig_img: Image.Image, w: int, h: int) -> bool:
    """Check if the crop is a valid figure (not blank, not too small, good ratio)."""
    # Size checks
    if w < MIN_FIGURE_WIDTH or h < MIN_FIGURE_HEIGHT:
        return False
    if w * h < MIN_FIGURE_AREA:
        return False

    # Aspect ratio: reject extremely narrow/tall crops (likely bad crop)
    ratio = w / h if h > 0 else 0
    if ratio > 8.0 or ratio < 0.1:
        return False

    # Blank check
    extrema = fig_img.convert("L").getextrema()
    if extrema[1] - extrema[0] < BLANK_THRESHOLD:
        return False

    return True
