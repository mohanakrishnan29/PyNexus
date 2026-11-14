# PyNexus

PyNexus is a local-first Python documentation assistant. It crawls documentation pages, turns the extracted text into embeddings, stores them in a local FAISS vector index, and uses retrieval-augmented generation (RAG) to answer questions with source links.

This repository is designed to be a self-contained local AI assistant for Python documentation. The backend handles crawling, indexing, retrieval, and answer generation. The frontend provides a chat interface and knowledge-base controls. The project is intentionally local-first: it can run without paid LLM access by using retrieved excerpts as the fallback answer mode, and it can optionally use OpenAI or Gemini when configured.

The README below is written so that it can be exported to external AI tools such as Claude for deeper project understanding and future development support.

---

## 1. What this project is

PyNexus is a small but complete RAG application for Python documentation. It combines:

- a web crawler that collects documentation pages,
- an ingestion pipeline that chunks and embeds the text,
- a local vector store powered by FAISS,
- a retrieval and answer pipeline,
- and a React-based frontend for interacting with the knowledge base.

The system is meant to answer questions like:

- “What is a Python list comprehension?”
- “How does async/await work in Python?”
- “What is the difference between a list and a tuple?”

The answer is grounded in retrieved documentation snippets rather than a fully generative local model.

---

## 2. High-level architecture

```text
User (browser) -> React frontend -> FastAPI backend -> crawler / ingestor / RAG pipeline
                                              |
                                              +-> raw JSON files in backend/data/raw
                                              +-> FAISS index in backend/db/faiss_index
```

### Runtime responsibilities

- Frontend: owns chat UI, conversation state, sidebar state, and browser-local persistence.
- Backend: owns indexing state, crawling, embedding, retrieval, and API endpoints.
- Local filesystem: stores crawled docs and the in-memory/on-disk vector index.
- Background worker thread: runs initialization jobs and keeps the API responsive.

---

## 3. End-to-end flow

### A. Knowledge-base initialization

1. The user clicks “Initialize knowledge base” in the sidebar.
2. The frontend calls the FastAPI endpoint `/initialize`.
3. The backend starts a background thread and runs the configured documentation source crawls.
4. Each crawl writes page-level JSON files into `backend/data/raw/`.
5. After crawling, the ingestor reads all raw JSON, splits text into chunks, embeds the chunks, and rebuilds the FAISS index.
6. The RAG pipeline reloads the vector store so queries can use the new index.

### B. A user asks a question

1. The React app sends the query to `/query`.
2. The backend retrieves the most relevant chunks from FAISS.
3. The RAG pipeline chooses a provider:
   - local fallback: returns extracted snippets from the retrieved context;
   - OpenAI: uses the retrieved context and recent history to synthesize an answer;
   - Gemini: uses the retrieved context and recent history if configured.
4. The backend returns the answer plus source references and snippets.
5. The frontend renders the answer as Markdown and shows expandable source links.

### C. How the data moves

```text
HTML docs -> Scrapy crawler -> JSON docs -> chunker -> embeddings -> FAISS -> query -> answer
```

---

## 4. Project structure

```text
PyNexus/
├── backend/
│   ├── __init__.py
│   ├── main.py
│   ├── python_sources.py
│   ├── sitecustomize.py
│   ├── crawler/
│   │   └── crawler.py
│   ├── scrapy_project/
│   │   ├── __init__.py
│   │   ├── items.py
│   │   ├── pipelines.py
│   │   ├── settings.py
│   │   └── spiders/
│   │       └── documentation.py
│   ├── ingestion/
│   │   └── ingest.py
│   ├── rag/
│   │   └── pipeline.py
│   ├── utils/
│   │   ├── config.py
│   │   └── logger.py
│   ├── data/
│   │   ├── raw/
│   │   └── crawl_jobs/
│   ├── db/
│   │   └── faiss_index/
│   └── tests/
│       ├── test_rag_format.py
│       └── test_scrapy_crawler.py
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   ├── postcss.config.js
│   ├── tailwind.config.js
│   └── src/
│       ├── api.js
│       ├── App.jsx
│       ├── index.css
│       ├── main.jsx
│       └── components/
│           ├── ChatUI.jsx
│           ├── KBPanel.jsx
│           └── Sidebar.jsx
├── requirements.txt
├── env.example
├── gitignore.txt
└── README.md
```

---

## 5. What each backend Python file does

### Top-level backend files

- `backend/main.py`
  - The main FastAPI application.
  - Defines the API routes: `/health`, `/stats`, `/sources`, `/initialize`, `/init-status`, `/crawl`, `/ingest`, and `/query`.
  - Holds the initialization state for the background crawl/build job.
  - Runs blocking work in threads so the FastAPI event loop stays responsive.

- `backend/python_sources.py`
  - Defines the built-in documentation source registry.
  - Each `DocSource` contains a name, description, seed URL, and enabled flag.
  - The initialization endpoint uses this list to decide what to crawl.

- `backend/sitecustomize.py`
  - Ensures the repository root is importable when the backend is launched from inside the `backend/` directory.
  - A small startup helper for Python path setup.

### Crawling layer

- `backend/crawler/crawler.py`
  - Compatibility wrapper around the Scrapy-based crawler.
  - Accepts crawl settings, invokes Scrapy as a subprocess, and returns a structured result.
  - This keeps the FastAPI API contract stable while using Scrapy underneath.

- `backend/scrapy_project/items.py`
  - Defines the `CrawledPageItem` schema used by the spider.
  - Contains the fields `url`, `title`, `text`, and `headings`.

- `backend/scrapy_project/pipelines.py`
  - Writes scraped pages to JSON files in the raw data directory.
  - Generates stable filenames using the original URL and a hash suffix.

- `backend/scrapy_project/settings.py`
  - Centralized Scrapy settings like retries, delays, concurrency, logging, and the item pipeline.

- `backend/scrapy_project/spiders/documentation.py`
  - The actual Scrapy spider implementation.
  - Visits documentation pages, extracts readable content, filters out navigation and boilerplate, and yields items for persistence.
  - It also collects summary stats such as pages crawled and pages saved.

### Ingestion layer

- `backend/ingestion/ingest.py`
  - Reads all raw JSON files from `backend/data/raw/`.
  - Ignores invalid JSON and empty content.
  - Splits documents into overlapping text chunks.
  - Loads or creates the embedding model.
  - Embeds the chunks and builds a FAISS index on disk.

### RAG layer

- `backend/rag/pipeline.py`
  - Implements the retrieval and answering flow.
  - Loads the FAISS vector store from disk.
  - Retrieves top-k documents for a query.
  - Chooses a provider for answer generation: local fallback, OpenAI, or Gemini.
  - Formats the answer and sources for the UI.

### Utilities

- `backend/utils/config.py`
  - Loads configuration from environment variables and `.env`.
  - Resolves backend-relative paths for raw data and the FAISS index.
  - Centralizes settings for the crawler, chunking, API host/port, and model providers.

- `backend/utils/logger.py`
  - Creates a consistent logging setup for the backend.
  - Ensures logs are emitted to stdout with a predictable format.

### Tests

- `backend/tests/test_rag_format.py`
  - Verifies that the response formatting logic produces the expected structure.

- `backend/tests/test_scrapy_crawler.py`
  - Verifies that the crawler extracts readable page content and that URL filtering behaves as expected.

---

## 6. What each frontend file does

- `frontend/src/App.jsx`
  - Main React application shell.
  - Manages conversations, active conversation selection, health polling, and initialization polling.
  - Persists conversation history to browser `localStorage`.

- `frontend/src/api.js`
  - Centralizes all API calls to the FastAPI backend.
  - Exposes helpers for health checks, initialization, crawling, ingestion, and querying.

- `frontend/src/main.jsx`
  - Entry point that mounts the React app into the browser.

- `frontend/src/index.css`
  - Main styling layer for the dark chat UI, message bubbles, source lists, and responsive layouts.

- `frontend/src/components/Sidebar.jsx`
  - Displays the conversation list and knowledge-base panel.
  - Starts initialization and shows build progress.

- `frontend/src/components/ChatUI.jsx`
  - Main chat experience.
  - Sends user messages, renders Markdown responses, shows sources, and handles the input area.

- `frontend/src/components/KBPanel.jsx`
  - Modal-like progress panel showing source-level indexing status.

---

## 7. How the project works technically

### Backend flow

1. The backend reads environment settings from `.env` and `backend/utils/config.py`.
2. The FastAPI app starts and tries to load an existing FAISS index if one already exists.
3. The initialize route kicks off a background crawl/build job.
4. The crawler writes raw JSON pages.
5. The ingestor incrementally adds only new or changed pages to the vector index.
6. The RAG pipeline retrieves relevant chunks and generates an answer.

### Frontend flow

1. The frontend loads the app and checks backend health.
2. It polls initialization status while indexing is running.
3. The user enters a question and sends it to the backend.
4. The response is rendered with Markdown and source links.
5. Conversations are stored locally in the browser so the app feels like a chat assistant without requiring a user account system.

---

## 8. Tech stack and role of each tool

| Area | Technology | Role in this application |
| --- | --- | --- |
| Backend language | Python 3.10–3.12 | Core runtime for the API, crawler, embeddings, and RAG pipeline |
| Web API | FastAPI + Uvicorn + Pydantic | Serves the API, validates requests, and exposes interactive docs |
| Crawling | Scrapy + BeautifulSoup + lxml | Discovers and extracts documentation content from HTML |
| Embeddings | Sentence-Transformers | Converts chunks and queries into dense vectors |
| Vector search | FAISS | Stores embeddings and performs similarity search |
| RAG framework | LangChain | Wraps document objects, chunking, retrieval, and vector-store integration |
| Response generation | Google Gemini API | Generates Markdown answers from retrieved documentation context |
| Frontend | React + Vite | Client-side chat UI and knowledge-base controls |
| Styling | Tailwind CSS + custom CSS | Dark-mode chat layout and responsive UI |
| HTTP client | Axios | Browser-side requests to the backend |
| Markdown rendering | react-markdown + remark-gfm | Converts backend answers into rich Markdown UI |
| Configuration | python-dotenv | Loads environment variables from `.env` |

### Why these technologies were chosen

- FastAPI is lightweight and well-suited for local API development.
- Scrapy is appropriate because the application needs a robust crawler with link discovery and request management.
- FAISS provides fast local vector similarity search without needing a remote database.
- Sentence-Transformers is a practical local embedding solution for a small self-hosted app.
- React/Vite provide a fast and simple chat UI experience.

---

## 9. Data artifacts and persistence model

PyNexus stores data in the local filesystem rather than a database.

- `backend/data/raw/`: stores raw crawled JSON documents.
- `backend/db/faiss_index/`: stores the FAISS vector index files.
- Browser localStorage: stores conversation history locally in the browser.

Important detail: the raw directory is cumulative. Rebuilding the index does not automatically delete old documents. If you want a clean corpus, you must remove old raw JSON and index files manually.

---

## 10. Configuration and environment variables

Copy `env.example` to `.env` at the repository root before running the app.

Key variables:

- `LLM_PROVIDER`: `gemini` (the configured response-generation provider)
- `GEMINI_API_KEY`: required Gemini API key; keep it only in `.env`
- `GEMINI_MODEL`: Gemini model name (defaults to `gemini-2.5-flash`)
- `EMBEDDING_MODEL`: embedding model to use
- `CHUNK_SIZE`: chunk length for splitting docs
- `CHUNK_OVERLAP`: overlap between adjacent chunks
- `TOP_K`: number of retrieved chunks per query
- `RAW_DIR`: raw crawl storage path
- `INDEX_DIR`: FAISS index storage path
- `API_HOST` / `API_PORT`: API bind address and port
- `CORS_ORIGINS`: allowed frontend origins

---

## 11. Local setup

### Backend

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item env.example .env
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

macOS/Linux:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp env.example .env
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Then open `http://localhost:5173`.

---

## 12. Extending the project

### Add more documentation sources

Edit `backend/python_sources.py` and add or enable more `DocSource` entries.

After restarting the backend, the Knowledge Base panel keeps existing completed
sources marked as `done` and shows each newly added source as `pending` (for
example, `1 / 2 sources indexed`). Select **Index New Sources** to crawl and
embed only those pending sources.

### Customize crawl behavior

Adjust settings in `backend/utils/config.py` or `.env`.

### Improve answer quality

You can:

- change the embedding model,
- adjust chunk size and overlap,
- add reranking,
- add citation validation,
- or introduce a more advanced LLM provider.

### Add frontend features

The current frontend is intentionally simple. Future enhancements could include:

- source filtering,
- conversation export/import,
- user accounts,
- streaming responses,
- better markdown rendering,
- and richer knowledge-base management.

---

## 13. Current limitations and important design notes

- The local fallback is extractive, not fully generative.
- The crawler does not implement advanced features like JavaScript rendering or authentication handling.
- The index is built from all raw JSON files in the raw directory; it is not source-scoped unless you manually clean the directory.
- Initialization state and the loaded vector index are process-local.
- There is no user auth, database-backed persistence, or multi-user storage.
- This project is intended for local development and experimentation, not as a production-grade multi-tenant service.

---

## 14. Summary for AI handoff

PyNexus is a local-first Python documentation RAG app with:

- a Scrapy-based crawler,
- a FastAPI API server,
- a FAISS-backed vector search index,
- an embedding and chunking pipeline,
- and a React chat frontend.

The core idea is simple: crawl docs, index them locally, retrieve relevant passages, and answer questions with source-backed context.

For future development, the best extension points are:

- `backend/python_sources.py` for knowledge-base expansion,
- `backend/ingestion/ingest.py` for indexing improvements,
- `backend/rag/pipeline.py` for answer quality improvements,
- and `frontend/src/components/` for UX enhancements.
