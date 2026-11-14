"""PyNexus FastAPI application.

Endpoints:
  POST /initialize      - crawl all pre-configured Python sources + build index
  POST /pause           - pause immediately (current page finishes, then stops)
  POST /resume          - resume a paused crawl from where it left off
  GET  /init-status     - poll initialization progress
  POST /crawl           - crawl a custom URL
  POST /ingest          - (re)build the FAISS index from raw data
  POST /query           - RAG query with optional conversation history
  GET  /health          - health probe + index status
  GET  /stats           - stats about crawled pages and index
  GET  /sources         - list configured Python doc sources

Pause/Resume design
-------------------
A single ``threading.Event`` called ``_stop_flag`` is created fresh for every
crawl run and passed into the Crawler (and from there into the spider).  The
spider checks ``stop_flag.is_set()`` after saving each page.  When /pause sets
the flag the spider stops within one page-fetch round-trip â€” typically a few
seconds, not hours.

On resume a new _stop_flag is created (cleared) so the next run proceeds
normally.  The manifest on disk tracks which sources finished so resume always
continues from the right place.
"""
from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, HttpUrl

from backend.crawler import Crawler
from backend.ingestion import Ingestor
from backend.python_sources import PYTHON_SOURCES
from backend.rag.production_pipeline import pipeline
from backend.utils.config import settings
from backend.utils.logger import get_logger

logger = get_logger("PyNexus.api")

app = FastAPI(
    title="PyNexus",
    version="1.0.0",
    description="RAG-based developer documentation assistant.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Manifest â€” persists progress across process restarts
# ---------------------------------------------------------------------------
MANIFEST_PATH: Path = settings.raw_dir.parent / "crawl_jobs" / "manifest.json"
MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
# Unlike the run manifest, this file is deliberately kept after a successful
# run.  It lets us tell a source that was indexed last week from one that was
# just added to python_sources.py today.
SOURCE_STATUS_PATH: Path = MANIFEST_PATH.parent / "source_status.json"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CrawlRequest(BaseModel):
    seed_url: HttpUrl = Field(..., description="Where the crawler should start.")
    allowed_path: Optional[str] = Field(None)
    max_pages: Optional[int] = Field(None, ge=1, le=5000)
    same_domain_only: bool = Field(True)
    crawl_depth: Optional[int] = Field(None, ge=0)
    delay_seconds: Optional[float] = Field(None, ge=0)


class CrawlResponse(BaseModel):
    seed_url: str
    pages_crawled: int
    pages_saved: int
    output_dir: str
    failed_urls: List[str]


class IngestResponse(BaseModel):
    documents_loaded: int
    chunks_indexed: int
    index_dir: str


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: Optional[int] = Field(None, ge=1, le=20)
    history: Optional[List[Dict[str, str]]] = Field(None)


class SourceRefSchema(BaseModel):
    title: str
    url: str
    snippet: str


class QueryResponseSchema(BaseModel):
    answer: str
    sources: List[SourceRefSchema]
    used_provider: str


class HealthResponse(BaseModel):
    status: str
    index_loaded: bool
    llm_provider: str
    embedding_model: str


# ---------------------------------------------------------------------------
# Global crawl state
# ---------------------------------------------------------------------------

_init_lock = threading.Lock()

# _stop_flag is created fresh per run (cleared = run freely).
# /pause sets it; the spider checks it after every page.
_stop_flag: threading.Event = threading.Event()   # starts cleared = run freely
# We also keep a "resume gate" so the worker thread can be told to start.
_resume_gate: threading.Event = threading.Event()
_resume_gate.set()

_init_state: Dict[str, Any] = {
    "running":  False,
    "paused":   False,
    "done":     False,
    "error":    None,
    "sources":  [],
    "total":    0,
    "completed": 0,
}


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------

def _save_manifest() -> None:
    """Persist _init_state to disk. Must be called under _init_lock."""
    try:
        MANIFEST_PATH.write_text(
            json.dumps(_init_state, indent=2, default=str), encoding="utf-8"
        )
    except Exception as exc:
        logger.warning("Could not save manifest: %s", exc)


def _load_manifest() -> Optional[Dict[str, Any]]:
    if not MANIFEST_PATH.exists():
        return None
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not read manifest: %s", exc)
        return None


def _source_key(source) -> str:
    """Stable source identity; renaming a source does not cause a re-crawl."""
    return source.seed_url.rstrip("/").lower()


def _source_entry(source, status: str = "pending", pages_crawled: int = 0) -> Dict[str, Any]:
    return {
        "name": source.name,
        "description": source.description,
        "seed_url": source.seed_url,
        "status": status,
        "pages_crawled": pages_crawled,
    }


def _load_source_status() -> Dict[str, Dict[str, Any]]:
    """Load the durable record of sources which completed successfully."""
    if not SOURCE_STATUS_PATH.exists():
        return {}
    try:
        payload = json.loads(SOURCE_STATUS_PATH.read_text(encoding="utf-8"))
        records = payload.get("sources", [])
        return {
            str(record.get("seed_url", "")).rstrip("/").lower(): record
            for record in records
            if record.get("status") == "done" and record.get("seed_url")
        }
    except Exception as exc:
        logger.warning("Could not read source status ledger: %s", exc)
        return {}


def _save_source_status(sources: List[Dict[str, Any]]) -> None:
    """Persist completed sources without retaining transient run state."""
    # Preserve completions for disabled sources too, so re-enabling one does
    # not unexpectedly make it pending again.
    completed_by_key = _load_source_status()
    for source in sources:
        if source.get("status") == "done" and source.get("seed_url"):
            completed_by_key[str(source["seed_url"]).rstrip("/").lower()] = source
    try:
        tmp = SOURCE_STATUS_PATH.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"sources": list(completed_by_key.values())}, indent=2),
            encoding="utf-8",
        )
        tmp.replace(SOURCE_STATUS_PATH)
    except Exception as exc:
        logger.warning("Could not save source status ledger: %s", exc)


def _source_has_indexed_content(source) -> bool:
    """Best-effort migration for installations created before the ledger.

    Older PyNexus versions discarded completion state after a successful run.
    If an existing FAISS index contains raw pages under a configured source's
    URL prefix, carry that source forward as completed once rather than asking
    the user to crawl it again.
    """
    if not (settings.index_dir / "index.faiss").exists():
        return False
    seed = source.seed_url.rstrip("/") + "/"
    try:
        for raw_file in settings.raw_dir.glob("*.json"):
            payload = json.loads(raw_file.read_text(encoding="utf-8"))
            if str(payload.get("url", "")).startswith(seed):
                return True
    except Exception as exc:
        logger.warning("Could not inspect existing raw documents for source migration: %s", exc)
    return False


def _build_source_list(enabled_sources, saved_sources: Optional[Dict[str, Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Reconcile configured sources with completed-source history."""
    saved_sources = saved_sources if saved_sources is not None else _load_source_status()
    merged = []
    migrated = False
    for source in enabled_sources:
        saved = saved_sources.get(_source_key(source))
        if saved:
            merged.append(_source_entry(source, "done", saved.get("pages_crawled", 0)))
        elif not saved_sources and _source_has_indexed_content(source):
            merged.append(_source_entry(source, "done"))
            migrated = True
        else:
            merged.append(_source_entry(source))

    if migrated:
        _save_source_status(merged)
    return merged


def _merge_with_manifest(enabled_sources, manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Keep completed sources done; leave newly configured sources pending."""
    durable_sources = _load_source_status()
    manifest_by_key = {
        str(s.get("seed_url", "")).rstrip("/").lower(): s
        for s in manifest.get("sources", [])
        if s.get("seed_url")
    }
    # Compatibility with manifests created before seed_url was stored.
    manifest_by_name = {s.get("name"): s for s in manifest.get("sources", [])}
    merged = []
    migrated = False
    for s in enabled_sources:
        saved = durable_sources.get(_source_key(s)) or manifest_by_key.get(_source_key(s)) or manifest_by_name.get(s.name)
        if saved and saved.get("status") == "done":
            merged.append(_source_entry(s, "done", saved.get("pages_crawled", 0)))
        elif not durable_sources and _source_has_indexed_content(s):
            merged.append(_source_entry(s, "done"))
            migrated = True
        else:
            merged.append(_source_entry(s))
    if migrated:
        _save_source_status(merged)
    return merged


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

def _run_initialize(is_resume: bool = False) -> None:
    """
    Background thread: crawls all pending sources then builds the FAISS index.

    The key difference from the old approach:
    - A fresh _stop_flag (threading.Event) is used per run.
    - It is passed into each Crawler() call.
    - The spider checks it after EVERY page â€” pause latency is now
      one HTTP round-trip (~milliseconds to seconds), not one source (~hours).
    - When the flag fires mid-source, that source is marked 'paused' in the
      manifest and will restart from page 1 on resume (safe because filenames
      are URL-hash-stable, so re-crawling just overwrites the same files).
    """
    global _stop_flag

    enabled = [s for s in PYTHON_SOURCES if s.enabled]

    with _init_lock:
        _init_state["running"] = True
        _init_state["paused"]  = False
        _init_state["done"]    = False
        _init_state["error"]   = None
        _save_manifest()

    try:
        for idx, source in enumerate(enabled):
            with _init_lock:
                src_status = _init_state["sources"][idx]["status"]

            # Skip already-finished sources (resume path).
            if src_status == "done":
                logger.info("Skipping already-done source: %s", source.name)
                continue

            with _init_lock:
                _init_state["sources"][idx]["status"] = "running"
                _save_manifest()

            try:
                # Confine this crawl to the seed URL's own path prefix.
                # Without this, sources sharing a domain (e.g. many
                # docs.python.org sections) would wander into each other's
                # already-crawled territory â€” same_domain_only alone doesn't
                # prevent that. Re-visiting an already-saved URL just
                # overwrites its file (stable URL-hash filenames), so the
                # symptom was "counters climbing but raw folder count frozen".
                #
                # Example: seed https://docs.python.org/3/library/  ->
                # allowed_path="/3/library/", so it can't stray into
                # /3/tutorial/ (already covered by another source).
                seed_path = urlparse(source.seed_url).path or "/"

                result = Crawler(
                    seed_url=source.seed_url,
                    allowed_path=seed_path,
                    same_domain_only=True,
                    stop_flag=_stop_flag,   # â† injected here
                ).run()

                if result.stopped_early:
                    # User-requested pause (via /pause) mid-source.
                    # Mark as pending so resume re-crawls it from the start
                    # (safe â€” URL-hash filenames mean no duplicates).
                    with _init_lock:
                        _init_state["sources"][idx]["status"] = "pending"
                        _init_state["sources"][idx]["pages_crawled"] = result.pages_saved
                        _init_state["running"] = False
                        _init_state["paused"]  = True
                        _save_manifest()
                    logger.info(
                        "Paused mid-source '%s' after %d pages.",
                        source.name, result.pages_saved,
                    )
                    return  # Exit worker â€” resume will spawn a new thread

                if result.stalled:
                    # Watchdog force-aborted this source due to a network-level
                    # hang (no activity for stall_timeout seconds). This is
                    # NOT a user pause â€” mark it 'failed' (visible in the UI)
                    # and move on to the next source. Since it's not marked
                    # 'done', a future /initialize or /resume will retry it
                    # automatically (safe â€” URL-hash filenames dedupe).
                    with _init_lock:
                        _init_state["sources"][idx]["status"] = "failed"
                        _init_state["sources"][idx]["pages_crawled"] = result.pages_saved
                        _init_state["sources"][idx]["error"] = (
                            "Stalled â€” no crawl activity detected (possible network "
                            "hang or stale connection). Will retry on next run."
                        )
                        _save_manifest()
                    logger.warning(
                        "Source '%s' stalled after %d pages â€” marked failed, continuing.",
                        source.name, result.pages_saved,
                    )
                    continue  # Move on to the next source in this same run

                # Source completed normally.
                with _init_lock:
                    _init_state["sources"][idx]["status"]       = "done"
                    _init_state["sources"][idx]["pages_crawled"] = result.pages_saved
                    _init_state["completed"] += 1
                    _save_source_status(_init_state["sources"])
                    _save_manifest()

            except Exception as exc:
                logger.exception("Source crawl failed: %s", source.name)
                with _init_lock:
                    _init_state["sources"][idx]["status"] = "failed"
                    _init_state["sources"][idx]["error"]  = str(exc)
                    _save_manifest()

        # Only pending sources are crawled.  Merge their documents into the
        # existing index so already indexed sources are never re-embedded.
        logger.info("Pending sources finished. Updating FAISS index.")
        Ingestor().incremental_update()
        pipeline.reload()

        with _init_lock:
            _init_state["done"]   = all(source["status"] == "done" for source in _init_state["sources"])
            _init_state["paused"] = False
            if _init_state["done"]:
                MANIFEST_PATH.unlink(missing_ok=True)   # run state is no longer needed
            else:
                _save_manifest()

    except Exception as exc:
        logger.exception("Initialization failed")
        with _init_lock:
            _init_state["error"] = str(exc)
            _save_manifest()
    finally:
        with _init_lock:
            _init_state["running"] = False


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def _startup() -> None:
    settings.ensure_dirs()
    try:
        settings.validate_llm()
    except RuntimeError as exc:
        # Keep crawler/index endpoints available, while /query returns this
        # actionable error until the environment is corrected.
        logger.error("LLM configuration error: %s", exc)
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Reconcile the durable source ledger on every startup.  A source added to
    # python_sources.py therefore appears immediately as pending in the UI.
    manifest = _load_manifest()
    enabled = [s for s in PYTHON_SOURCES if s.enabled]
    restored = (
        _merge_with_manifest(enabled, manifest)
        if manifest and not manifest.get("done")
        else _build_source_list(enabled)
    )
    completed = sum(1 for source in restored if source["status"] == "done")
    has_incomplete = any(source["status"] != "done" for source in restored)
    with _init_lock:
        _init_state.update({
            "running":   False,
            "paused":    bool(manifest and manifest.get("paused") and has_incomplete),
            "done":      bool(restored) and not has_incomplete,
            "error":     None,
            "sources":   restored,
            "total":     len(enabled),
            "completed": completed,
        })
    logger.info("Loaded source status: %d/%d sources complete.", completed, len(enabled))

    try:
        pipeline.reload()
    except Exception as exc:
        logger.info("No existing index at startup: %s", exc)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        index_loaded=pipeline._vs is not None,
        llm_provider=settings.llm_provider,
        embedding_model=settings.embedding_model,
    )


@app.get("/stats")
async def stats() -> dict:
    raw_count    = len(list(settings.raw_dir.glob("*.json")))
    index_exists = (settings.index_dir / "index.faiss").exists()
    return {
        "raw_documents": raw_count,
        "raw_dir":       str(settings.raw_dir),
        "index_exists":  index_exists,
        "index_dir":     str(settings.index_dir),
        "index_loaded":  pipeline._vs is not None,
    }


@app.get("/sources")
async def get_sources() -> dict:
    return {
        "sources": [
            {"name": s.name, "description": s.description, "seed_url": s.seed_url, "enabled": s.enabled}
            for s in PYTHON_SOURCES
        ]
    }


@app.post("/initialize")
async def initialize() -> dict:
    """Crawl only configured sources that have not completed yet."""
    global _stop_flag

    with _init_lock:
        if _init_state["running"]:
            return {"started": False, "message": "Initialization already in progress."}

    enabled = [s for s in PYTHON_SOURCES if s.enabled]

    with _init_lock:
        sources = _build_source_list(enabled)
        completed = sum(1 for source in sources if source["status"] == "done")
        if completed == len(sources):
            _init_state.update({
                "running": False,
                "paused": False,
                "done": bool(sources),
                "error": None,
                "completed": completed,
                "total": len(enabled),
                "sources": sources,
            })
            return {"started": False, "message": "All configured sources are already indexed."}

        # Fresh stop_flag â€” cleared so the spider runs freely.
        _stop_flag = threading.Event()
        _init_state.update({
            "running":   False,
            "paused":    False,
            "done":      False,
            "error":     None,
            "completed": completed,
            "total":     len(enabled),
            "sources":   sources,
        })

    thread = threading.Thread(target=_run_initialize, kwargs={"is_resume": False}, daemon=True)
    thread.start()
    return {"started": True, "message": "Initialization started. Poll /init-status for progress."}


@app.post("/pause")
async def pause_crawl() -> dict:
    """
    Pause the crawl immediately.

    Sets the stop_flag that the spider checks after every page.
    Pause takes effect within one HTTP round-trip (seconds), not after
    the current source finishes (which could be hours).
    """
    with _init_lock:
        if not _init_state["running"]:
            return {"paused": False, "message": "No crawl is currently running."}
        if _init_state.get("paused"):
            return {"paused": False, "message": "Crawl is already paused."}

    # Set the flag â€” the spider will see this on its next page check.
    _stop_flag.set()

    logger.info("Pause flag set â€” spider will stop after current page.")
    return {
        "paused": True,
        "message": "Pause signal sent. Crawl will stop within seconds (current page will finish).",
    }


@app.post("/resume")
async def resume_crawl() -> dict:
    """Resume a paused crawl from where it left off."""
    global _stop_flag

    with _init_lock:
        if _init_state["running"]:
            return {"resumed": False, "message": "Crawl is already running."}

    enabled = [s for s in PYTHON_SOURCES if s.enabled]

    with _init_lock:
        current_sources = _init_state.get("sources") or []

    if not current_sources:
        manifest = _load_manifest()
        if manifest:
            current_sources = manifest.get("sources", [])

    if not current_sources:
        return {
            "resumed": False,
            "message": "No paused state found. Use /initialize to start fresh.",
        }

    merged    = _merge_with_manifest(enabled, {"sources": current_sources})
    completed = sum(1 for s in merged if s["status"] == "done")

    # Fresh stop_flag â€” cleared so the resumed spider runs freely.
    _stop_flag = threading.Event()

    with _init_lock:
        _init_state.update({
            "sources":   merged,
            "total":     len(enabled),
            "completed": completed,
            "paused":    False,
            "done":      False,
            "error":     None,
        })
        _save_manifest()

    thread = threading.Thread(target=_run_initialize, kwargs={"is_resume": True}, daemon=True)
    thread.start()
    return {
        "resumed": True,
        "message": f"Resuming from source {completed + 1} of {len(enabled)}.",
    }


@app.get("/init-status")
async def init_status() -> dict:
    with _init_lock:
        return dict(_init_state)


@app.post("/crawl", response_model=CrawlResponse)
async def crawl(req: CrawlRequest) -> CrawlResponse:
    crawler = Crawler(
        seed_url=str(req.seed_url),
        allowed_path=req.allowed_path,
        max_pages=req.max_pages,
        same_domain_only=req.same_domain_only,
        crawl_depth=req.crawl_depth,
        delay_seconds=req.delay_seconds,
        # No stop_flag â€” manual crawl runs to completion.
    )
    try:
        result = await asyncio.to_thread(crawler.run)
    except Exception as exc:
        logger.exception("Crawl failed")
        raise HTTPException(status_code=500, detail=f"Crawl failed: {exc}") from exc
    return CrawlResponse(
        seed_url=result.seed_url,
        pages_crawled=result.pages_crawled,
        pages_saved=result.pages_saved,
        output_dir=result.output_dir,
        failed_urls=result.failed_urls,
    )


@app.post("/ingest", response_model=IngestResponse)
async def ingest() -> IngestResponse:
    ingestor = Ingestor()
    try:
        result = await asyncio.to_thread(ingestor.build_index)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Ingest failed")
        raise HTTPException(status_code=500, detail=f"Ingest failed: {exc}") from exc
    pipeline.reload()
    return IngestResponse(**asdict(result))


@app.post("/query", response_model=QueryResponseSchema)
async def query(req: QueryRequest) -> QueryResponseSchema:
    try:
        result = await asyncio.to_thread(pipeline.query, req.query, req.top_k, req.history)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Query failed")
        raise HTTPException(status_code=500, detail=f"Query failed: {exc}") from exc

    return QueryResponseSchema(
        answer=result.answer,
        sources=[SourceRefSchema(**asdict(s)) for s in result.sources],
        used_provider=result.used_provider,
    )


if __name__ == "__main__":  # pragma: no cover
    import uvicorn
    uvicorn.run("backend.main:app", host=settings.api_host, port=settings.api_port, reload=False)
