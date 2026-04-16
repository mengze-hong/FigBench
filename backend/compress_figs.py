"""Compress figures: convert PNG → JPEG (85% quality), resize if >1600px.
Updates DB filenames accordingly."""
import sys, os, io
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pathlib import Path
from PIL import Image
from database import get_conn, init_db
from config import FIGURE_DIR

init_db()

MAX_DIM = 1600
JPEG_QUALITY = 85

all_pngs = list(FIGURE_DIR.rglob("*.png"))
print(f"Found {len(all_pngs)} PNG files\n")

total_before = 0
total_after = 0

for i, fp in enumerate(all_pngs):
    before = fp.stat().st_size
    total_before += before

    try:
        img = Image.open(fp)
        if img.mode in ('RGBA', 'P', 'LA'):
            bg = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'RGBA':
                bg.paste(img, mask=img.split()[3])
            else:
                bg.paste(img.convert('RGBA'), mask=img.convert('RGBA').split()[3])
            img = bg
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        w, h = img.size
        if w > MAX_DIM or h > MAX_DIM:
            ratio = min(MAX_DIM / w, MAX_DIM / h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

        # Save as JPEG
        jpg_path = fp.with_suffix('.jpg')
        img.save(jpg_path, format="JPEG", quality=JPEG_QUALITY, optimize=True)

        after = jpg_path.stat().st_size
        total_after += after

        # Remove old PNG
        fp.unlink()

        # Update DB: old filename → new filename
        old_rel = str(fp.relative_to(FIGURE_DIR)).replace('\\', '/')
        new_rel = str(jpg_path.relative_to(FIGURE_DIR)).replace('\\', '/')
        conn = get_conn()
        conn.execute("UPDATE figures SET filename=? WHERE filename=?", (new_rel, old_rel))
        conn.commit()
        conn.close()

    except Exception as e:
        total_after += before
        print(f"  Error {fp.name}: {e}")

    if (i + 1) % 100 == 0:
        pct = (1 - total_after / total_before) * 100 if total_before > 0 else 0
        print(f"[{i+1}/{len(all_pngs)}] {total_before//1024//1024}MB → {total_after//1024//1024}MB ({pct:.0f}% saved)")

pct = (1 - total_after / total_before) * 100 if total_before > 0 else 0
print(f"\n{'='*60}")
print(f"  Before: {total_before / 1024 / 1024:.1f} MB")
print(f"  After:  {total_after / 1024 / 1024:.1f} MB")
print(f"  Saved:  {(total_before - total_after) / 1024 / 1024:.1f} MB ({pct:.0f}%)")
print(f"{'='*60}")
