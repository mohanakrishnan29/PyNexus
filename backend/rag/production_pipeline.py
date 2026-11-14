"""Production retrieval-to-LLM pipeline.

The retrieval stack is provider-agnostic: it prepares context and calls the
configured response-generation service through a common interface.
"""
from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from langchain_core.documents import Document

from backend.ingestion.ingest import load_vectorstore
from backend.services.context_processor import ContextProcessor
from backend.services.llm_service import get_llm_service
from backend.services.markdown_validator import validate_markdown
from backend.utils.config import settings

SYSTEM_PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "system_prompt.txt").read_text(encoding="utf-8")


@dataclass
class SourceRef:
    title: str
    url: str
    snippet: str = ""


@dataclass
class QueryResponse:
    answer: str
    sources: List[SourceRef] = field(default_factory=list)
    used_provider: str = "gemini"


class RAGPipeline:
    def __init__(self) -> None:
        self._vs = None
        self.context_processor = ContextProcessor()

    def reload(self) -> None:
        self._vs = load_vectorstore()

    def _ensure_loaded(self):
        if self._vs is None:
            self.reload()
        if self._vs is None:
            raise RuntimeError("Knowledge base is not ready. Crawl and ingest documentation first.")
        return self._vs

    def retrieve(self, query: str, k: Optional[int] = None) -> List[Document]:
        return self._ensure_loaded().similarity_search(query.strip(), k=k or settings.top_k)

    @staticmethod
    def _system_prompt(context: str) -> str:
        return (
            f"{SYSTEM_PROMPT}\n\n"
            "Use the documentation context below as the sole source of facts. "
            "Return only the polished Markdown answer for the user.\n\n"
            f"Documentation context:\n{context}"
        )

    def query(
        self,
        question: str,
        k: Optional[int] = None,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> QueryResponse:
        question = (question or "").strip()
        if not question:
            raise ValueError("question must be a non-empty string")

        docs = self.retrieve(question, k)
        context = self.context_processor.build(docs)
        if not context:
            raise RuntimeError("No usable documentation was found for that question.")

        llm = get_llm_service()
        answer = validate_markdown(
            llm.generate(
                system_prompt=self._system_prompt(context),
                user_prompt=question,
                history=history,
            )
        )

        sources, seen = [], set()
        for doc in docs:
            url = doc.metadata.get("source", "")
            if url and url not in seen:
                seen.add(url)
                sources.append(SourceRef(doc.metadata.get("title") or url, url))
        return QueryResponse(answer=answer, sources=sources, used_provider=llm.provider_name)


pipeline = RAGPipeline()