from __future__ import annotations

from langchain_core.documents import Document


class ContextProcessor:
    def __init__(self, max_chars: int = 12_000) -> None:
        self.max_chars = max_chars

    def build(self, documents: list[Document]) -> str:
        seen, blocks, size = set(), [], 0
        for doc in documents:
            content = doc.page_content.strip()
            key = " ".join(content.split()).lower()
            if not content or key in seen:
                continue
            block = f"## {doc.metadata.get('section') or doc.metadata.get('title') or 'Documentation'}\n{content}"
            if size + len(block) > self.max_chars:
                break
            seen.add(key)
            blocks.append(block)
            size += len(block)
        return "\n\n---\n\n".join(blocks)
