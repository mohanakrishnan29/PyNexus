from __future__ import annotations

import re

# A model occasionally emits a fenced block for a Python keyword or identifier.
# These are prose-level inline-code values, not implementation examples.
_SHORT_INLINE_FENCE = re.compile(
    r"(?m)^(?:```(?:code)?[ \t]*\n)([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*(?:\(\))?)[ \t]*\n```$"
)


def validate_markdown(markdown: str) -> str:
    """Repair unsafe fences and normalize accidental one-token code blocks."""
    text = (markdown or "").strip()
    if text.count("```") % 2:
        text += "\n```"
    text = _SHORT_INLINE_FENCE.sub(lambda match: f"`{match.group(1)}`", text)
    return re.sub(r"\n{3,}", "\n\n", text)