"""SQLite database layer – thin wrapper around sqlite3."""

import sqlite3
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import DB_PATH


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS papers (
        id          TEXT PRIMARY KEY,
        title       TEXT NOT NULL,
        authors     TEXT,
        venue       TEXT,
        year        INTEGER,
        url         TEXT,
        pdf_url     TEXT,
        pdf_path    TEXT,
        created_at  TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS figures (
        id              TEXT PRIMARY KEY,
        paper_id        TEXT NOT NULL REFERENCES papers(id),
        filename        TEXT NOT NULL,
        page_num        INTEGER,
        width           INTEGER,
        height          INTEGER,
        description     TEXT,
        tags            TEXT,          -- JSON array
        figure_type     TEXT,          -- e.g. "architecture", "benchmark", "chart"
        caption         TEXT,          -- extracted caption from PDF if available
        quality_score   REAL DEFAULT 0,
        created_at      TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_figures_paper ON figures(paper_id);
    CREATE INDEX IF NOT EXISTS idx_figures_tags  ON figures(tags);
    CREATE INDEX IF NOT EXISTS idx_figures_type  ON figures(figure_type);
    CREATE INDEX IF NOT EXISTS idx_figures_score ON figures(quality_score DESC);
    """)
    conn.commit()
    conn.close()


# ── Paper CRUD ─────────────────────────────────────────────────────────

def insert_paper(title: str, authors: str, venue: str, year: int,
                 url: str, pdf_url: str, pdf_path: str = "") -> str:
    pid = str(uuid.uuid4())[:8]
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO papers (id,title,authors,venue,year,url,pdf_url,pdf_path) VALUES (?,?,?,?,?,?,?,?)",
        (pid, title, authors, venue, year, url, pdf_url, pdf_path),
    )
    conn.commit()
    conn.close()
    return pid


def get_paper(pid: str) -> Optional[dict]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM papers WHERE id=?", (pid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def paper_exists_by_url(url: str) -> bool:
    conn = get_conn()
    row = conn.execute("SELECT 1 FROM papers WHERE url=?", (url,)).fetchone()
    conn.close()
    return row is not None


# ── Figure CRUD ────────────────────────────────────────────────────────

def insert_figure(paper_id: str, filename: str, page_num: int,
                  width: int, height: int, description: str = "",
                  tags: list = None, figure_type: str = "",
                  caption: str = "", quality_score: float = 0) -> str:
    fid = str(uuid.uuid4())[:8]
    conn = get_conn()
    conn.execute(
        """INSERT INTO figures
           (id,paper_id,filename,page_num,width,height,description,tags,figure_type,caption,quality_score)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (fid, paper_id, filename, page_num, width, height, description,
         json.dumps(tags or []), figure_type, caption, quality_score),
    )
    conn.commit()
    conn.close()
    return fid


def search_figures(query: str = "", tags: list = None, figure_type: str = "",
                   layout_type: str = "",
                   venue: str = "", year: int = 0,
                   sort: str = "created_at", order: str = "DESC",
                   page: int = 1, per_page: int = 24) -> dict:
    """Full-text + tag + type search with pagination."""

    ALLOWED_SORT = {"quality_score", "created_at", "width", "height"}
    ALLOWED_ORDER = {"ASC", "DESC"}
    sort = sort if sort in ALLOWED_SORT else "created_at"
    order = order.upper() if order.upper() in ALLOWED_ORDER else "DESC"

    conn = get_conn()
    conditions = []
    params = []

    if query:
        conditions.append("(f.description LIKE ? OR f.caption LIKE ? OR p.title LIKE ?)")
        q = f"%{query}%"
        params.extend([q, q, q])
    if tags:
        for t in tags:
            conditions.append("f.tags LIKE ?")
            params.append(f'%"{t}"%')
    if figure_type:
        conditions.append("f.figure_type = ?")
        params.append(figure_type)
    if layout_type:
        conditions.append("f.layout_type = ?")
        params.append(layout_type)
    if venue:
        conditions.append("p.venue LIKE ?")
        params.append(f"%{venue}%")
    if year:
        conditions.append("p.year = ?")
        params.append(year)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    count_sql = f"SELECT COUNT(*) FROM figures f JOIN papers p ON f.paper_id=p.id {where}"
    total = conn.execute(count_sql, params).fetchone()[0]

    data_sql = f"""
        SELECT f.*, p.title as paper_title, p.authors, p.venue, p.year, p.url as paper_url
        FROM figures f JOIN papers p ON f.paper_id=p.id
        {where}
        ORDER BY f.{sort} {order}
        LIMIT ? OFFSET ?
    """
    params.extend([per_page, (page - 1) * per_page])
    rows = conn.execute(data_sql, params).fetchall()
    conn.close()

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
        "items": [dict(r) for r in rows],
    }


def get_all_tags() -> list:
    conn = get_conn()
    rows = conn.execute("SELECT tags FROM figures WHERE tags != '[]'").fetchall()
    conn.close()
    tag_set = set()
    for r in rows:
        for t in json.loads(r["tags"]):
            tag_set.add(t)
    return sorted(tag_set)


def get_all_figure_types() -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT figure_type FROM figures WHERE figure_type != '' ORDER BY figure_type"
    ).fetchall()
    conn.close()
    return [r["figure_type"] for r in rows]


def get_stats() -> dict:
    conn = get_conn()
    papers = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    figures = conn.execute("SELECT COUNT(*) FROM figures").fetchone()[0]
    venues = conn.execute("SELECT DISTINCT venue FROM papers").fetchall()
    conn.close()
    return {"papers": papers, "figures": figures, "venues": [r["venue"] for r in venues]}


# Auto-init on import
init_db()
