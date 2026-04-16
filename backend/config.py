"""Global configuration for AcademicFigureGallery.

All settings are centralized here. API keys are loaded from .env file.
"""

import os
from pathlib import Path
from dataclasses import dataclass, field

# Load .env from project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_env_file = _PROJECT_ROOT / ".env"
if _env_file.exists():
    from dotenv import load_dotenv
    load_dotenv(_env_file)


# ── Paths ───────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
PDF_DIR = DATA_DIR / "pdfs"
FIGURE_DIR = DATA_DIR / "figures"
DB_PATH = DATA_DIR / "db" / "gallery.db"

for d in [PDF_DIR, FIGURE_DIR, DB_PATH.parent]:
    d.mkdir(parents=True, exist_ok=True)


# ── LLM ─────────────────────────────────────────────────────────────
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://hunyuanapi.woa.com/openapi/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "HY-Vision-2.0-instruct")

# LLM call parameters
LLM_MAX_TOKENS_SCREEN = 300       # for screening calls
LLM_MAX_TOKENS_ANALYZE = 800     # for analysis calls
LLM_MAX_TOKENS_COMBINED = 1000   # for combined screen+analyze
LLM_TEMPERATURE = 0.1
LLM_TIMEOUT = 60                  # seconds
LLM_MAX_RETRIES = 2              # retry count on failure
LLM_RETRY_DELAY = 2.0            # base delay between retries (exponential)


# ── Figure Extraction ───────────────────────────────────────────────
MIN_FIGURE_WIDTH = 200    # px — skip tiny logos / icons
MIN_FIGURE_HEIGHT = 150
MIN_FIGURE_AREA = 50_000  # w*h threshold
RENDER_SCALE = 3          # 3x rendering for high quality
CROP_PADDING = 10         # px padding around cropped figures
BLANK_THRESHOLD = 25      # min brightness range to not be "blank"
MIN_FILE_SIZE = 10_000    # bytes — skip < 10KB images


# ── Image Preprocessing (for LLM) ──────────────────────────────────
IMAGE_MAX_WIDTH = 1200    # resize before sending to LLM
IMAGE_JPEG_QUALITY = 80   # JPEG compression quality


# ── ACL Anthology ───────────────────────────────────────────────────
ACL_ANTHOLOGY_BASE = "https://aclanthology.org"
SCRAPE_DELAY = 0.5        # seconds between requests (politeness)
DOWNLOAD_TIMEOUT = 60     # seconds for PDF download


# ── Pipeline ────────────────────────────────────────────────────────
PIPELINE_DELAY_BETWEEN_FIGURES = 0.3   # seconds between LLM calls
PIPELINE_DELAY_BETWEEN_PAPERS = 1.0    # seconds between papers
