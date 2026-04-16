"""LLM-based figure screening and rich tagging for retrieval.

Unified module:
- Image preprocessing (resize, compress, base64 encode)
- LLM vision calls with retry logic (direct HTTP, compatible with any OpenAI-style API)
- Robust JSON parsing
- Combined screen + tag + describe in single call
- Rich hierarchical tagging for retrieval and similarity comparison
"""

import base64
import io
import json
import time
import requests as http_requests
from pathlib import Path
from typing import Optional

from PIL import Image

from config import (
    LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, FIGURE_DIR,
    LLM_MAX_TOKENS_COMBINED, LLM_TEMPERATURE, LLM_TIMEOUT,
    LLM_MAX_RETRIES, LLM_RETRY_DELAY,
    IMAGE_MAX_WIDTH, IMAGE_JPEG_QUALITY, MIN_FILE_SIZE,
)
from log import get_logger

logger = get_logger("Analyzer")

# ── LLM Call with Retry ──────────────────────────────────────────────

def _call_llm_vision(system_prompt: str, image_b64: str,
                     user_text: str = "Analyze this academic figure:",
                     max_tokens: int = LLM_MAX_TOKENS_COMBINED) -> dict:
    """Call LLM vision API via direct HTTP and return parsed JSON response.
    
    Compatible with OpenAI-style APIs including Hunyuan.
    """
    url = f"{LLM_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {
                    "url": f"data:image/jpeg;base64,{image_b64}",
                }},
            ]},
        ],
        "max_tokens": max_tokens,
        "temperature": LLM_TEMPERATURE,
    }

    last_error = None
    for attempt in range(1 + LLM_MAX_RETRIES):
        try:
            resp = http_requests.post(url, headers=headers, json=payload, timeout=LLM_TIMEOUT)
            if resp.status_code != 200:
                raise ValueError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
            text = data["choices"][0]["message"]["content"].strip()
            result = parse_json_response(text)
            if result:
                return result
            raise ValueError(f"Empty JSON from response: {text[:100]}")
        except Exception as e:
            last_error = e
            if attempt < LLM_MAX_RETRIES:
                delay = LLM_RETRY_DELAY * (2 ** attempt)
                logger.warning("LLM call failed (attempt %d/%d): %s — retrying in %.1fs",
                               attempt + 1, 1 + LLM_MAX_RETRIES, e, delay)
                time.sleep(delay)

    logger.error("LLM call failed after %d attempts: %s", 1 + LLM_MAX_RETRIES, last_error)
    return {}


# ── Prompt ───────────────────────────────────────────────────────────

COMBINED_PROMPT = """You are a strict curator for a gallery of beautiful, hand-designed academic figures.

## Task (answer ALL dimensions in ONE response)

### Dimension 1: Completeness
Is the figure COMPLETE? Or is it badly cropped / cut off / corrupted?
- "complete" — all parts of the figure are visible, nothing is cut off
- "incomplete" — diagram/text/components are obviously cut off at edges, corrupted, or mostly blank

### Dimension 2: Accept/Reject
Is this a hand-designed illustration worth showcasing?

ACCEPT (hand-crafted):
- Framework / system overview diagrams
- Model architecture diagrams with custom visual components
- Dataset overview illustrations
- Conceptual illustrations explaining a method
- Pipeline / workflow diagrams with custom graphics, icons, arrows
- Taxonomy / categorization visualizations
- Infographic-style figures, multi-component system diagrams
- Comparison illustrations, annotation examples, task illustrations

REJECT (auto-generated or low-effort):
- Bar / line / pie / scatter / box charts (matplotlib, seaborn, ggplot)
- Tables, heatmaps, confusion matrices, training curves, loss plots
- Plain text, formulas, code screenshots
- Simple flowcharts with just plain boxes (no design effort)
- Benchmark comparison bar charts, radar charts, standard statistical plots
- Corrupted, blank, mostly-text images

### Dimension 3: Layout Classification
- "standalone" — figure occupies full image width, no body text paragraphs alongside
- "in-text" — figure shares space with paragraph text (e.g., one column figure + one column text)
  Note: caption text below the figure is fine — that's still "standalone"

### Dimension 4: Rich Tagging
Assign tags from MULTIPLE dimensions:

**Structure**: multi-panel, single-panel, grid-layout, side-by-side, layered, circular-layout, hierarchical, radial-design, left-to-right-flow, top-to-bottom-flow, nested

**Category**: framework-overview, system-architecture, model-architecture, dataset-overview, methodology-diagram, pipeline-illustration, conceptual-diagram, taxonomy-visualization, comparison-illustration, workflow-diagram, evaluation-framework, task-illustration, annotation-example, input-output-example, multi-stage-process, training-paradigm, data-flow-diagram, component-diagram, interaction-diagram

**Visual**: custom-icons, gradient-design, color-coded, hand-drawn-style, 3d-elements, rich-typography, visual-metaphor, illustration-art, geometric-shapes, shadow-effects, rounded-components, connector-arrows, labeled-annotations, background-sections, bordered-panels, emoji-or-symbols

**Domain**: nlp, cv, multimodal, llm, speech, reinforcement-learning, information-retrieval, knowledge-graph, code-generation, dialogue, machine-translation, data-curation, alignment, reasoning, agents, question-answering, summarization, prompt-engineering, retrieval-augmented-generation, safety-alignment, instruction-tuning, chain-of-thought, tool-use, planning

**Use Case**: benchmark-overview, method-comparison, system-design-reference, dataset-structure, training-pipeline-reference, evaluation-setup, task-definition, research-motivation, ablation-overview, error-analysis

{caption_hint}

## Response — JSON only, NO markdown:
{{
  "complete": true/false,
  "accept": true/false,
  "layout": "standalone|in-text",
  "reason": "one-line explanation",
  "description": "2-4 retrieval-friendly sentences (empty if rejected)",
  "tags": ["tag1", "tag2", ...],
  "figure_type": "framework-overview|system-architecture|model-architecture|dataset-overview|methodology|pipeline|conceptual|taxonomy|infographic|comparison|task-illustration|other",
  "design_highlights": "1-2 sentences on visual design (empty if rejected)"
}}"""


VALID_FIGURE_TYPES = {
    "framework-overview", "system-architecture", "model-architecture",
    "dataset-overview", "methodology", "pipeline", "conceptual",
    "taxonomy", "infographic", "comparison", "task-illustration", "other",
}


# ── Image Preprocessing ─────────────────────────────────────────────

def encode_image(image_path: Path, max_width: int = IMAGE_MAX_WIDTH,
                 jpeg_quality: int = IMAGE_JPEG_QUALITY) -> str:
    """Load, resize, compress, and base64-encode an image for LLM vision API."""
    img = Image.open(image_path)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, int(img.height * ratio)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=jpeg_quality)
    return base64.b64encode(buf.getvalue()).decode()


# ── JSON Parsing ─────────────────────────────────────────────────────

def parse_json_response(text: str) -> dict:
    """Robustly parse JSON from LLM output."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass
    logger.warning("Failed to parse JSON: %s", text[:200])
    return {}




# ── Public API ───────────────────────────────────────────────────────

def screen_and_analyze(figure_path: str, caption: str = "") -> dict:
    """Screen, check completeness, classify layout, and analyze in ONE LLM call.

    Returns dict with: accepted, reason, description, tags, figure_type,
                       layout_type, design_highlights
    """
    full_path = FIGURE_DIR / figure_path
    if not full_path.exists():
        return _rejected("File not found")
    if full_path.stat().st_size < MIN_FILE_SIZE:
        return _rejected("Image too small (< 10KB)")

    caption_hint = f'Caption from paper: "{caption[:300]}"' if caption else ""
    prompt = COMBINED_PROMPT.format(caption_hint=caption_hint)

    try:
        img_b64 = encode_image(full_path)
        result = _call_llm_vision(prompt, img_b64)
        if not result:
            return _rejected("LLM returned empty response")

        # Check completeness first
        if not result.get("complete", True):
            return _rejected("Incomplete figure: " + result.get("reason", "cut off"))

        # Check accept/reject
        if result.get("accept"):
            layout = result.get("layout", "standalone").lower().strip()
            if layout not in ("standalone", "in-text"):
                layout = "standalone"
            return {
                "accepted": True,
                "reason": result.get("reason", "Accepted"),
                "description": result.get("description", caption or ""),
                "tags": _clean_tags(result.get("tags", [])),
                "figure_type": _validate_figure_type(result.get("figure_type", "other")),
                "layout_type": layout,
                "quality_score": 0,
                "design_highlights": result.get("design_highlights", ""),
            }
        else:
            return _rejected(result.get("reason", "Rejected by LLM"))
    except Exception as e:
        logger.error("screen_and_analyze failed for %s: %s", figure_path, e)
        return _rejected(f"Error: {e}")


def screen_figure(figure_path: str, caption: str = "") -> dict:
    """Quick screen only."""
    result = screen_and_analyze(figure_path, caption)
    return {"accept": result["accepted"], "reason": result["reason"]}


def analyze_figure(figure_path: str, caption: str = "") -> dict:
    """Full analysis."""
    result = screen_and_analyze(figure_path, caption)
    if result["accepted"]:
        return {k: result[k] for k in ("description", "tags", "figure_type", "quality_score", "design_highlights")}
    return {"description": caption or "", "tags": [], "figure_type": "other", "quality_score": 0, "design_highlights": ""}


# ── Helpers ──────────────────────────────────────────────────────────

def _rejected(reason: str) -> dict:
    return {
        "accepted": False, "reason": reason,
        "description": "", "tags": [], "figure_type": "other",
        "layout_type": "", "quality_score": 0, "design_highlights": "",
    }


def _clean_tags(tags: list) -> list:
    """Normalize tags: lowercase, strip, deduplicate, remove empties."""
    if not isinstance(tags, list):
        return []
    seen = set()
    cleaned = []
    for t in tags:
        if isinstance(t, str):
            t = t.strip().lower().replace(" ", "-")
            if t and t not in seen:
                seen.add(t)
                cleaned.append(t)
    return cleaned


def _validate_figure_type(ft: str) -> str:
    ft = ft.strip().lower()
    return ft if ft in VALID_FIGURE_TYPES else "other"
