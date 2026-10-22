from __future__ import annotations

import json
import time
import hashlib
from pathlib import Path
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw_fast"
PROCESSED = DATA / "processed_fast"
REPORTS = DATA / "reports"

BASE_URL = "https://svce.edu.in/"
ALLOWED_HOSTS = {"svce.edu.in", "www.svce.edu.in"}
MAX_WORKERS = 4
TIMEOUT = 15
MAX_URLS = 300

for folder in (RAW, PROCESSED, REPORTS):
    folder.mkdir(parents=True, exist_ok=True)


def make_session():
    session = requests.Session()

    retry = Retry(
        total=3,
        connect=3,
        read=2,
        status=2,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET"]),
        respect_retry_after_header=True,
    )

    adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    session.headers.update({
        "User-Agent": "STIF-SVCE-KnowledgeBot/0.2"
    })

    return session


def normalize_url(url):
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        return None

    if parsed.hostname not in ALLOWED_HOSTS:
        return None

    if parsed.username or parsed.password:
        return None

    return url.split("#", 1)[0]


def discover_urls():
    session = make_session()
    found = {BASE_URL}
    queue = [BASE_URL]
    visited = set()

    while queue and len(visited) < MAX_URLS:
        current = queue.pop(0)

        if current in visited:
            continue

        visited.add(current)

        try:
            response = session.get(current, timeout=TIMEOUT)
            response.raise_for_status()

            content_type = response.headers.get("content-type", "").lower()

            if "html" not in content_type:
                continue

            soup = BeautifulSoup(response.text, "html.parser")

            for anchor in soup.select("a[href]"):
                link = normalize_url(urljoin(current, anchor["href"]))

                if not link or link in found:
                    continue

                found.add(link)

                # Crawl HTML pages; retain PDF links for downloading.
                path = urlparse(link).path.lower()

                if not path.endswith((".pdf", ".jpg", ".jpeg", ".png",
                                      ".gif", ".zip", ".mp4", ".mp3")):
                    queue.append(link)

            print(
                f"Discovered {len(found)} URLs; "
                f"visited {len(visited)} pages",
                flush=True,
            )

        except requests.RequestException as exc:
            print(f"Discovery failed: {current} — {exc}", flush=True)

        time.sleep(0.25)

    session.close()
    return sorted(found)


def extract_pdf(content):
    import io

    reader = PdfReader(io.BytesIO(content))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def download_document(url):
    session = make_session()
    doc_id = hashlib.sha256(url.encode()).hexdigest()[:18]
    output_path = PROCESSED / f"{doc_id}.json"

    # Reuse documents that were successfully extracted previously.
    if output_path.exists():
        try:
            previous = json.loads(output_path.read_text(encoding="utf-8"))
            if previous.get("text", "").strip() and not previous.get("error"):
                session.close()
                return {"status": "cached", "url": url}
        except (OSError, json.JSONDecodeError):
            pass

    try:
        response = session.get(url, timeout=TIMEOUT)
        response.raise_for_status()

        content_type = response.headers.get("content-type", "").lower()
        path = urlparse(url).path.lower()

        if "pdf" in content_type or path.endswith(".pdf"):
            text = extract_pdf(response.content)
            title = Path(urlparse(url).path).name
        elif "html" in content_type or "xhtml" in content_type:
            soup = BeautifulSoup(response.text, "html.parser")

            title = (
                soup.title.get_text(" ", strip=True)
                if soup.title else url
            )

            for tag in soup([
                "script", "style", "noscript", "svg",
                "nav", "footer", "header"
            ]):
                tag.decompose()

            main = soup.find("main") or soup.find("article") or soup.body or soup
            text = "\n".join(main.stripped_strings)
        else:
            session.close()
            return {
                "status": "skipped",
                "url": url,
                "reason": f"Unsupported content type: {content_type}",
            }

        record = {
            "doc_id": doc_id,
            "url": url,
            "title": title,
            "text": text.strip(),
            "content_type": content_type,
            "status_code": response.status_code,
            "collected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "verification_status": "NEEDS_VERIFICATION",
        }

        output_path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        session.close()

        return {
            "status": "success" if text.strip() else "empty",
            "url": url,
            "characters": len(text.strip()),
        }

    except Exception as exc:
        session.close()

        return {
            "status": "failed",
            "url": url,
            "error": str(exc),
        }


def main():
    start = time.time()

    print("Starting SVCE website collection...", flush=True)

    urls = discover_urls()

    url_file = DATA / "fast_discovered_urls.txt"
    url_file.write_text("\n".join(urls), encoding="utf-8")

    print(f"\nTotal discovered URLs: {len(urls)}", flush=True)
    print("Downloading pages and PDFs...", flush=True)

    results = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(download_document, url): url
            for url in urls
        }

        for future in as_completed(futures):
            result = future.result()
            results.append(result)

            print(
                f"[{result['status'].upper()}] {result['url']}",
                flush=True,
            )

    counts = {}

    for result in results:
        status = result["status"]
        counts[status] = counts.get(status, 0) + 1

    report = {
        "base_url": BASE_URL,
        "discovered_urls": len(urls),
        "results": counts,
        "elapsed_seconds": round(time.time() - start, 2),
        "failed_documents": [
            result for result in results
            if result["status"] == "failed"
        ],
        "empty_documents": [
            result for result in results
            if result["status"] == "empty"
        ],
        "warning": (
            "Collected documents require quality review. "
            "An empty PDF may require OCR. "
            "Collected facts have not been independently verified."
        ),
    }

    report_path = REPORTS / "fast_ingestion_report.json"

    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\nCollection finished.", flush=True)
    print(json.dumps(report, indent=2), flush=True)
    print(f"\nReport saved to: {report_path}", flush=True)


if __name__ == "__main__":
    main()