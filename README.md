# AcademicFigureGallery

> Curated high-quality, hand-designed academic figures from top-tier NLP/AI conferences.

## What is this?

A platform that extracts and curates **professionally designed figures** (framework overviews, architecture diagrams, dataset illustrations) from research papers at conferences like ACL, EMNLP, and NAACL. Every figure is screened by an LLM to ensure only visually impressive, hand-crafted illustrations make it into the gallery — no standard bar charts or tables.

## Quick Start

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn server:app --host 0.0.0.0 --port 8765
# Open http://localhost:8765
```

## Project Structure

```
AcademicFigureGallery/
├── README.md
├── .gitignore
├── backend/
│   ├── config.py              # Configuration (LLM, paths, thresholds)
│   ├── database.py            # SQLite data layer
│   ├── server.py              # FastAPI backend + frontend serving
│   ├── requirements.txt
│   ├── pipeline/
│   │   ├── analyzer.py        # LLM vision: screen + analyze figures
│   │   ├── extractor.py       # PDF → figure extraction (pypdfium2)
│   │   ├── maintenance.py     # DB cleanup utilities
│   │   ├── run.py             # End-to-end pipeline orchestrator
│   │   └── scraper.py         # ACL Anthology paper scraper
│   └── data/
│       ├── db/gallery.db      # SQLite database
│       ├── metadata.json      # Exported paper + figure metadata
│       └── figures/           # Curated figure images (PNG)
└── frontend/
    ├── index.html
    ├── app.js
    └── style.css
```

## Data

| Venue | Papers | Figures |
|-------|--------|---------|
| ACL 2024 | 13 | 23 |
| NAACL 2025 | 20 | 24 |
| EMNLP 2025 | 6 | 5 |
| **Total** | **39** | **52** |

## Pipeline

```
ACL Anthology → Download PDF → Extract embedded images → LLM screen (accept/reject) → Analyze (description, tags, score) → Gallery
```

**Accept**: framework overviews, architecture diagrams, dataset overviews, conceptual illustrations, pipeline diagrams  
**Reject**: bar/line/pie charts, tables, heatmaps, training curves, ablation plots

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Vanilla HTML/CSS/JS |
| Backend | FastAPI + SQLite |
| PDF Extraction | pypdfium2 |
| LLM | HY-Vision-2.0-instruct (Hunyuan) |
| Data Source | ACL Anthology |

## API

| Endpoint | Description |
|----------|-------------|
| `GET /api/figures` | Search & browse with filters |
| `GET /api/figures/{id}` | Figure detail |
| `GET /api/tags` | All tags |
| `GET /api/figure-types` | All figure types |
| `GET /api/stats` | Global statistics |
| `POST /api/ingest` | Trigger paper ingestion |
| `GET /docs` | Swagger docs |

## License

MIT
