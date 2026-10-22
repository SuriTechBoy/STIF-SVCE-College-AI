from __future__ import annotations

import argparse
import csv
import json
import os
import re
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ingestion.crawler import SiteCrawler, USER_AGENT

load_dotenv()
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
INDEX = DATA / "index"
SOURCES = DATA / "sources"
REPORTS = DATA / "reports"


def ensure_dirs():
    for path in [RAW, PROCESSED, INDEX, SOURCES, REPORTS]:
        path.mkdir(parents=True, exist_ok=True)


def safe_filename(url: str, suffix: str = ".txt") -> str:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:18]
    return digest + suffix


def clean_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def split_chunks(text: str, size: int = 1100, overlap: int = 150) -> list[str]:
    text = clean_text(text)
    if not text:
        return []
    chunks, start = [], 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            boundary = max(text.rfind(". ", start, end), text.rfind("\n", start, end))
            if boundary > start + size // 2:
                end = boundary + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


def download_pdfs(seed_urls: list[str], allowed_domains: set[str], timeout: int = 20):
    session = requests.Session()

    retry_strategy = Retry(
    total=4,
    connect=4,
    read=2,
    status=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=frozenset(["GET"]),
    respect_retry_after_header=True,
)
    adapter = HTTPAdapter(max_retries=retry_strategy)

    session.mount("https://", adapter)
    session.mount("http://", adapter)

    session.headers["User-Agent"] = USER_AGENT
    results = []
    for url in seed_urls:
        parsed = urlparse(url)
        if parsed.netloc.lower() not in allowed_domains or not parsed.path.lower().endswith(".pdf"):
            continue
        path = RAW / safe_filename(url, ".pdf")
        try:
            response = session.get(url, timeout=timeout)
            response.raise_for_status()
            if "pdf" not in response.headers.get("content-type", "").lower() and not response.content.startswith(b"%PDF"):
                continue
            path.write_bytes(response.content)
            reader = PdfReader(str(path))
            pages = []
            for page in reader.pages:
                try:
                    pages.append(page.extract_text() or "")
                except Exception:
                    pages.append("")
            text = clean_text("\n".join(pages))
            results.append({
                "url": url, "title": Path(parsed.path).name, "text": text,
                "content_type": "application/pdf", "status_code": response.status_code,
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "extraction_note": "Scanned/image-only PDFs may require OCR; review if extracted text is empty."
            })
        except Exception as exc:
            results.append({"url": url, "title": Path(parsed.path).name, "text": "",
                             "content_type": "application/pdf", "error": str(exc),
                             "collected_at": datetime.now(timezone.utc).isoformat()})
    return results


def run_ingestion(start_url: str | None = None, max_pages: int | None = None):
    ensure_dirs()
    start_url = start_url or os.getenv("START_URL", "https://svce.edu.in/")
    allowed_domains = set(d.strip().lower() for d in os.getenv(
        "ALLOWED_DOMAINS", "svce.edu.in,www.svce.edu.in").split(",") if d.strip())
    max_pages = max_pages or int(os.getenv("MAX_PAGES", "500"))
    delay = float(os.getenv("CRAWL_DELAY_SECONDS", "1.0"))
    timeout = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "20"))
    started = datetime.now(timezone.utc).isoformat()

    crawler = SiteCrawler(start_url, list(allowed_domains), max_pages=max_pages, delay=delay, timeout=timeout)
    docs = []
    pdf_urls = set()
    for item in crawler.crawl():
        collected_at = datetime.now(timezone.utc).isoformat()
        raw_file = RAW / safe_filename(item["url"], ".html.txt")
        raw_file.write_text(item["text"], encoding="utf-8")
        item["collected_at"] = collected_at
        item["raw_file"] = str(raw_file.relative_to(ROOT))
        docs.append(item)
        # Discover PDFs from links on the page. They are downloaded in a separate pass.
        for link in item.get("links", []):
            if urlparse(link).path.lower().endswith(".pdf"):
                pdf_urls.add(link)

    pdf_docs = download_pdfs(sorted(pdf_urls), allowed_domains, timeout=timeout)
    docs.extend(pdf_docs)

    processed_docs = []
    chunk_rows = []
    inventory_rows = []
    for doc in docs:
        text = clean_text(doc.get("text", ""))
        record = {
            "doc_id": hashlib.sha256(doc["url"].encode("utf-8")).hexdigest()[:18],
            "url": doc["url"],
            "title": doc.get("title", doc["url"]),
            "text": text,
            "content_type": doc.get("content_type", ""),
            "collected_at": doc.get("collected_at", datetime.now(timezone.utc).isoformat()),
            "verification_status": "NEEDS_VERIFICATION",
            "extraction_note": doc.get("extraction_note", ""),
            "error": doc.get("error", ""),
        }
        processed_docs.append(record)
        (PROCESSED / f"{record['doc_id']}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        chunks = split_chunks(text)
        for i, chunk in enumerate(chunks):
            chunk_rows.append({
                "chunk_id": f"{record['doc_id']}_{i:04d}",
                "doc_id": record["doc_id"],
                "title": record["title"],
                "url": record["url"],
                "text": chunk,
                "collected_at": record["collected_at"],
                "verification_status": record["verification_status"],
            })
        inventory_rows.append({
            "url": record["url"], "title": record["title"], "content_type": record["content_type"],
            "characters_extracted": len(text), "chunks": len(chunks),
            "verification_status": record["verification_status"],
            "collected_at": record["collected_at"], "error": record["error"],
        })

    chunks_path = INDEX / "chunks.jsonl"
    with chunks_path.open("w", encoding="utf-8") as f:
        for row in chunk_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    inventory_path = SOURCES / "source_inventory.csv"
    if inventory_rows:
        with inventory_path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list(inventory_rows[0].keys()))
            writer.writeheader()
            writer.writerows(inventory_rows)
    else:
        inventory_path.write_text("url,title,content_type,characters_extracted,chunks,verification_status,collected_at,error\n", encoding="utf-8")

    report = {
        "status": "completed_with_review_required",
        "started_at": started,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "start_url": start_url,
        "allowed_domains": sorted(allowed_domains),
        "max_pages": max_pages,
        "html_documents": sum(1 for d in docs if "html" in d.get("content_type", "")),
        "pdf_documents": sum(1 for d in docs if d.get("content_type") == "application/pdf"),
        "documents_total": len(docs),
        "chunks_total": len(chunk_rows),
        "crawl_errors": crawler.errors,
        "documents_with_extraction_errors": sum(1 for d in docs if d.get("error")),
        "warning": "Collection completion does not mean all pages were discovered or facts were verified. Review source inventory, errors, PDFs, and time-sensitive claims.",
    }
    (REPORTS / "ingestion_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description="Collect public SVCE Tirupati website knowledge.")
    parser.add_argument("--start-url", default=None)
    parser.add_argument("--max-pages", type=int, default=None)
    args = parser.parse_args()
    report = run_ingestion(args.start_url, args.max_pages)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
