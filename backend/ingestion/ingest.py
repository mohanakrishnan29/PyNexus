"""Ingestion pipeline: raw JSON -> chunks -> embeddings -> FAISS index.

Incremental ingestion
---------------------
On a fresh build every raw JSON file is embedded and indexed from scratch.

On a resume-triggered re-ingest (i.e. after crawling only the remaining
sources) we use a hash ledger stored at ``<index_dir>/doc_hashes.json``.
Each entry maps a raw filename to the SHA-256 of its content.  Files whose
hash has not changed since the last index build are skipped; only new or
modified files are embedded and merged into the existing index.

The ledger is written atomically after every successful build so a crashed
mid-ingest never leaves a stale ledger behind.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS

try:
    from langchain_huggingface import HuggingFaceEmbeddings
except ImportError:  # pragma: no cover
    try:
        from langchain.embeddings import HuggingFaceEmbeddings
    except ImportError:  # pragma: no cover
        from sentence_transformers import SentenceTransformer
        import numpy as np

        class HuggingFaceEmbeddings:
            def __init__(
                self, model_name: str, encode_kwargs: Optional[dict] = None
            ) -> None:
                self.model_name = model_name
                self.encode_kwargs = encode_kwargs or {}
                self.model = SentenceTransformer(model_name)

            def embed_documents(self, texts: List[str]) -> List[List[float]]:
                normalize = self.encode_kwargs.get("normalize_embeddings", True)
                vectors = self.model.encode(
                    texts, convert_to_numpy=True, show_progress_bar=False
                )
                if normalize:
                    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
                    norms[norms == 0] = 1.0
                    vectors = vectors / norms
                return [list(map(float, vec)) for vec in vectors]

from backend.chunking.semantic_chunker import SemanticChunker

from backend.utils.config import settings
from backend.utils.logger import get_logger

logger = get_logger("PyNexus.ingest")

LEDGER_FILENAME = "doc_hashes.json"


@dataclass
class IngestResult:
    documents_loaded: int
    chunks_indexed: int
    index_dir: str
    skipped_unchanged: int = 0


_embeddings_singleton: Optional[HuggingFaceEmbeddings] = None


def get_embeddings() -> HuggingFaceEmbeddings:
    global _embeddings_singleton
    if _embeddings_singleton is None:
        logger.info("Loading embedding model: %s", settings.embedding_model)
        _embeddings_singleton = HuggingFaceEmbeddings(
            model_name=settings.embedding_model,
            encode_kwargs={"normalize_embeddings": True},
        )
    return _embeddings_singleton


def _file_hash(path: Path) -> str:
    """Return the SHA-256 hex digest of a file's raw bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Ingestor:
    """Reads crawled JSON files and writes (or merges into) a FAISS index."""

    def __init__(
        self,
        raw_dir: Optional[Path] = None,
        index_dir: Optional[Path] = None,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
    ) -> None:
        self.raw_dir = raw_dir or settings.raw_dir
        self.index_dir = index_dir or settings.index_dir
        self.chunk_size = chunk_size or settings.chunk_size
        self.chunk_overlap = chunk_overlap or settings.chunk_overlap
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.splitter = SemanticChunker(max_chars=self.chunk_size * 4)

    # ------------------------------------------------------------------ ledger

    def _ledger_path(self) -> Path:
        return self.index_dir / LEDGER_FILENAME

    def _load_ledger(self) -> Dict[str, str]:
        """Return saved {filename: sha256} map, or {} if none exists."""
        p = self._ledger_path()
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Could not read hash ledger: %s", exc)
            return {}

    def _save_ledger(self, ledger: Dict[str, str]) -> None:
        tmp = self._ledger_path().with_suffix(".tmp")
        tmp.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
        tmp.replace(self._ledger_path())

    # ------------------------------------------------------------------ load

    def _load_raw_documents(
        self, only_new: bool = False
    ) -> Tuple[List[Document], Dict[str, str], int]:
        """
        Load raw JSON files as LangChain Documents.

        Parameters
        ----------
        only_new : bool
            If True, skip files whose hash matches the saved ledger
            (incremental mode used on resume).

        Returns
        -------
        docs            : documents to embed
        new_ledger      : updated {filename: hash} map for all files seen
        skipped_count   : number of files skipped as unchanged
        """
        saved_ledger = self._load_ledger() if only_new else {}
        new_ledger: Dict[str, str] = dict(saved_ledger)  # start with old, update below

        docs: List[Document] = []
        skipped = 0
        files = sorted(self.raw_dir.glob("*.json"))

        if not files:
            logger.warning("No raw documents found in %s", self.raw_dir)
            return docs, new_ledger, skipped

        for file in files:
            current_hash = _file_hash(file)
            new_ledger[file.name] = current_hash

            if only_new and saved_ledger.get(file.name) == current_hash:
                skipped += 1
                continue

            try:
                payload = json.loads(file.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                logger.warning("Skipping corrupt JSON %s: %s", file.name, exc)
                continue

            text = (payload.get("text") or "").strip()
            if not text:
                continue

            docs.append(
                Document(
                    page_content=text,
                    metadata={
                        "source": payload.get("url", ""),
                        "title": payload.get("title", ""),
                        "file": file.name,
                    },
                )
            )

        logger.info(
            "Loaded %d raw documents (%d skipped as unchanged) from %s",
            len(docs),
            skipped,
            self.raw_dir,
        )
        return docs, new_ledger, skipped

    # ----------------------------------------------------------------- chunk

    def _chunk(self, docs: List[Document]) -> List[Document]:
        chunks = self.splitter.split_documents(docs)
        logger.info(
            "Split into %d chunks (size=%d, overlap=%d)",
            len(chunks),
            self.chunk_size,
            self.chunk_overlap,
        )
        return chunks

    # ----------------------------------------------------------------- embed

    def _embed_chunks(self, chunks: List[Document]) -> Tuple[List[str], List[List[float]], List[dict]]:
        embeddings = get_embeddings()
        texts = [c.page_content for c in chunks]
        metadatas = [c.metadata for c in chunks]
        vectors: List[List[float]] = []
        batch_size = settings.embedding_batch_size
        for start in range(0, len(texts), batch_size):
            batch = texts[start: start + batch_size]
            batch_vectors = embeddings.embed_documents(batch)
            vectors.extend(batch_vectors)
            logger.info(
                "Embedded batch %d-%d / %d",
                start + 1,
                min(start + batch_size, len(texts)),
                len(texts),
            )
        return texts, vectors, metadatas

    # ----------------------------------------------------------------- store

    def build_index(self) -> IngestResult:
        """Full rebuild — embeds every raw document, replaces the index."""
        docs, new_ledger, skipped = self._load_raw_documents(only_new=False)
        if not docs:
            raise RuntimeError(
                "No crawled documents to ingest. Run /crawl first or place "
                f"JSON files in {self.raw_dir}."
            )

        chunks = self._chunk(docs)
        if not chunks:
            raise RuntimeError("Chunking produced no documents. Adjust chunk settings.")

        logger.info("Building FAISS index over %d chunks ...", len(chunks))
        texts, vectors, metadatas = self._embed_chunks(chunks)

        store = FAISS.from_embeddings(
            list(zip(texts, vectors)),
            get_embeddings(),
            metadatas=metadatas,
        )
        store.save_local(str(self.index_dir))
        self._save_ledger(new_ledger)
        logger.info("FAISS index saved to %s", self.index_dir)

        return IngestResult(
            documents_loaded=len(docs),
            chunks_indexed=len(chunks),
            index_dir=str(self.index_dir),
            skipped_unchanged=0,
        )

    def incremental_update(self) -> IngestResult:
        """
        Merge only new/changed documents into the existing FAISS index.

        Used after a resume completes newly crawled sources so we don't
        re-embed the entire corpus — only the files that changed.
        Falls back to a full build if no existing index is found.
        """
        index_faiss = self.index_dir / "index.faiss"
        if not index_faiss.exists():
            logger.info("No existing index found — falling back to full build.")
            return self.build_index()

        docs, new_ledger, skipped = self._load_raw_documents(only_new=True)

        if not docs:
            logger.info("No new/changed documents — index is already up to date.")
            return IngestResult(
                documents_loaded=0,
                chunks_indexed=0,
                index_dir=str(self.index_dir),
                skipped_unchanged=skipped,
            )

        chunks = self._chunk(docs)
        if not chunks:
            return IngestResult(
                documents_loaded=len(docs),
                chunks_indexed=0,
                index_dir=str(self.index_dir),
                skipped_unchanged=skipped,
            )

        logger.info(
            "Incremental update: embedding %d new chunks (%d files skipped) ...",
            len(chunks),
            skipped,
        )
        texts, vectors, metadatas = self._embed_chunks(chunks)

        # Load and merge into the existing store.
        existing_store = FAISS.load_local(
            str(self.index_dir),
            get_embeddings(),
            allow_dangerous_deserialization=True,
        )
        new_store = FAISS.from_embeddings(
            list(zip(texts, vectors)),
            get_embeddings(),
            metadatas=metadatas,
        )
        existing_store.merge_from(new_store)
        existing_store.save_local(str(self.index_dir))
        self._save_ledger(new_ledger)
        logger.info("Incremental FAISS update saved to %s", self.index_dir)

        return IngestResult(
            documents_loaded=len(docs),
            chunks_indexed=len(chunks),
            index_dir=str(self.index_dir),
            skipped_unchanged=skipped,
        )


def load_vectorstore() -> Optional[FAISS]:
    """Load a previously built FAISS index from disk, if present."""
    index_path = settings.index_dir
    if not (index_path / "index.faiss").exists():
        return None
    embeddings = get_embeddings()
    return FAISS.load_local(
        str(index_path),
        embeddings,
        allow_dangerous_deserialization=True,
    )