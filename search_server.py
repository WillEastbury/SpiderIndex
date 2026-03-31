#!/usr/bin/env python3
"""
search_server.py — FastAPI semantic search server for help centre docs.

Usage:
    python search_server.py [--db-dir DIR] [--port PORT] [--title TITLE]

Opens browser-ready search UI at http://localhost:8080
"""

import argparse
import uvicorn
from pathlib import Path
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

import chromadb
from chromadb.utils import embedding_functions

app = FastAPI(title="Help Centre Search")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

collection = None


def init_db(db_dir: str):
    global collection
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
    client = chromadb.PersistentClient(path=db_dir)
    collection = client.get_collection(name="helpctr_docs", embedding_function=ef)
    print(f"Loaded collection: {collection.count()} chunks")


@app.get("/api/search")
def search(q: str = Query(..., min_length=2), n: int = Query(10, ge=1, le=50)):
    results = collection.query(query_texts=[q], n_results=n, include=["documents", "metadatas", "distances"])

    items = []
    for doc, meta, dist in zip(results["documents"][0], results["metadatas"][0], results["distances"][0]):
        title = meta.get("title", "Untitled")
        relevance = round((1 - dist) * 100, 1)

        if relevance < 25:
            continue

        items.append({
            "title": title,
            "heading": meta.get("heading", ""),
            "collection": meta.get("collection", ""),
            "subcollection": meta.get("subcollection", ""),
            "source_url": meta.get("source_url", ""),
            "html_file": meta.get("html_file", ""),
            "snippet": doc[:300] + "..." if len(doc) > 300 else doc,
            "relevance": relevance,
        })

    return {"query": q, "count": len(items), "results": items}


@app.get("/api/stats")
def stats():
    return {"total_chunks": collection.count()}


@app.get("/", response_class=HTMLResponse)
def index():
    return SEARCH_HTML


SEARCH_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Help Centre — Search</title>
<style>
:root { --accent: #0b8888; --accent-light: #e9faf7; --text: #1a1a1a;
    --text-sec: #666; --border: #e0e0e0; --bg: #fafafa; }
* { box-sizing: border-box; }
body { font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    color: var(--text); background: var(--bg); margin: 0; }
header { background: var(--accent); color: white; padding: 2rem 2rem 1.5rem; text-align: center; }
header h1 { margin: 0; font-size: 1.6rem; }
header p { margin: 0.3rem 0 0; opacity: 0.8; font-size: 0.9rem; }
.search-box { max-width: 700px; margin: -1.5rem auto 0; padding: 0 1rem; position: relative; z-index: 1; }
.search-input { width: 100%; padding: 1rem 1.25rem 1rem 3rem; font-size: 1.1rem; border: 2px solid var(--border);
    border-radius: 12px; outline: none; background: white; box-shadow: 0 4px 12px rgba(0,0,0,0.08);
    transition: border-color 0.2s; }
.search-input:focus { border-color: var(--accent); }
.search-icon { position: absolute; left: 1.75rem; top: 50%; transform: translateY(-50%);
    font-size: 1.2rem; color: var(--text-sec); pointer-events: none; }
main { max-width: 700px; margin: 1.5rem auto; padding: 0 1rem; }
.status { text-align: center; color: var(--text-sec); font-size: 0.9rem; margin: 1rem 0; }
.result { background: white; border-radius: 10px; padding: 1.25rem 1.5rem; margin-bottom: 0.75rem;
    border: 1px solid var(--border); transition: all 0.15s; cursor: pointer; }
.result:hover { border-color: var(--accent); box-shadow: 0 2px 8px rgba(11,136,136,0.1); }
.result-title { font-weight: 600; font-size: 1.05rem; color: var(--accent); margin: 0 0 0.2rem; }
.result-meta { font-size: 0.8rem; color: var(--text-sec); margin-bottom: 0.5rem; }
.result-meta span { margin-right: 0.75rem; }
.result-snippet { font-size: 0.9rem; color: var(--text); line-height: 1.5; }
.relevance { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 8px;
    font-size: 0.75rem; font-weight: 600; }
.rel-high { background: #dcfce7; color: #166534; }
.rel-mid { background: #fef9c3; color: #854d0e; }
.rel-low { background: #fee2e2; color: #991b1b; }
.tag { background: var(--accent-light); color: var(--accent); padding: 0.1rem 0.45rem;
    border-radius: 6px; font-size: 0.75rem; }
mark { background: #fef08a; padding: 0 2px; border-radius: 2px; }
.empty { text-align: center; padding: 3rem; color: var(--text-sec); }
.empty .emoji { font-size: 2.5rem; margin-bottom: 0.5rem; }
</style>
</head>
<body>
<header>
    <h1>🔍 Help Centre Search</h1>
    <p>Semantic search across all support documentation</p>
</header>
<div class="search-box">
    <span class="search-icon">🔎</span>
    <input class="search-input" type="text" id="q" placeholder="Search documentation..."
           autofocus autocomplete="off">
</div>
<main>
    <div class="status" id="status"></div>
    <div id="results">
        <div class="empty">
            <div class="emoji">📚</div>
            <p>Type a question or keyword to search the Help Centre</p>
        </div>
    </div>
</main>
<script>
let timer = null;
const input = document.getElementById('q');
const resultsDiv = document.getElementById('results');
const statusDiv = document.getElementById('status');

// Load stats
fetch('/api/stats').then(r => r.json()).then(d => {
    statusDiv.textContent = `${d.total_chunks.toLocaleString()} indexed sections ready`;
});

input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(doSearch, 250);
});

input.addEventListener('keydown', e => {
    if (e.key === 'Enter') { clearTimeout(timer); doSearch(); }
});

async function doSearch() {
    const q = input.value.trim();
    if (q.length < 2) {
        resultsDiv.innerHTML = '<div class="empty"><div class="emoji">📚</div><p>Type a question or keyword to search</p></div>';
        statusDiv.textContent = '';
        return;
    }

    statusDiv.textContent = 'Searching...';
    try {
        const resp = await fetch(`/api/search?q=${encodeURIComponent(q)}&n=15`);
        const data = await resp.json();
        statusDiv.textContent = `${data.count} results for "${data.query}"`;

        if (data.results.length === 0) {
            resultsDiv.innerHTML = '<div class="empty"><div class="emoji">🤷</div><p>No results found. Try different keywords.</p></div>';
            return;
        }

        resultsDiv.innerHTML = data.results.map(r => {
            const relClass = r.relevance >= 70 ? 'rel-high' : r.relevance >= 50 ? 'rel-mid' : 'rel-low';
            const snippet = highlightTerms(r.snippet, q);
            const url = r.source_url || '#';

            return `<div class="result" onclick="window.open('${url}', '_blank')">
                <div style="display:flex;justify-content:space-between;align-items:start">
                    <div class="result-title">${escHtml(r.title)}</div>
                    <span class="relevance ${relClass}">${r.relevance}%</span>
                </div>
                <div class="result-meta">
                    ${r.collection ? `<span class="tag">${escHtml(r.collection)}</span>` : ''}
                    ${r.heading ? `<span>§ ${escHtml(r.heading)}</span>` : ''}
                </div>
                <div class="result-snippet">${snippet}</div>
            </div>`;
        }).join('');
    } catch (e) {
        statusDiv.textContent = 'Search error: ' + e.message;
    }
}

function escHtml(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function highlightTerms(text, query) {
    const safe = escHtml(text);
    const terms = query.split(/\\s+/).filter(t => t.length > 2);
    let result = safe;
    terms.forEach(term => {
        const re = new RegExp(`(${term.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&')})`, 'gi');
        result = result.replace(re, '<mark>$1</mark>');
    });
    return result;
}
</script>
</body>
</html>"""


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-dir", default="search_db")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    init_db(args.db_dir)
    print(f"Starting server on http://localhost:{args.port}")
    uvicorn.run(app, host="0.0.0.0", port=args.port)
