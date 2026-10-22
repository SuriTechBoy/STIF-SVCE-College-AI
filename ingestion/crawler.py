from __future__ import annotations

import time
from collections import deque
from urllib.parse import urljoin, urlparse, urldefrag
from urllib.robotparser import RobotFileParser
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = "STIF-SVCE-KnowledgeBot/0.1 (+educational knowledge collection; contact site administrator)"
SKIP_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".css", ".js", ".ico",
    ".zip", ".rar", ".mp4", ".mp3", ".woff", ".woff2", ".ttf", ".eot",
}


def normalize_url(url: str) -> str:
    url, _ = urldefrag(url)
    parsed = urlparse(url)
    scheme = parsed.scheme or "https"
    path = parsed.path or "/"
    return f"{scheme}://{parsed.netloc.lower()}{path}" + (f"?{parsed.query}" if parsed.query else "")


def is_html_candidate(url: str) -> bool:
    path = urlparse(url).path.lower()
    return not any(path.endswith(ext) for ext in SKIP_EXTENSIONS)


class SiteCrawler:
    def __init__(self, start_url: str, allowed_domains: list[str], max_pages: int = 500,
                 delay: float = 1.0, timeout: int = 20):
        self.start_url = normalize_url(start_url)
        self.allowed_domains = {d.lower().strip() for d in allowed_domains if d.strip()}
        self.max_pages = max_pages
        self.delay = max(0.0, delay)
        self.timeout = timeout
        self.session = requests.Session()
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
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        self.session.headers.update({"User-Agent": USER_AGENT})
        self.errors: list[dict] = []
        self.robots = RobotFileParser()
        parsed = urlparse(self.start_url)
        self.robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        try:
            self.robots.set_url(self.robots_url)
            self.robots.read()
            self.robots_loaded = True
        except Exception as exc:
            self.robots_loaded = False
            self.errors.append({"url": self.robots_url, "error": f"robots.txt unavailable: {exc}"})

    def allowed(self, url: str) -> bool:
        host = urlparse(url).netloc.lower()
        if host not in self.allowed_domains:
            return False
        if self.robots_loaded:
            try:
                return self.robots.can_fetch(USER_AGENT, url)
            except Exception:
                return False
        # Conservative fallback when robots.txt could not be read: don't crawl automatically.
        return False

    def sitemap_urls(self) -> list[str]:
        parsed = urlparse(self.start_url)
        candidates = [f"{parsed.scheme}://{parsed.netloc}/sitemap.xml",
                      f"{parsed.scheme}://{parsed.netloc}/sitemap_index.xml"]
        found = []
        for sitemap in candidates:
            try:
                if not self.allowed(sitemap):
                    continue
                response = self.session.get(sitemap, timeout=self.timeout)
                if response.ok and "xml" in response.headers.get("content-type", "").lower():
                    soup = BeautifulSoup(response.text, "xml")
                    found.extend(loc.get_text(strip=True) for loc in soup.find_all("loc"))
            except Exception as exc:
                self.errors.append({"url": sitemap, "error": str(exc)})
        return [normalize_url(u) for u in found if u.startswith(("http://", "https://"))]

    def crawl(self):
        queue = deque([self.start_url])
        for url in self.sitemap_urls():
            if url not in queue:
                queue.append(url)
        visited = set()
        while queue and len(visited) < self.max_pages:
            url = normalize_url(queue.popleft())
            if url in visited or not is_html_candidate(url) or not self.allowed(url):
                continue
            visited.add(url)
            try:
                response = self.session.get(url, timeout=self.timeout)
                if response.status_code in (429, 500, 502, 503, 504):
                    time.sleep(max(self.delay, 2))
                    response = self.session.get(url, timeout=self.timeout)
                response.raise_for_status()
                ctype = response.headers.get("content-type", "").lower()
                if "text/html" not in ctype and "application/xhtml" not in ctype:
                    continue
                soup = BeautifulSoup(response.text, "html.parser")
                title = soup.title.get_text(" ", strip=True) if soup.title else url
                for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header"]):
                    tag.decompose()
                main = soup.find("main") or soup.find("article") or soup.body or soup
                text = " ".join(main.stripped_strings)
                yield {
                    "url": url,
                    "title": title,
                    "text": text,
                    "content_type": ctype,
                    "status_code": response.status_code,
                    "links": self._extract_links(soup, url),
                }
                for link in self._extract_links(soup, url):
                    if link not in visited and link not in queue and is_html_candidate(link):
                        queue.append(link)
                time.sleep(self.delay)
            except Exception as exc:
                self.errors.append({"url": url, "error": str(exc)})

    def _extract_links(self, soup, current_url):
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.startswith(("mailto:", "tel:", "javascript:", "#")):
                continue
            full = normalize_url(urljoin(current_url, href))
            if urlparse(full).netloc.lower() in self.allowed_domains:
                links.append(full)
        return list(dict.fromkeys(links))
