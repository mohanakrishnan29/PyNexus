from langchain_core.documents import Document

from backend.chunking.semantic_chunker import SemanticChunker
from backend.extractor.document_cleaner import DocumentCleaner
from backend.services.context_processor import ContextProcessor
from backend.services.markdown_validator import validate_markdown


def test_semantic_chunks_keep_heading_metadata_and_fenced_code():
    doc = Document(
        page_content="# Lists\n\nLists are mutable ordered collections.\n\n## Example\n\n```python\nitems = [1, 2]\n```",
        metadata={"title": "Lists", "source": "https://example.test/lists"},
    )
    chunks = SemanticChunker(max_chars=500).split_documents([doc])
    assert len(chunks) == 2
    assert chunks[1].metadata["section"] == "Lists > Example"
    assert "```python" in chunks[1].page_content


def test_context_never_returns_duplicate_chunks_and_validator_closes_fence():
    docs = [Document(page_content="Useful documentation.", metadata={"title": "Guide"})] * 2
    assert ContextProcessor().build(docs).count("Useful documentation.") == 1
    assert validate_markdown("```python\nprint(1)").endswith("```")


def test_cleaner_keeps_code_whitespace():
    text = "Text   \n\n```python\n  print('exact')  \n```"
    assert "  print('exact')  " in DocumentCleaner().clean(text)
