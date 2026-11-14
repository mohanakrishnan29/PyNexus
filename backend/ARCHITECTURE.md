# Production documentation pipeline

```text
URL discovery and robots rules
  -> Playwright rendered DOM
  -> Trafilatura extraction (DOM fallback)
  -> Markdown cleaning
  -> heading-aware semantic chunks
  -> embeddings -> FAISS
  -> FAISS top-K -> context processor
  -> Google Gemini API -> Markdown validation -> React Markdown
```

`backend/crawler/playwright_crawler.py` is the active crawler exposed by
`backend.crawler.Crawler`. It renders JavaScript, opens `details`, attempts
common “load more” controls, scrolls lazy content, filters internal URLs, and
respects `robots.txt`. Crawled JSON holds cleaned documentation only.

At runtime, FAISS is only used to select chunks. `production_pipeline.py`
passes de-duplicated context through a provider-neutral LLM interface and
returns only the validated Markdown response. Gemini-specific SDK calls stay
in `backend/services/gemini_service.py`. The API source list deliberately
contains titles and URLs, never a raw chunk/snippet.

## Local setup

```powershell
pip install -r requirements.txt
playwright install chromium
```

Set `LLM_PROVIDER=gemini`, provide `GEMINI_API_KEY`, and optionally choose a
Gemini model with `GEMINI_MODEL` (default: `gemini-2.5-flash`).