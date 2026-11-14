from __future__ import annotations

import re
import unicodedata


class DocumentCleaner:
    """Conservative Markdown cleanup that never alters fenced code."""

    def clean(self, markdown: str) -> str:
        markdown = unicodedata.normalize("NFC", markdown or "").replace("\r\n", "\n")
        parts = re.split(r"(```[\s\S]*?```)", markdown)
        seen, cleaned = set(), []
        for index, part in enumerate(parts):
            if index % 2:
                cleaned.append(part.strip())
                continue
            part = re.sub(r"[ \t]+\n", "\n", part)
            part = re.sub(r"\n{3,}", "\n\n", part).strip()
            if part and part not in seen:
                seen.add(part)
                cleaned.append(part)
        return "\n\n".join(part for part in cleaned if part).strip()
