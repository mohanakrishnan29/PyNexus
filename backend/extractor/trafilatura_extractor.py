"""Extract useful documentation from a Playwright-rendered DOM."""
from __future__ import annotations

from bs4 import BeautifulSoup

from backend.extractor.document_cleaner import DocumentCleaner

NOISE = "script,style,noscript,svg,iframe,form,nav,footer,header,aside,[role=navigation],[role=banner],[role=contentinfo],.sidebar,.navbar,.cookie,.advertisement,.ads"


class DocumentationExtractor:
    def __init__(self) -> None:
        self.cleaner = DocumentCleaner()

    def extract(self, url: str, html: str) -> dict | None:
        title = url
        try:
            import trafilatura
            markdown = trafilatura.extract(
                html, output_format="markdown", include_tables=True,
                include_links=False, include_comments=False,
            )
        except ImportError:
            markdown = None
        soup = BeautifulSoup(html, "lxml")
        if soup.title:
            title = soup.title.get_text(" ", strip=True)
        # Trafilatura is primary; DOM conversion covers pages it cannot classify.
        text = self.cleaner.clean(markdown or self._dom_markdown(soup))
        if len(text) < 80:
            return None
        headings = [h.get_text(" ", strip=True) for h in soup.select("h1,h2,h3,h4,h5,h6")]
        return {"url": url, "title": title, "text": text, "headings": headings}

    @staticmethod
    def _dom_markdown(soup: BeautifulSoup) -> str:
        for node in soup.select(NOISE):
            node.decompose()
        main = soup.select_one("main,article,[role=main],#main,#content,.main-content,.doc-content,.markdown-body") or soup.body or soup
        out = []
        for el in main.select("h1,h2,h3,h4,h5,h6,p,li,pre,table"):
            value = el.get_text("\n" if el.name == "pre" else " ", strip=True)
            if not value:
                continue
            if el.name.startswith("h"):
                out.append("%s %s" % ("#" * int(el.name[1]), value))
            elif el.name == "pre":
                out.append(f"```\n{value}\n```")
            elif el.name == "li":
                out.append(f"- {value}")
            else:
                out.append(value)
        return "\n\n".join(out)
