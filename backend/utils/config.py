"""Centralized configuration loaded from environment variables.

Keeping settings in one place makes the rest of the codebase easy to
reason about and lets us swap providers (LLM / embedding model) without
touching call-sites.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _abs(path_str: str) -> Path:
    """Resolve a path relative to backend/ if it is not already absolute."""
    p = Path(path_str)
    return p if p.is_absolute() else (BACKEND_DIR / p)


def _csv_env(key: str, default: str) -> List[str]:
    raw = os.getenv(key, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass
class Settings:
    # LLM
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "gemini").strip().lower())
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip())
    # Embeddings
    embedding_model: str = field(
        default_factory=lambda: os.getenv(
            "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
        )
    )

    embedding_batch_size: int = field(
        default_factory=lambda: int(os.getenv("EMBEDDING_BATCH_SIZE", "32"))
    )

    # Crawler
    crawler_max_pages: int = field(
        default_factory=lambda: int(os.getenv("CRAWLER_MAX_PAGES", "5000"))
    )
    crawler_request_timeout: int = field(
        default_factory=lambda: int(os.getenv("CRAWLER_REQUEST_TIMEOUT", "15"))
    )
    crawler_user_agent: str = field(
        default_factory=lambda: os.getenv(
            "CRAWLER_USER_AGENT", "PyNexusBot/1.0 (+https://localhost)"
        )
    )

    crawler_depth_limit: int = field(default_factory=lambda: int(os.getenv("CRAWLER_DEPTH_LIMIT", "0")))
    crawler_download_delay: float = field(default_factory=lambda: float(os.getenv("CRAWLER_DOWNLOAD_DELAY", "0.2")))
    crawler_retry_times: int = field(default_factory=lambda: int(os.getenv("CRAWLER_RETRY_TIMES", "2")))
    crawler_autothrottle_max_delay: float = field(default_factory=lambda: float(os.getenv("CRAWLER_AUTOTHROTTLE_MAX_DELAY", "10")))
    crawler_concurrent_requests_per_domain: int = field(default_factory=lambda: int(os.getenv("CRAWLER_CONCURRENT_REQUESTS_PER_DOMAIN", "2")))


    # RAG
    chunk_size: int = field(default_factory=lambda: int(os.getenv("CHUNK_SIZE", "500")))
    chunk_overlap: int = field(default_factory=lambda: int(os.getenv("CHUNK_OVERLAP", "80")))
    top_k: int = field(default_factory=lambda: int(os.getenv("TOP_K", "5")))

    # Storage
    data_dir: Path = field(default_factory=lambda: _abs(os.getenv("DATA_DIR", "data")))
    raw_dir: Path = field(default_factory=lambda: _abs(os.getenv("RAW_DIR", "data/raw")))
    index_dir: Path = field(default_factory=lambda: _abs(os.getenv("INDEX_DIR", "db/faiss_index")))

    # API
    api_host: str = field(default_factory=lambda: os.getenv("API_HOST", "0.0.0.0"))
    api_port: int = field(default_factory=lambda: int(os.getenv("API_PORT", "8000")))
    cors_origins: List[str] = field(
        default_factory=lambda: _csv_env(
            "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
        )
    )

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.raw_dir, self.index_dir):
            d.mkdir(parents=True, exist_ok=True)

    def validate_llm(self) -> None:
        """Raise a safe, actionable error for an incomplete LLM configuration."""
        if not self.llm_provider:
            raise RuntimeError("LLM_PROVIDER must be configured (for example, 'gemini').")
        if self.llm_provider != "gemini":
            raise RuntimeError(
                f"Unsupported LLM_PROVIDER '{self.llm_provider}'. Available providers: gemini."
            )
        if not self.gemini_api_key.strip():
            raise RuntimeError("GEMINI_API_KEY must be configured when LLM_PROVIDER=gemini.")
        if not self.gemini_model:
            raise RuntimeError("GEMINI_MODEL must name a Gemini model (for example, 'gemini-2.5-flash').")


settings = Settings()
settings.ensure_dirs()




