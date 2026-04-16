<div align="center">

# 📊 FigBench

**A Curated Benchmark of Hand-Designed Academic Figures from Top NLP/AI Conferences**

[![Figures](https://img.shields.io/badge/Figures-1136-blue?style=for-the-badge)](.)
[![Papers](https://img.shields.io/badge/Papers-711-green?style=for-the-badge)](.)
[![Venues](https://img.shields.io/badge/Venues-ACL%20%7C%20EMNLP%20%7C%20NAACL-orange?style=for-the-badge)](.)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)

*FigBench is a large-scale, human-curated collection of professionally hand-designed figures extracted from top-tier NLP/AI conference papers, built for figure aesthetic evaluation, retrieval, and preference benchmarking.*

</div>

---

## 🌟 Highlights

- 🎨 **Hand-Designed Only** — Every figure is a professionally crafted illustration (framework overviews, architecture diagrams, pipeline illustrations, etc.). Standard auto-generated charts, tables, and plots are excluded.
- 🔍 **Rich Metadata** — Each figure has description, multi-dimensional tags, figure type, layout classification, paper title, venue, and caption — enabling powerful retrieval and comparison.
- 🏷️ **Layout Annotated** — Figures are classified as `standalone` (full-width, clean extraction) or `in-text` (embedded in paper column with surrounding text), supporting controlled evaluation.
- 🧹 **Human-Verified** — Two-stage quality pipeline: LLM-based screening (HY-Vision-2.0-instruct) followed by manual human review to remove incomplete/corrupted figures.
- 🌐 **Interactive Web UI** — Built-in gallery with search, tag filtering, in-place cropping, label editing, and figure replacement.

---

## 📋 Dataset Overview

| Metric | Value |
|--------|-------|
| **Total Figures** | 1,136 |
| **Total Papers** | 711 |
| **Venues** | ACL 2024, EMNLP 2025, NAACL 2025 |
| **Layout Types** | 582 standalone · 554 in-text |
| **Figure Types** | 12 categories |
| **Avg Figures / Paper** | 1.60 |
| **Format** | JPEG (avg ~200KB per figure) |

### Venue Distribution

| Venue | Papers | Figures |
|-------|--------|---------|
| ACL 2024 | 457 | 717 |
| NAACL 2025 | 133 | 228 |
| EMNLP 2025 | 121 | 198 |

### Figure Type Distribution

| Type | Count | % |
|------|-------|---|
| Comparison | 322 | 28.3% |
| Conceptual | 149 | 13.1% |
| Framework Overview | 133 | 11.8% |
| Methodology | 110 | 9.6% |
| Task Illustration | 97 | 8.6% |
| Pipeline | 95 | 8.3% |
| Model Architecture | 59 | 5.2% |
| System Architecture | 39 | 3.4% |
| Dataset Overview | 18 | 1.6% |
| Taxonomy | 17 | 1.5% |

### Tag System (5 Dimensions)

| Dimension | Example Tags |
|-----------|-------------|
| **Structure** | `multi-panel`, `single-panel`, `hierarchical`, `side-by-side` |
| **Category** | `framework-overview`, `model-architecture`, `pipeline-illustration`, `comparison-illustration` |
| **Visual** | `custom-icons`, `color-coded`, `labeled-annotations`, `connector-arrows` |
| **Domain** | `nlp`, `llm`, `multimodal`, `reasoning`, `dialogue`, `code-generation` |
| **Use Case** | `system-design-reference`, `task-definition`, `evaluation-setup`, `training-pipeline-reference` |

---

## 🚀 Quick Start

### Installation

```bash
git clone https://github.com/mengze-hong/FigBench.git
cd FigBench
pip install -r backend/requirements.txt
```

### Launch Web Gallery

```bash
cd backend
python -m uvicorn server:app --host 0.0.0.0 --port 8766
# Open http://localhost:8766
```

### Configuration

Copy `.env.example` to `.env` and set your API key (required for data processing pipeline only, not for browsing):

```bash
cp .env.example .env
# Edit .env with your LLM API credentials
```

---

## 🖼️ Web UI Features

The built-in web interface provides:

- **🔍 Search** — Full-text search across descriptions, captions, and paper titles
- **🏷️ Tag Filtering** — Click tags to filter by category, domain, or visual style
- **📋 Venue / Type / Layout Filters** — Dropdown filters for all metadata dimensions
- **✂️ In-Place Cropping** — Click Crop, drag to select region, apply — original backed up automatically
- **✏️ Label Editing** — Edit description, tags, figure type, and layout directly in the modal
- **📋 Figure Replacement** — Paste a new image (Ctrl+V) to replace any figure
- **❌ Manual Flagging** — Hover and click × to remove bad figures (moved to `bad_figures/`)

---

## 📁 Project Structure

```
FigBench/
├── README.md
├── STATISTICS.md              # Auto-generated dataset statistics
├── start.py                   # One-click server launcher
│
├── backend/
│   ├── config.py              # Centralized configuration
│   ├── database.py            # SQLite data layer
│   ├── server.py              # FastAPI web server + API
│   ├── log.py                 # Unified logging
│   ├── requirements.txt
│   │
│   ├── pipeline/
│   │   ├── run.py             # Unified CLI: download → extract → screen → store
│   │   ├── scraper.py         # ACL Anthology paper downloader (8-thread concurrent)
│   │   ├── extractor.py       # PDF figure extraction (caption-guided precise cropping)
│   │   ├── analyzer.py        # LLM vision screening + tagging (HY-Vision-2.0-instruct)
│   │   └── maintenance.py     # Dedup, cleanup, stats
│   │
│   └── data/
│       ├── db/gallery.db      # SQLite database
│       ├── metadata.json      # Exported metadata
│       └── figures/            # 711 paper dirs, 1136 JPEGs
│
└── frontend/
    ├── index.html
    ├── app.js
    └── style.css
```

---

## ⚙️ Data Processing Pipeline

The pipeline processes papers end-to-end in one command:

```bash
# Process 200 papers from a venue
python -m pipeline.run --venue 2025.emnlp-main --range 1-200

# Check status
python -m pipeline.run --status

# Cleanup (dedup + orphan removal)
python -m pipeline.run --cleanup
```

### Pipeline Stages

```
Download PDF (8-thread) → Extract Figures (caption-guided crop)
    → LLM Screen (accept hand-designed / reject charts)
    → LLM Analyze (description + tags + type + layout)
    → Store to DB → Cleanup
```

**Screening criteria:**
- ✅ Accept: framework overviews, architecture diagrams, dataset illustrations, pipeline diagrams, conceptual figures, infographics
- ❌ Reject: bar/line/pie charts, tables, heatmaps, training curves, confusion matrices, standard matplotlib output

---

## 📊 API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/figures` | GET | Search & browse with pagination, filters |
| `/api/figures/{id}` | GET | Single figure with full metadata |
| `/api/figures/{id}` | PATCH | Update description, tags, type, layout |
| `/api/figures/{id}` | DELETE | Flag as bad (move to bad_figures/) |
| `/api/figures/{id}/crop` | POST | Crop figure in-place |
| `/api/figures/{id}/replace` | POST | Replace figure via base64 image |
| `/api/tags` | GET | All unique tags |
| `/api/figure-types` | GET | All figure types |
| `/api/stats` | GET | Dataset statistics |

---

## 🗺️ Roadmap

- [x] ACL 2024 long papers (457 papers, 717 figures)
- [x] EMNLP 2025 main (121 papers, 198 figures)
- [x] NAACL 2025 long (133 papers, 228 figures)
- [ ] ICML 2025 / NeurIPS 2024 (single-column format)
- [ ] Pairwise preference annotation for figure aesthetics
- [ ] Embedding-based similar figure retrieval
- [ ] Automated figure quality scoring benchmark

---

## 📝 Citation

If you use FigBench in your research, please cite:

```bibtex
@misc{figbench2025,
    title={FigBench: A Curated Benchmark of Hand-Designed Academic Figures},
    author={Meng, Zehong},
    year={2025},
    url={https://github.com/mengze-hong/FigBench}
}
```

---

## 📬 Contact

For questions or collaboration, please open an [issue](https://github.com/mengze-hong/FigBench/issues) or reach out directly.

---

<div align="center">
<sub>Built with FastAPI · SQLite · pypdfium2 · HY-Vision-2.0-instruct</sub>
</div>
