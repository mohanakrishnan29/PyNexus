from backend.scrapy_project.pipelines import raw_filename
from backend.scrapy_project.spiders.documentation import DocumentationSpider


def test_scrapy_extraction_preserves_ingestion_schema():
    html = """<html><head><title>Example</title></head><body><nav>ignore</nav><main>
    <h1>Heading</h1><p>This is meaningful documentation content with enough characters to be saved by the crawler.</p>
    <pre>print('hello')</pre></main></body></html>"""
    page = DocumentationSpider.extract_page("https://example.test/docs", html)
    assert set(page) == {"url", "title", "text", "headings"}
    assert page["title"] == "Example"
    assert page["headings"] == ["Heading"]
    assert "ignore" not in page["text"]
    assert "```" in page["text"]


def test_scrapy_url_filter_and_legacy_filename():
    spider = DocumentationSpider(seed_url="https://example.test/docs/", allowed_path="/docs")
    assert spider.is_followable("https://example.test/docs/page")
    assert not spider.is_followable("https://example.test/other")
    assert not spider.is_followable("https://other.test/docs/page")
    assert not spider.is_followable("https://example.test/docs/file.pdf")
    assert raw_filename("https://example.test/docs/page") == raw_filename("https://example.test/docs/page")
