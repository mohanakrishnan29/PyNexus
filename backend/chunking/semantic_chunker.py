"""Heading-aware chunks that keep code fences and document hierarchy intact."""
from __future__ import annotations

import re
from typing import List

from langchain_core.documents import Document

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


class SemanticChunker:
    def __init__(self, max_chars: int = 1800) -> None:
        self.max_chars = max_chars

    def split_documents(self, documents: List[Document]) -> List[Document]:
        chunks: List[Document] = []
        for document in documents:
            hierarchy, buffer = [], []
            for block in self._blocks(document.page_content):
                match = HEADING.match(block)
                if match:
                    chunks.extend(self._flush(document, hierarchy, buffer))
                    level, heading = len(match.group(1)), match.group(2)
                    hierarchy = hierarchy[: level - 1] + [heading]
                    buffer = [block]
                elif sum(len(x) + 2 for x in buffer) + len(block) > self.max_chars and buffer:
                    chunks.extend(self._flush(document, hierarchy, buffer))
                    buffer = [block]
                else:
                    buffer.append(block)
            chunks.extend(self._flush(document, hierarchy, buffer))
        return chunks

    @staticmethod
    def _blocks(text: str) -> List[str]:
        return [item.strip() for item in re.split(r"\n\s*\n", text) if item.strip()]

    @staticmethod
    def _flush(document: Document, hierarchy: List[str], blocks: List[str]) -> List[Document]:
        if not blocks:
            return []
        content = "\n\n".join(blocks).strip()
        if len(content) < 40:
            return []
        metadata = dict(document.metadata)
        metadata.update({"section": " > ".join(hierarchy), "heading_hierarchy": hierarchy})
        return [Document(page_content=content, metadata=metadata)]
