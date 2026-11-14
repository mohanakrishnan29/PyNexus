"""Spider for HTML documentation sites.

Pause support
-------------
When a ``stop_flag`` (threading.Event) is provided and is set, the spider
calls ``self.crawler.engine.close_spider()`` immediately after finishing the
page it is currently processing.  This means /pause responds within seconds
(one HTTP round-trip + page parse time) rather than waiting for the entire
source to complete.

The ``stopped_early`` attribute is set to True in this case so the caller
(Crawler / main.py) can record the source as 'paused' rather than 'done'.
"""
from __future__ import annotations

import json
import re
import threading
from typing import Optional
import time
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

import scrapy
from bs4 import BeautifulSoup
from scrapy import signals
from scrapy.exceptions import CloseSpider

from backend.scrapy_project.items import CrawledPageItem

# ---------------------------------------------------------------------------
# Selectors
# ---------------------------------------------------------------------------
NOISE_SELECTORS = (
    "script", "style", "noscript", "svg", "iframe", "form",
    "nav", "footer", "header", "aside",
    "[role=navigation]", "[role=banner]", "[role=contentinfo]",
    ".nav", ".navbar", ".sidebar", ".side-nav",
    ".breadcrumb", ".breadcrumbs",
    ".footer", ".header",
    ".cookie", ".cookies",
    ".advert", ".ads", ".ad",
    "#nav", "#navbar", "#sidebar", "#footer", "#header", "#cookie",
)
CONTENT_SELECTORS = (
    "main", "article", "[role=main]",
    "#main", "#content", "#main-content",
    ".main", ".content", ".main-content",
    ".doc-content", ".markdown-body",
)
BAD_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
    ".pdf", ".zip", ".tar", ".gz", ".rar", ".7z",
    ".mp3", ".mp4", ".mov", ".avi", ".wmv",
    ".css", ".js",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".xml", ".json", ".rss", ".atom",
}


class DocumentationSpider(scrapy.Spider):
    name = "documentation"

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(
        self,
        seed_url=None,
        output_dir=None,
        max_pages="5000",
        allowed_path=None,
        same_domain_only="true",
        crawl_depth="0",
        summary_path=None,      # kept for backward-compat, not used in-process
        stop_flag=None,         # threading.Event — set it to pause the spider
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        if not seed_url or not seed_url.startswith(("http://", "https://")):
            raise ValueError("seed_url must start with http:// or https://")

        self.seed_url        = self.normalize_url(seed_url)
        self.start_urls      = [self.seed_url]
        self.output_dir      = output_dir or "backend/data/raw"
        self.max_pages       = int(max_pages)
        self.allowed_path    = allowed_path or None
        self.same_domain_only = str(same_domain_only).lower() == "true"
        self.crawl_depth     = int(crawl_depth) if crawl_depth else 0
        self.summary_path    = Path(summary_path) if summary_path else None

        # stop_flag may arrive as a threading.Event (in-process) or as the
        # string "None" / "" (legacy subprocess path — treat as no flag).
        if isinstance(stop_flag, threading.Event):
            self.stop_flag: Optional[threading.Event] = stop_flag
        else:
            self.stop_flag = None

        self.seed_domain     = urlparse(self.seed_url).netloc
        self.allowed_domains = [urlparse(self.seed_url).hostname] if self.same_domain_only else []

        # Stats
        self.pages_crawled = 0
        self.pages_saved   = 0
        self.failed_urls: list = []
        self.stopped_early = False   # True when paused via stop_flag (user)
        self.stalled       = False   # True when aborted by the stall watchdog

        # Heartbeat for the stall watchdog (see backend/crawler/crawler.py).
        # Updated on every response received (success or failure) so an
        # external watchdog thread can detect "no activity for N seconds"
        # and forcibly abort a hung crawl instead of blocking forever.
        self.last_activity = time.time()

        if self.crawl_depth:
            self.custom_settings = {"DEPTH_LIMIT": self.crawl_depth}

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        crawler.signals.connect(spider.on_spider_error,  signal=signals.spider_error)
        crawler.signals.connect(spider.on_spider_closed, signal=signals.spider_closed)
        return spider

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def normalize_url(url: str) -> str:
        url, _ = urldefrag(url)
        return url[:-1] if url.endswith("/") and len(urlparse(url).path) > 1 else url

    def start_requests(self):
        yield scrapy.Request(
            self.seed_url, callback=self.parse, errback=self.on_request_error
        )

    def is_followable(self, url: str) -> bool:
        parsed = urlparse(url)
        return (
            parsed.scheme in {"http", "https"}
            and (not self.same_domain_only or parsed.netloc == self.seed_domain)
            and (not self.allowed_path or parsed.path.startswith(self.allowed_path))
            and Path(parsed.path).suffix.lower() not in BAD_EXTENSIONS
        )

    # ------------------------------------------------------------------
    # Core parse — checks stop_flag after every page
    # ------------------------------------------------------------------

    def parse(self, response):
        self.last_activity = time.time()   # heartbeat for stall watchdog
        self.pages_crawled += 1

        page = self.extract_page(response.url, response.text)
        if page:
            self.pages_saved += 1
            yield CrawledPageItem(**page)

        # ---- PAUSE CHECK ------------------------------------------------
        # Check the stop_flag right after yielding the page item.
        # This is the earliest safe point: the item has been handed to the
        # pipeline so it will be saved even if we stop now.
        if self.stop_flag is not None and self.stop_flag.is_set():
            self.stopped_early = True
            self.logger.info(
                "Stop flag detected after page %d — closing spider now.",
                self.pages_crawled,
            )
            raise CloseSpider("pause_requested")
        # -----------------------------------------------------------------

        if self.pages_crawled >= self.max_pages:
            raise CloseSpider("max_pages_reached")

        for href in response.css("a::attr(href)").getall():
            url = self.normalize_url(urljoin(response.url, href))
            if self.is_followable(url):
                yield response.follow(
                    url, callback=self.parse, errback=self.on_request_error
                )

    # ------------------------------------------------------------------
    # Error / closed callbacks
    # ------------------------------------------------------------------

    def on_request_error(self, failure):
        self.last_activity = time.time()   # heartbeat for stall watchdog
        url = failure.request.url
        if url not in self.failed_urls:
            self.failed_urls.append(url)
        self.logger.warning("Request failed for %s: %s", url, failure.value)

    def on_spider_error(self, failure, response, spider):
        self.logger.exception("Parsing failed for %s", response.url)

    def on_spider_closed(self, spider, reason):
        # Write summary file for any legacy/subprocess callers still using it.
        if self.summary_path:
            self.summary_path.write_text(
                json.dumps({
                    "pages_crawled": self.pages_crawled,
                    "pages_saved":   self.pages_saved,
                    "failed_urls":   self.failed_urls,
                    "stopped_early": self.stopped_early,
                }),
                encoding="utf-8",
            )
        self.logger.info(
            "Crawl finished: crawled=%d saved=%d stopped_early=%s reason=%s",
            self.pages_crawled, self.pages_saved, self.stopped_early, reason,
        )

    # ------------------------------------------------------------------
    # Page extraction (unchanged)
    # ------------------------------------------------------------------

    @staticmethod
    def extract_page(url: str, html: str):
        soup = BeautifulSoup(html, "lxml")
        title = soup.title.get_text(strip=True) if soup.title else url

        for selector in NOISE_SELECTORS:
            for node in soup.select(selector):
                node.decompose()

        main = (
            next(
                (node for selector in CONTENT_SELECTORS if (node := soup.select_one(selector))),
                None,
            )
            or soup.body
            or soup
        )

        chunks, headings = [], []
        for element in main.find_all({"h1", "h2", "h3", "h4", "h5", "h6", "p", "pre", "code", "li"}):
            text = element.get_text(" ", strip=True)
            if not text:
                continue
            if element.name.startswith("h"):
                headings.append(text)
                chunks.append(f"\n## {text}\n")
            elif element.name == "pre":
                chunks.append(f"\n```\n{element.get_text(strip=False).strip()}\n```\n")
            elif element.name == "code" and element.parent and element.parent.name != "pre":
                chunks.append(f"`{text}`")
            elif element.name == "li":
                chunks.append(f"- {text}")
            else:
                chunks.append(text)

        text = re.sub(r"\n{3,}", "\n\n", "\n".join(chunks)).strip()
        return {"url": url, "title": title, "text": text, "headings": headings} if len(text) >= 80 else None