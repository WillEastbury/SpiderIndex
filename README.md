# Help Centre Toolkit

A complete toolkit for spidering, converting, analysing, and searching Intercom-based Help Centre sites — with persona-driven document reviews.

## Features

- **Spider** — Crawl an Intercom Help Centre and download all articles
- **Convert** — Transform HTML articles to Markdown with YAML frontmatter, then render to clean standalone HTML with sidebar TOC and scroll-spy
- **Analyse** — Generate a comprehensive readability & accessibility report with audience-aware scoring, per-document recommendations, and multi-persona reviews
- **Renderer** — On-the-fly themed Markdown rendering with `theme.yaml` support, branded header, breadcrumbs, and responsive layout
- **Search** — Semantic search powered by local sentence-transformer embeddings and ChromaDB (results filtered at 25% relevance threshold)

## Quick Start

### 1. Install dependencies

```bash
pip install markdown pyyaml chromadb fastapi uvicorn sentence-transformers
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

### 3. Analyse readability with persona reviews

```bash
python analyse_readability.py --input-dir site/markdown --output site/readability-report.html --personas personas.json
```

Generates an interactive HTML report with:
- Per-document readability scores (Flesch, FK Grade, Fog, SMOG, Coleman-Liau)
- Domain-adjusted scoring based on frontmatter `audience` field
- Accessibility checks (alt text, heading hierarchy, link text)
- Prioritised recommendations for every document
- **9 reviewer personas** each providing independent pass/warn/fail assessments
- Sortable/filterable dashboard with expandable detail panels and persona tabs

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
- Relevance scoring (results below 25% filtered out)
- Keyword highlighting
- Collection/section context

## Reviewer Personas

The analysis engine reviews every document through the lens of **9 configurable personas**, each with their own readability thresholds, domain vocabulary, and heuristic checks:

| Persona | Role | Focus | Vocab |
|---|---|---|---|
| 🩺 Dr. Sarah Chen | General Practitioner | Speed, scannability, clinical terms OK | 134 |
| 🔪 Mr. James Okafor | Consultant Surgeon | Precision, brevity, mobile, time-critical | 98 |
| 📊 Dr. Priya Patel | Clinical Informatics Lead | Governance, prerequisites, role clarity | 111 |
| 💻 Alex Rivera | Integration Developer | Technical detail, code examples, error handling | 135 |
| ✍️ Emma Liu | Content & UX Writer | Tone, plain language, active voice, CTAs | 71 |
| 🔍 Jordan Blake | QA & Accessibility Tester | WCAG, alt text, heading hierarchy, links | 74 |
| 🏗️ David Okonkwo | Solutions Architect | System context, data flows, scalability | 143 |
| 🧑‍🦳 Margaret Thompson | Patient / Service User | Simplicity, no jargon, reassurance, mobile | 106 |
| 📋 Karen Mitchell | Medical Secretary | Procedures, batch ops, screenshots, efficiency | 118 |

Personas are defined in `personas.json` and include ~990 domain vocabulary terms covering NHS terminology, system names (EMIS, SystmOne, Cerner, Epic), medical coding (SNOMED, ICD-10), governance frameworks (GDPR, Caldicott), cloud/infra terms, and plain-language synonyms.

To add or customise personas, edit `personas.json` — no code changes needed.

## Tools

| File | Purpose |
|---|---|
| `spider.py` | Crawl and convert an Intercom Help Centre |
| `md2html.py` | Convert a single Markdown file to HTML with TOC |
| `analyse_readability.py` | Batch readability & accessibility analysis with persona reviews |
| `renderer.py` | On-the-fly themed Markdown renderer with `theme.yaml` support |
| `index_docs.py` | Chunk and embed documents into ChromaDB |
| `search_server.py` | FastAPI search server with web UI |
| `personas.json` | Reviewer persona definitions (readability thresholds, checks, vocabulary) |

## Architecture

```
Help Centre (Intercom)
    │
    ▼ spider.py --base-url URL
site/markdown/*.md          (Markdown + YAML frontmatter)
site/articles/*.html        (Standalone HTML with TOC)
site/index.html             (Site-wide table of contents)
site/manifest.json          (Site structure metadata)
    │
    ├─▶ analyse_readability.py ──┬─▶ readability-report.html
    │                            └── personas.json (9 reviewers)
    │
    ├─▶ renderer.py + theme.yaml ─▶ Themed HTML (on-the-fly)
    │
    └─▶ index_docs.py ─▶ search_db/ (ChromaDB + embeddings)
                              │
                              ▼ search_server.py
                    http://localhost:8080 (Search UI)
```

## Requirements

- Python 3.10+
- ~200MB disk for the sentence-transformer model (downloaded on first run)
- No API keys required — all embeddings are generated locally

## ⚠️ Disclaimer

This is **AI-generated proof-of-concept code**. It was built as a demonstration and, while it appears to work, it has not been rigorously tested for production use. No warranties are provided, express or implied.

**By using this software you accept that:**
- It is provided **as-is**, with no guarantee of correctness, completeness, or fitness for any particular purpose
- The authors accept **no liability** for any damage, data loss, or other issues arising from its use
- You are solely responsible for reviewing, testing, and validating the code before relying on it in any environment
- It may contain bugs, security vulnerabilities, or unexpected behaviour

**Use at your own risk.** If it breaks something, that's on you.

## License

MIT
