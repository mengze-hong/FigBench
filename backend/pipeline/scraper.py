"""ACL Anthology scraper – fetch paper metadata and PDFs."""

import re
import time
import requests
from bs4 import BeautifulSoup
from pathlib import Path
from typing import List, Dict
from tqdm import tqdm

from config import ACL_ANTHOLOGY_BASE, PDF_DIR
from database import insert_paper, paper_exists_by_url


def fetch_acl_volume(volume_id: str, max_papers: int = 100) -> List[Dict]:
    """Scrape paper list from an ACL Anthology volume page.

    Example volume_ids:
        '2024.acl-long'    – ACL 2024 long papers
        '2024.acl-short'   – ACL 2024 short papers
        '2024.emnlp-main'  – EMNLP 2024 main
        '2023.acl-long'    – ACL 2023 long papers
        '2024.naacl-long'  – NAACL 2024
        '2024.eacl-long'   – EACL 2024
    """
    url = f"{ACL_ANTHOLOGY_BASE}/volumes/{volume_id}/"
    print(f"[Scraper] Fetching volume page: {url}")
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    papers = []
    # Each paper is in a <p> with class "d-sm-flex"
    entries = soup.select("p.d-sm-flex")
    if not entries:
        # Fallback: try alternate structure
        entries = soup.select("div.paper-list p") or soup.select("span.d-block")

    for entry in entries[:max_papers + 5]:  # extra buffer to skip non-papers
        try:
            # Title
            title_tag = entry.select_one("strong a.align-middle") or entry.select_one("strong a")
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)
            href = title_tag["href"]
            paper_url = ACL_ANTHOLOGY_BASE + href if href.startswith("/") else href

            # Skip proceedings entry (entry 0, usually "Proceedings of...")
            if title.lower().startswith("proceedings of"):
                continue

            # Authors
            author_spans = entry.select("a[href*='/people/']")
            authors = ", ".join(a.get_text(strip=True) for a in author_spans)

            # PDF link – try multiple strategies
            pdf_url = ""

            # Strategy 1: Direct PDF link in entry
            pdf_tag = entry.select_one("a[href$='.pdf']")
            if pdf_tag:
                h = pdf_tag["href"]
                pdf_url = h if h.startswith("http") else ACL_ANTHOLOGY_BASE + h

            # Strategy 2: Construct from paper URL
            # ACL Anthology pattern: /2024.acl-long.1/ → /2024.acl-long.1.pdf
            if not pdf_url and href:
                paper_slug = href.strip("/").split("/")[-1]  # e.g. "2024.acl-long.1"
                pdf_url = f"{ACL_ANTHOLOGY_BASE}/{paper_slug}.pdf"

            # Parse venue/year from volume_id
            parts = volume_id.split(".")
            year = int(parts[0]) if parts[0].isdigit() else 2024
            venue = parts[1].split("-")[0].upper() if len(parts) > 1 else "ACL"

            papers.append({
                "title": title,
                "authors": authors,
                "venue": venue,
                "year": year,
                "url": paper_url,
                "pdf_url": pdf_url,
            })

            if len(papers) >= max_papers:
                break
        except Exception as e:
            print(f"[Scraper] Skip entry: {e}")
            continue

    print(f"[Scraper] Found {len(papers)} papers in {volume_id}")
    return papers


def download_pdf(pdf_url: str, paper_id: str) -> Path:
    """Download a PDF and return local path."""
    if not pdf_url:
        raise ValueError("No PDF URL")
    out = PDF_DIR / f"{paper_id}.pdf"
    if out.exists():
        return out
    print(f"[Download] {pdf_url}")
    resp = requests.get(pdf_url, timeout=60, stream=True)
    resp.raise_for_status()
    with open(out, "wb") as f:
        for chunk in resp.iter_content(8192):
            f.write(chunk)
    return out


def ingest_volume(volume_id: str, max_papers: int = 50) -> List[str]:
    """Scrape a volume, download PDFs, return list of paper_ids."""
    papers = fetch_acl_volume(volume_id, max_papers)
    paper_ids = []

    for p in tqdm(papers, desc=f"Ingesting {volume_id}"):
        if paper_exists_by_url(p["url"]):
            continue
        pid = insert_paper(
            title=p["title"], authors=p["authors"], venue=p["venue"],
            year=p["year"], url=p["url"], pdf_url=p["pdf_url"],
        )
        try:
            pdf_path = download_pdf(p["pdf_url"], pid)
            # Update pdf_path in DB
            from database import get_conn
            conn = get_conn()
            conn.execute("UPDATE papers SET pdf_path=? WHERE id=?", (str(pdf_path), pid))
            conn.commit()
            conn.close()
            paper_ids.append(pid)
        except Exception as e:
            print(f"[Ingest] Failed to download PDF for '{p['title'][:60]}': {e}")
        time.sleep(0.5)  # Be polite

    print(f"[Ingest] Ingested {len(paper_ids)} new papers from {volume_id}")
    return paper_ids
