"""In-process Scrapy crawler with page-level pause support.

Switches from subprocess to CrawlerRunner so a threading.Event (stop_flag)
can be injected directly into the running spider.  The spider checks the flag
after every page save and calls engine.close_spider() immediately when set,
making /pause respond within seconds rather than waiting for a full source
to finish (which could take hours).

Twisted reactor lifecycle
-------------------------
Scrapy's CrawlerRunner requires the Twisted reactor to be running.  We start
it once in a daemon thread for the entire process lifetime.  All subsequent
crawl jobs are submitted via reactor.callFromThread() and awaited with a
threading.Event so the calling (FastAPI worker) thread blocks cleanly.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from backend.utils.config import settings
from backend.utils.logger import get_logger

logger = get_logger("PyNexus.crawler")

# ---------------------------------------------------------------------------
# Twisted / Scrapy imports — deferred to avoid import-time side-effects
# ---------------------------------------------------------------------------
# We import these at module level because FastAPI imports this module on
# startup; the imports themselves are safe, only reactor.run() has side-effects.
from twisted.internet import reactor                                                    # noqa: E402
from scrapy.crawler import CrawlerRunner                                                # noqa: E402
from scrapy.utils.project import get_project_settings                                   # noqa: E402
from scrapy import signals as scrapy_signals                                             # noqa: E402
from backend.scrapy_project.spiders.documentation import DocumentationSpider            # noqa: E402

# ---------------------------------------------------------------------------
# Reactor thread — started once, lives for the process lifetime
# ---------------------------------------------------------------------------
_reactor_started = threading.Event()
_reactor_lock    = threading.Lock()
_reactor_thread: Optional[threading.Thread] = None


def _ensure_reactor() -> None:
    """Start the Twisted reactor in a background daemon thread if needed."""
    global _reactor_thread
    with _reactor_lock:
        if _reactor_thread is not None and _reactor_thread.is_alive():
            return

        def _run_reactor():
            _reactor_started.set()
            reactor.run(installSignalHandlers=False)

        _reactor_thread = threading.Thread(
            target=_run_reactor, daemon=True, name="twisted-reactor"
        )
        _reactor_thread.start()

    # Wait until reactor.run() has actually entered its loop.
    _reactor_started.wait(timeout=5)
    time.sleep(0.05)   # small extra margin for the loop to be ready


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class CrawlResult:
    seed_url: str
    pages_crawled: int
    pages_saved: int
    output_dir: str
    failed_urls: List[str] = field(default_factory=list)
    stopped_early: bool = False   # True when the spider was stopped by stop_flag (user pause)
    stalled: bool = False         # True when the stall watchdog force-aborted the crawl


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------

class Crawler:
    """Run the DocumentationSpider in-process with optional pause support.

    Parameters
    ----------
    stop_flag : threading.Event, optional
        Pass a *cleared* Event (i.e. ``threading.Event()`` with no ``.set()``
        called yet).  When the caller calls ``stop_flag.set()`` the spider
        will finish the page it is currently saving and then shut down — this
        typically takes only a few seconds, not hours.

        If None, the spider runs to natural completion (max_pages or no more
        links).

    stall_timeout : float, optional
        Seconds of zero crawl activity (no response received, success or
        failure) after which a background watchdog forcibly aborts the crawl.
        Guards against rare hangs where a request neither completes nor times
        out at the network layer (e.g. a stale reused connection).  Defaults
        to 180 seconds.  Set to None to disable the watchdog entirely.
    """

    def __init__(
        self,
        seed_url: str,
        allowed_path: Optional[str] = None,
        max_pages: Optional[int] = None,
        same_domain_only: bool = True,
        delay_seconds: Optional[float] = None,
        crawl_depth: Optional[int] = None,
        output_dir: Optional[Path] = None,
        stop_flag: Optional[threading.Event] = None,
        stall_timeout: Optional[float] = 180.0,
    ) -> None:
        if not seed_url.startswith(("http://", "https://")):
            raise ValueError("seed_url must start with http:// or https://")
        self.seed_url        = seed_url
        self.allowed_path    = allowed_path
        self.max_pages       = max_pages if max_pages is not None else settings.crawler_max_pages
        self.same_domain_only = same_domain_only
        self.delay_seconds   = delay_seconds if delay_seconds is not None else settings.crawler_download_delay
        self.crawl_depth     = crawl_depth if crawl_depth is not None else settings.crawler_depth_limit
        self.output_dir      = Path(output_dir) if output_dir is not None else settings.raw_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.stop_flag       = stop_flag
        self.stall_timeout   = stall_timeout

    # ------------------------------------------------------------------

    def run(self) -> CrawlResult:
        """Block the calling thread until the crawl finishes or is paused."""
        _ensure_reactor()

        # Per-run result storage — written by the spider's closed signal.
        result_holder: List[Optional[CrawlResult]] = [None]
        done_event = threading.Event()

        # Load Scrapy settings from the project module, then override per-crawl.
        scrapy_settings = get_project_settings()
        scrapy_settings.setmodule("backend.scrapy_project.settings", priority="project")
        scrapy_settings.set("DOWNLOAD_DELAY", self.delay_seconds, priority="cmdline")
        scrapy_settings.set("DEPTH_LIMIT",    self.crawl_depth,   priority="cmdline")

        # Scrapy 2.7+ defaults TWISTED_REACTOR to AsyncioSelectorReactor and
        # verifies the installed reactor matches on every CrawlerRunner init.
        # We installed the plain (non-asyncio) reactor above, so disable that
        # check — it's only a compatibility guard, not required for crawling.
        scrapy_settings.set("TWISTED_REACTOR", None, priority="cmdline")

        runner = CrawlerRunner(scrapy_settings)

        # Spider kwargs — stop_flag is passed as a Python object, not a string,
        # because from_crawler calls __init__ directly in in-process mode.
        spider_kwargs = dict(
            seed_url        = self.seed_url,
            output_dir      = str(self.output_dir),
            max_pages       = str(self.max_pages),
            same_domain_only= str(self.same_domain_only).lower(),
            allowed_path    = self.allowed_path or "",
            stop_flag       = self.stop_flag,   # threading.Event or None
        )

        def _spider_opened(spider):
            """Capture the live spider instance so we can read its attrs later."""
            result_holder.append(spider)   # index 1 = live spider

        def _crawl_ok(_ignored):
            done_event.set()

        def _crawl_failed(failure):
            # Surface the real error instead of silently swallowing it —
            # this is what was hidden behind "Spider did not open" before.
            logger.error(
                "Crawl failed for %s:\n%s",
                self.seed_url,
                failure.getTraceback(),
            )
            done_event.set()

        crawl_obj_holder: List[object] = []
        stall_state = {"stalled": False}

        def _schedule_on_reactor():
            """Submitted to the reactor thread via callFromThread."""
            try:
                # Create a Scrapy Crawler object so we can connect signals
                # BEFORE the crawl starts — avoids the race where
                # spider_opened fires before we've connected to it.
                crawl_obj = runner.create_crawler(DocumentationSpider)
                crawl_obj_holder.append(crawl_obj)
                crawl_obj.signals.connect(_spider_opened, signal=scrapy_signals.spider_opened)

                # Track it on the runner's own bookkeeping set (harmless,
                # keeps runner.stop()/join() consistent if ever used elsewhere).
                runner.crawlers.add(crawl_obj)

                d = crawl_obj.crawl(**spider_kwargs)
                d.addCallbacks(_crawl_ok, _crawl_failed)
            except Exception:
                logger.exception("Failed to schedule crawl for %s", self.seed_url)
                done_event.set()

        reactor.callFromThread(_schedule_on_reactor)

        # -------------------------------------------------------------
        # Stall watchdog: runs on its own thread, independent of the
        # reactor.  If the spider goes quiet (no response received —
        # success or failure — for stall_timeout seconds), forcibly stop
        # the crawl instead of blocking done_event.wait() forever.
        # -------------------------------------------------------------
        def _watchdog():
            logger.info(
                "[WATCHDOG] Thread started for %s | stall_timeout=%s",
                self.seed_url, self.stall_timeout,
            )
            if not self.stall_timeout:
                logger.info("[WATCHDOG] stall_timeout falsy — watchdog disabled, exiting.")
                return
            check_interval = min(10.0, self.stall_timeout / 3)
            started_at = time.time()
            loop_count = 0
            while not done_event.wait(timeout=check_interval):
                loop_count += 1
                spider = result_holder[1] if len(result_holder) > 1 else None
                if spider is None:
                    elapsed = time.time() - started_at
                    logger.info(
                        "[WATCHDOG] check #%d: spider not yet captured (elapsed=%.0fs)",
                        loop_count, elapsed,
                    )
                    if elapsed >= self.stall_timeout:
                        logger.warning(
                            "Stall watchdog: spider never opened within %.0fs for %s — aborting.",
                            self.stall_timeout, self.seed_url,
                        )
                        stall_state["stalled"] = True
                        if crawl_obj_holder:
                            reactor.callFromThread(crawl_obj_holder[0].stop)
                        return
                    continue
                idle = time.time() - getattr(spider, "last_activity", time.time())
                logger.info(
                    "[WATCHDOG] check #%d: idle=%.0fs / threshold=%.0fs | pages_crawled=%s pages_saved=%s",
                    loop_count, idle, self.stall_timeout,
                    getattr(spider, "pages_crawled", "?"), getattr(spider, "pages_saved", "?"),
                )
                if idle >= self.stall_timeout:
                    logger.warning(
                        "Stall watchdog: no activity for %.0fs on %s — aborting crawl.",
                        idle, self.seed_url,
                    )
                    stall_state["stalled"] = True
                    if crawl_obj_holder:
                        reactor.callFromThread(crawl_obj_holder[0].stop)
                    return
            logger.info("[WATCHDOG] Exiting loop — done_event was set (crawl finished normally).")

        def _watchdog_safe():
            try:
                _watchdog()
            except Exception:
                logger.exception("[WATCHDOG] Crashed with an unhandled exception!")

        watchdog_thread = threading.Thread(target=_watchdog_safe, daemon=True, name="crawl-watchdog")
        watchdog_thread.start()
        logger.info("[WATCHDOG] threading.Thread.start() called, is_alive=%s", watchdog_thread.is_alive())

        # Block until Scrapy is done (naturally, via stop_flag, or via watchdog).
        done_event.wait()

        # Read results from the spider instance captured above.
        spider = result_holder[1] if len(result_holder) > 1 else None

        if spider is not None:
            return CrawlResult(
                seed_url     = self.seed_url,
                pages_crawled= getattr(spider, "pages_crawled", 0),
                pages_saved  = getattr(spider, "pages_saved",   0),
                output_dir   = str(self.output_dir),
                failed_urls  = list(getattr(spider, "failed_urls", [])),
                stopped_early= getattr(spider, "stopped_early",  False),
                stalled      = stall_state["stalled"],
            )

        # Spider never opened — likely a settings/import error, or the
        # watchdog fired before spider_opened ever signaled (extremely rare).
        logger.error("Spider did not open for %s — check Scrapy settings.", self.seed_url)
        return CrawlResult(
            seed_url     = self.seed_url,
            pages_crawled= 0,
            pages_saved  = 0,
            output_dir   = str(self.output_dir),
            stopped_early= False,
            stalled      = stall_state["stalled"],
        )