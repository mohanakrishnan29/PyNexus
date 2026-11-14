import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.rag.pipeline import RAGPipeline


def test_format_answer_structure():
    formatted = RAGPipeline._format_answer(
        "How do I read a CSV in Python?",
        "Use the csv module or pandas.read_csv for larger datasets.",
        ["csv module", "pandas.read_csv"],
    )

    assert "Answer" in formatted
    assert "Example" in formatted
    assert "Sources" in formatted
