"""Pre-configured Python documentation sources for PyNexus.

Edit the PYTHON_SOURCES list below to add, remove, or tune the sites
that get crawled when the user clicks "Initialize Knowledge Base".
Each DocSource is crawled independently; set enabled=False to skip one
without deleting it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class DocSource:
    name: str
    description: str
    seed_url: str
    enabled: bool = True


# ---------------------------------------------------------------------------
# Modify this list to change which Python docs are indexed.
# ---------------------------------------------------------------------------
PYTHON_SOURCES: List[DocSource] = [
   DocSource(
        name="W3Schools Python",
        description="Beginner-friendly Python tutorials with live try-it examples",
        seed_url="https://www.w3schools.com/python/",
    ),
    DocSource(
        name="Python Official Docs",
        description="The official Python 3 documentation",
        seed_url="https://docs.python.org/3/",
    ),
]