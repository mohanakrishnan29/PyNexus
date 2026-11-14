"""Backward-compatible RAG pipeline using the shared LLM provider interface."""
from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document

from backend.ingestion.ingest import load_vectorstore
from backend.services.llm_service import get_llm_service
from backend.utils.config import settings
from backend.utils.logger import get_logger

logger = get_logger("PyNexus.rag")

SYSTEM_PROMPT = """You are PyNexus, an expert Python programming assistant.
Answer only from the supplied documentation context. Return clear Markdown,
with code fenced as Python when relevant."""


@dataclass
class SourceRef:
    title: str
    url: str
    snippet: str


@dataclass
class QueryResponse:
    answer: str
    sources: List[SourceRef] = field(default_factory=list)
    used_provider: str = "gemini"


class RAGPipeline:
    def __init__(self) -> None:
        self._vs: Optional[FAISS] = None

    def reload(self) -> None:
        self._vs = load_vectorstore()

    def _ensure_loaded(self) -> FAISS:
        if self._vs is None:
            self.reload()
        if self._vs is None:
            raise RuntimeError("Vector index not built yet. Call /crawl then /ingest first.")
        return self._vs

    def retrieve(self, query: str, k: Optional[int] = None) -> List[Document]:
        return self._ensure_loaded().similarity_search(query, k=k or settings.top_k)

    @staticmethod
    def _build_context(docs: List[Document]) -> str:
        return "\n\n---\n\n".join(
            f"[Doc {index}] {doc.metadata.get('title', '')}\n{doc.page_content}"
            for index, doc in enumerate(docs, start=1)
        )

    @staticmethod
    def _format_answer(question: str, answer: str, sources: Optional[List[str]] = None) -> str:
        """Retained for compatibility with callers of the original pipeline."""
        source_block = "\n".join(f"- {source}" for source in (sources or [])[:5])
        return (
            "## Answer\n"
            f"{answer.strip()}\n\n"
            "## Example\n"
            f"If you want a quick example for {question.strip()}, use the relevant retrieved documentation.\n\n"
            "## Sources\n"
            f"{source_block or '- No specific sources cited.'}"
        )

    def query(self, question: str, k: Optional[int] = None, history: Optional[List[Dict[str, str]]] = None) -> QueryResponse:
        question = (question or "").strip()
        if not question:
            raise ValueError("question must be a non-empty string")
        docs = self.retrieve(question, k=k)
        context = self._build_context(docs)
        if not context:
            raise RuntimeError("No usable documentation was found for that question.")

        llm = get_llm_service()
        answer = llm.generate(
            system_prompt=f"{SYSTEM_PROMPT}\n\nDocumentation Context:\n{context}",
            user_prompt=question,
            history=history,
        )
        sources = [
            SourceRef(
                title=doc.metadata.get("title", ""),
                url=doc.metadata.get("source", ""),
                snippet=textwrap.shorten(doc.page_content.strip().replace("\n", " "), width=240, placeholder=" ..."),
            )
            for doc in docs
        ]
        return QueryResponse(answer=answer, sources=sources, used_provider=llm.provider_name)


pipeline = RAGPipeline()