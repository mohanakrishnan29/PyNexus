"""Playwright crawler: rendered DOM in, cleaned documentation JSON out."""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

from backend.extractor.trafilatura_extractor import DocumentationExtractor
from backend.utils.config import settings
from backend.utils.logger import get_logger

logger = get_logger("PyNexus.playwright")
BAD_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".pdf", ".zip", ".gz", ".css", ".js", ".xml", ".json", ".woff", ".woff2"}


@dataclass
class CrawlResult:
    seed_url: str
    pages_crawled: int
    pages_saved: int
    output_dir: str
    failed_urls: List[str] = field(default_factory=list)
    stopped_early: bool = False
    stalled: bool = False


def normalize_url(url: str) -> str:
    p = urlparse(url)
    query = urlencode(sorted((key, value) for key, value in parse_qsl(p.query, keep_blank_values=True)
                            if not (key.lower().startswith("utm_") or key.lower() in {"gclid", "fbclid"})))
    return urlunparse((p.scheme, p.netloc, p.path or "/", "", query, ""))


class Crawler:
    def __init__(self, seed_url: str, allowed_path: Optional[str] = None, max_pages: Optional[int] = None,
                 same_domain_only: bool = True, delay_seconds: Optional[float] = None,
                 crawl_depth: Optional[int] = None, output_dir: Optional[Path] = None,
                 stop_flag: Optional[threading.Event] = None, stall_timeout: Optional[float] = None) -> None:
        if not seed_url.startswith(("http://", "https://")):
            raise ValueError("seed_url must start with http:// or https://")
        self.seed_url, self.allowed_path = normalize_url(seed_url), allowed_path
        self.max_pages = max_pages or settings.crawler_max_pages
        self.same_domain_only, self.delay_seconds = same_domain_only, delay_seconds if delay_seconds is not None else settings.crawler_download_delay
        self.crawl_depth = crawl_depth if crawl_depth is not None else settings.crawler_depth_limit
        self.output_dir, self.stop_flag = Path(output_dir or settings.raw_dir), stop_flag
        self.domain = urlparse(self.seed_url).netloc
        self.extractor = DocumentationExtractor()

    def _robots(self) -> RobotFileParser:
        seed = urlparse(self.seed_url)
        parser = RobotFileParser(f"{seed.scheme}://{seed.netloc}/robots.txt")
        try:
            parser.read()
        except Exception as exc:
            logger.info("robots.txt unavailable for %s: %s", self.domain, exc)
        return parser

    def _followable(self, url: str, robots: RobotFileParser) -> bool:
        p = urlparse(url)
        if p.scheme not in {"http", "https"} or Path(p.path).suffix.lower() in BAD_EXTENSIONS:
            return False
        if self.same_domain_only and p.netloc != self.domain:
            return False
        if self.allowed_path and not p.path.startswith(self.allowed_path):
            return False
        if any(x in url.lower() for x in ("/login", "/signin", "/search", "?q=")):
            return False
        return robots.can_fetch(settings.crawler_user_agent, url)

    @staticmethod
    def _filename(url: str) -> str:
        path = re.sub(r"[^A-Za-z0-9._-]", "_", urlparse(url).path.strip("/") or "index")[:80]
        return f"{path}_{hashlib.sha1(url.encode()).hexdigest()[:10]}.json"

    @staticmethod
    def _expand(page) -> None:
        page.eval_on_selector_all("details", "els => els.forEach(e => e.open = true)")
        for selector in ("button:has-text('Show more')", "button:has-text('Load more')"):
            try:
                for button in page.locator(selector).all()[:20]:
                    if button.is_visible():
                        button.click(timeout=1000)
            except Exception:
                pass
        page.evaluate("""async () => { for(let y=0;y<document.body.scrollHeight;y+=900) {
          window.scrollTo(0,y); await new Promise(r=>setTimeout(r,80)); } window.scrollTo(0,0) }""")

    def run(self) -> CrawlResult:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Playwright is required; run `pip install playwright` then `playwright install chromium`.") from exc
        robots, queue, seen, failures = self._robots(), [(self.seed_url, 0)], set(), []
        crawled = saved = 0
        self.output_dir.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(user_agent=settings.crawler_user_agent)
            page = context.new_page()
            page.set_default_timeout(int(__import__('os').getenv("PLAYWRIGHT_TIMEOUT_MS", "30000")))
            while queue and crawled < self.max_pages:
                if self.stop_flag and self.stop_flag.is_set():
                    context.close(); browser.close()
                    return CrawlResult(self.seed_url, crawled, saved, str(self.output_dir), failures, True)
                url, depth = queue.pop(0)
                if url in seen or not self._followable(url, robots):
                    continue
                seen.add(url)
                try:
                    page.goto(url, wait_until="domcontentloaded")
                    try: page.wait_for_load_state("networkidle", timeout=8000)
                    except Exception: pass
                    self._expand(page)
                    final_url, html = normalize_url(page.url), page.content()
                    crawled += 1
                    extracted = self.extractor.extract(final_url, html)
                    if extracted:
                        (self.output_dir / self._filename(final_url)).write_text(json.dumps(extracted, ensure_ascii=False, indent=2), encoding="utf-8")
                        saved += 1
                    if not self.crawl_depth or depth < self.crawl_depth:
                        for href in page.locator("a[href]").evaluate_all("els => els.map(a => a.href)"):
                            candidate = normalize_url(urljoin(final_url, href))
                            if candidate not in seen and self._followable(candidate, robots): queue.append((candidate, depth + 1))
                    if self.delay_seconds: time.sleep(self.delay_seconds)
                except Exception as exc:
                    logger.warning("Crawl failure for %s: %s", url, exc); failures.append(url)
            context.close(); browser.close()
        return CrawlResult(self.seed_url, crawled, saved, str(self.output_dir), failures)
