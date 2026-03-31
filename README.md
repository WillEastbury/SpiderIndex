# Help Centre Toolkit

A complete toolkit for spidering, converting, analysing, and searching Intercom-based Help Centre sites.

## Features

- **Spider** — Crawl an Intercom Help Centre and download all articles
- **Convert** — Transform HTML articles to Markdown with YAML frontmatter, then render to clean standalone HTML with sidebar TOC and scroll-spy
- **Analyse** — Generate a comprehensive readability & accessibility report with audience-aware scoring and per-document recommendations
- **Search** — Semantic search powered by local sentence-transformer embeddings and ChromaDB

## Quick Start

### 1. Install dependencies

```bash
pip install markdown pyyaml chromadb fastapi uvicorn openai sentence-transformers
```

### 2. Spider a Help Centre

```bash
python spider.py --base-url https://support.example.com --output-dir site
```

This will:
- Discover all collections and sub-collections
- Download every article
- Convert to Markdown (with frontmatter) in `site/markdown/`
- Render to standalone HTML in `site/articles/`
- Generate a site-wide `site/index.html`
- Save a `site/manifest.json` with the full structure

### 3. Analyse readability

```bash
python analyse_readability.py --input-dir site/markdown --output site/readability-report.html
```

Generates an interactive HTML report with:
- Per-document readability scores (Flesch, FK Grade, Fog, SMOG)
- Domain-adjusted scoring based on frontmatter `audience` field
- Accessibility checks (alt text, heading hierarchy, link text)
- Prioritised recommendations for every document
- Sortable/filterable dashboard

### 4. Index for search

```bash
python index_docs.py --input-dir site/markdown --db-dir search_db
```

Chunks all documents by heading sections and creates embeddings using a local `all-MiniLM-L6-v2` model (no API key needed).

### 5. Start the search server

```bash
python search_server.py --db-dir search_db --port 8080
```

Opens a browser-ready semantic search UI at `http://localhost:8080` with:
- Real-time search-as-you-type
- Relevance scoring
- Keyword highlighting
- Collection/section context

## Tools

| File | Purpose |
|---|---|
| `spider.py` | Crawl and convert an Intercom Help Centre |
| `md2html.py` | Convert a single Markdown file to HTML with TOC |
| `analyse_readability.py` | Batch readability & accessibility analysis |
| `index_docs.py` | Chunk and embed documents into ChromaDB |
| `search_server.py` | FastAPI search server with web UI |

## Architecture

```
Help Centre (Intercom)
    │
    ▼ spider.py
site/markdown/*.md          (Markdown + YAML frontmatter)
site/articles/*.html        (Standalone HTML with TOC)
site/index.html             (Site-wide table of contents)
    │
    ├─▶ analyse_readability.py → readability-report.html
    │
    └─▶ index_docs.py → search_db/ (ChromaDB + embeddings)
                              │
                              ▼ search_server.py
                    http://localhost:8080 (Search UI)
```

## Requirements

- Python 3.10+
- ~200MB disk for the sentence-transformer model (downloaded on first run)
- No API keys required — all embeddings are generated locally

## License

MIT
