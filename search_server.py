#!/usr/bin/env python3
"""
search_server.py — FastAPI help centre server with browse, search, and
themed article rendering.

Usage:
    python search_server.py [--db-dir DIR] [--md-dir DIR] [--theme FILE] [--port PORT]

Serves:
    /              — Home page with collection panels (like original site)
    /browse/{col}  — Collection page with subcollection TOC
    /article/{id}  — Themed article with sidebar TOC
    /search        — Semantic search UI
    /api/search    — Search API
"""

import argparse
import re
import yaml
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
site_index = {}   # collection -> subcollection -> [articles]
all_articles = {} # filename -> meta
md_dir = None


def parse_frontmatter(text):
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                return yaml.safe_load(parts[1]) or {}, parts[2].strip()
            except yaml.YAMLError:
                pass
    return {}, text


def init_db(db_dir: str):
    global collection
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
    client = chromadb.PersistentClient(path=db_dir)
    collection = client.get_collection(name="helpctr_docs", embedding_function=ef)
    print(f"Loaded collection: {collection.count()} chunks")


def build_site_index(markdown_dir: Path):
    """Scan all markdown files and build a navigable site index."""
    global site_index, all_articles, md_dir
    md_dir = markdown_dir

    for f in sorted(markdown_dir.glob("*.md")):
        raw = f.read_text(encoding="utf-8")
        meta, _ = parse_frontmatter(raw)
        title = meta.get("title", f.stem)
        col = meta.get("collection", "Uncategorised")
        sub = meta.get("subcollection", "")

        entry = {"file": f.stem, "title": title, "meta": meta}
        all_articles[f.stem] = entry

        if col not in site_index:
            site_index[col] = {"_articles": []}
        if sub:
            if sub not in site_index[col]:
                site_index[col][sub] = []
            site_index[col][sub].append(entry)
        else:
            site_index[col]["_articles"].append(entry)

    # Deduplicate: remove from _articles any article that also appears
    # in a named subcollection (prefer the more specific placement)
    for col, col_data in site_index.items():
        sub_files = set()
        for key, articles in col_data.items():
            if key != "_articles":
                sub_files.update(a["file"] for a in articles)
        if sub_files:
            col_data["_articles"] = [
                a for a in col_data["_articles"] if a["file"] not in sub_files
            ]

    total = len(all_articles)
    cols = len(site_index)
    print(f"Built site index: {total} articles in {cols} collections")


theme = {}


def load_theme(path: str):
    global theme
    p = Path(path)
    if p.exists():
        theme.update(yaml.safe_load(p.read_text(encoding="utf-8")) or {})
    print(f"Loaded theme: {theme.get('site_name', 'Help Centre')}")


def slugify(text):
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s]+", "-", text).strip("-")


# ── Bootstrap CDN URLs ────────────────────────────────────────

def _bs_css():
    t = theme
    bsv = t.get("bootstrap_version", "5.3.3")
    bw = t.get("bootswatch_theme", "flatly")
    if bw and bw != "default":
        return f"https://cdn.jsdelivr.net/npm/bootswatch@{bsv}/dist/{bw}/bootstrap.min.css"
    return f"https://cdn.jsdelivr.net/npm/bootstrap@{bsv}/dist/css/bootstrap.min.css"

def _bs_js():
    bsv = theme.get("bootstrap_version", "5.3.3")
    return f"https://cdn.jsdelivr.net/npm/bootstrap@{bsv}/dist/js/bootstrap.bundle.min.js"


# ── HTML page wrapper ─────────────────────────────────────────

def _page(title: str, body: str, breadcrumbs: str = ""):
    t = theme
    name = t.get("site_name", "Help Centre")
    logo = f'<img src="{t["logo_url"]}" alt="" height="28" class="me-2">' if t.get("logo_url") else ""
    favicon = f'<link rel="icon" href="{t["favicon_url"]}">' if t.get("favicon_url") else ""
    footer = ""
    if t.get("footer_text"):
        footer = f'<footer class="footer-hc text-center py-3 mt-4"><small>{t["footer_text"]}</small></footer>'

    bc = ""
    if breadcrumbs and t.get("show_breadcrumbs", True):
        bc = f'<nav class="breadcrumb-hc px-4 py-2"><small>{breadcrumbs}</small></nav>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
{favicon}
<title>{title} &mdash; {name}</title>
<link rel="stylesheet" href="{_bs_css()}">
<link rel="stylesheet" href="/static/custom.css">
</head>
<body>
<nav class="navbar navbar-expand-md navbar-dark navbar-hc px-3">
    <a class="navbar-brand" href="/">{logo}{name}</a>
    <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navMain">
        <span class="navbar-toggler-icon"></span>
    </button>
    <div class="collapse navbar-collapse" id="navMain">
        <ul class="navbar-nav ms-auto">
            <li class="nav-item"><a class="nav-link" href="/">Home</a></li>
            <li class="nav-item"><a class="nav-link" href="/search">Search</a></li>
        </ul>
    </div>
</nav>
{bc}
{body}
{footer}
<script src="{_bs_js()}"></script>
</body>
</html>"""


# ── Static file serving ───────────────────────────────────────

from fastapi.staticfiles import StaticFiles


# ── API routes ────────────────────────────────────────────────

@app.get("/api/search")
def api_search(q: str = Query(..., min_length=2), n: int = Query(10, ge=1, le=50)):
    results = collection.query(query_texts=[q], n_results=n, include=["documents", "metadatas", "distances"])
    items = []
    for doc, meta, dist in zip(results["documents"][0], results["metadatas"][0], results["distances"][0]):
        relevance = round((1 - dist) * 100, 1)
        if relevance < 25:
            continue
        items.append({
            "title": meta.get("title", "Untitled"),
            "heading": meta.get("heading", ""),
            "collection": meta.get("collection", ""),
            "subcollection": meta.get("subcollection", ""),
            "source_url": meta.get("source_url", ""),
            "file": meta.get("file", "").replace(".md", ""),
            "snippet": doc[:300] + ("..." if len(doc) > 300 else ""),
            "relevance": relevance,
        })
    return {"query": q, "count": len(items), "results": items}


@app.get("/api/stats")
def api_stats():
    return {"total_chunks": collection.count(), "total_articles": len(all_articles),
            "total_collections": len(site_index)}


# ── Home page ─────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def home():
    t = theme
    name = t.get("site_name", "Help Centre")
    cards = ""
    for col_name, col_data in sorted(site_index.items()):
        slug = slugify(col_name)
        top = col_data.get("_articles", [])
        subs = {k: v for k, v in col_data.items() if k != "_articles"}
        total = len(top) + sum(len(v) for v in subs.values())
        sub_list = ", ".join(list(subs.keys())[:3])
        if len(subs) > 3:
            sub_list += f" +{len(subs)-3} more"

        cards += f"""<div class="col">
            <a href="/browse/{slug}" class="text-decoration-none">
                <div class="card card-hc h-100 p-3">
                    <div class="card-body">
                        <h5 class="card-title">{col_name}</h5>
                        <p class="card-text text-muted small">{sub_list}</p>
                    </div>
                    <div class="card-footer bg-transparent border-0 pt-0">
                        <small class="text-muted">{total} articles</small>
                    </div>
                </div>
            </a>
        </div>"""

    body = f"""
    <div class="hero-hc">
        <h1>{name}</h1>
        <p>Browse documentation or search across all articles</p>
        <input type="text" class="form-control" placeholder="Search for articles..."
            onkeydown="if(event.key==='Enter')window.location='/search?q='+encodeURIComponent(this.value)">
    </div>
    <div class="container py-4">
        <div class="row row-cols-1 row-cols-md-2 row-cols-lg-3 g-3">
            {cards}
        </div>
    </div>"""
    return _page(name, body)


# ── Browse collection ─────────────────────────────────────────

@app.get("/browse/{col_slug}", response_class=HTMLResponse)
def browse(col_slug: str):
    col_name = col_data = None
    for name, data in site_index.items():
        if slugify(name) == col_slug:
            col_name, col_data = name, data
            break
    if not col_data:
        return _page("Not Found", '<div class="container py-5"><h1>Collection not found</h1></div>')

    subs = {k: v for k, v in col_data.items() if k != "_articles"}
    top = col_data.get("_articles", [])

    # Deduplicate: remove from top any article that appears in a subcollection
    sub_files = set()
    for arts in subs.values():
        sub_files.update(a["file"] for a in arts)
    top = [a for a in top if a["file"] not in sub_files]

    # Deduplicate within subcollections by file key (keep first occurrence)
    seen_files = set(a["file"] for a in top)
    deduped_subs = {}
    for sn, arts in sorted(subs.items()):
        unique = []
        for a in arts:
            if a["file"] not in seen_files:
                seen_files.add(a["file"])
                unique.append(a)
        deduped_subs[sn] = unique
    subs = deduped_subs

    # Sidebar
    sb = '<p class="sidebar-heading mb-2">Navigation</p><ul class="nav flex-column">'
    if top:
        sb += '<li class="sub-heading mt-2">General</li>'
        for a in top[:8]:
            sb += f'<li class="nav-item"><a class="nav-link py-1" href="/article/{a["file"]}">{a["title"][:45]}</a></li>'
    for sn, arts in sorted(subs.items()):
        sid = slugify(sn)
        sb += f'<li class="sub-heading mt-2"><a href="#{sid}" class="text-decoration-none text-dark">{sn}</a></li>'
        for a in arts[:4]:
            sb += f'<li class="nav-item"><a class="nav-link py-1" href="/article/{a["file"]}">{a["title"][:40]}</a></li>'
        if len(arts) > 4:
            sb += f'<li class="nav-item"><a class="nav-link py-1 fst-italic" href="#{sid}">...{len(arts)-4} more</a></li>'
    sb += '</ul>'

    # Main
    main = ""
    if top:
        items = "".join(f'<a href="/article/{a["file"]}" class="list-group-item list-group-item-action">{a["title"]}</a>' for a in top)
        main += f'<div class="sub-section-hc mb-4"><h2>General</h2><div class="list-group article-list-hc">{items}</div></div>'
    for sn, arts in sorted(subs.items()):
        sid = slugify(sn)
        items = "".join(f'<a href="/article/{a["file"]}" class="list-group-item list-group-item-action">{a["title"]}</a>' for a in arts)
        main += f'<div class="sub-section-hc mb-4" id="{sid}"><h2>{sn}</h2><div class="list-group article-list-hc">{items}</div></div>'

    bc = f'<a href="/">Home</a> <span class="text-muted">&rsaquo;</span> {col_name}'
    body = f'<div class="container py-4"><div class="row"><div class="col-md-3"><div class="sidebar-hc">{sb}</div></div><div class="col-md-9">{main}</div></div></div>'
    return _page(col_name, body, bc)


# ── Article page ──────────────────────────────────────────────

@app.get("/article/{file_id}", response_class=HTMLResponse)
def article(file_id: str):
    import markdown as md_lib

    entry = all_articles.get(file_id)
    if not entry or not md_dir:
        return _page("Not Found", '<div class="container py-5"><h1>Article not found</h1></div>')

    md_path = md_dir / f"{file_id}.md"
    if not md_path.exists():
        return _page("Not Found", '<div class="container py-5"><h1>File not found</h1></div>')

    raw = md_path.read_text(encoding="utf-8")
    meta, body_md = parse_frontmatter(raw)
    title = meta.get("title", file_id)
    col = meta.get("collection", "")
    sub = meta.get("subcollection", "")
    author = meta.get("author", "")
    source_url = meta.get("source_url", "")

    engine = md_lib.Markdown(extensions=["extra", "sane_lists"])
    html_body = engine.convert(body_md)

    # Build TOC
    toc_items = []
    def inject_ids(m):
        tag, content = m.group(1), m.group(2)
        clean = re.sub(r"<[^>]+>", "", content).strip()
        slug = slugify(clean)
        cls = "toc-h3" if tag == "h3" else ""
        toc_items.append(f'<li class="nav-item {cls}"><a class="nav-link py-1" href="#{slug}">{clean}</a></li>')
        return f'<{tag} id="{slug}">{content}</{tag}>'
    html_body = re.sub(r"<(h[23])>(.*?)</\1>", inject_ids, html_body, flags=re.DOTALL)

    toc = ""
    if toc_items:
        toc = f'<p class="sidebar-heading mb-2">Contents</p><ul class="nav flex-column article-toc">{"".join(toc_items)}</ul>'

    # Collection nav
    col_nav = ""
    if col and col in site_index and theme.get("show_collection_nav", True):
        col_data = site_index[col]
        related = col_data.get(sub, []) if sub and sub in col_data else col_data.get("_articles", [])
        if related:
            col_slug = slugify(col)
            items = ""
            for a in related:
                cur = "current" if a["file"] == file_id else ""
                items += f'<li class="nav-item {cur}"><a class="nav-link py-1" href="/article/{a["file"]}">{a["title"][:40]}</a></li>'
            col_nav = f'<div class="col-nav-hc"><p class="sidebar-heading mb-2"><a href="/browse/{col_slug}" class="text-decoration-none text-muted">{sub or col}</a></p><ul class="nav flex-column">{items}</ul></div>'

    sidebar = f'<div class="sidebar-hc">{toc}{col_nav}</div>'

    # Meta banner
    banner = ""
    if theme.get("show_meta_banner", True) and (author or meta.get("audience")):
        parts = []
        if author: parts.append(f"By <strong>{author}</strong>")
        if meta.get("audience"): parts.append(meta["audience"])
        banner = f'<div class="meta-banner-hc p-2 px-3 mb-3 small text-muted">{" &middot; ".join(parts)}</div>'

    source = ""
    if source_url and theme.get("show_source_link", True):
        source = f'<div class="border-top mt-4 pt-3"><small><a href="{source_url}" target="_blank">View original article &nearr;</a></small></div>'

    # Breadcrumbs
    col_slug = slugify(col) if col else ""
    bc = '<a href="/">Home</a>'
    if col: bc += f' <span class="text-muted">&rsaquo;</span> <a href="/browse/{col_slug}">{col}</a>'
    if sub: bc += f' <span class="text-muted">&rsaquo;</span> {sub}'

    body = f"""<div class="container py-4">
        <div class="row">
            <div class="col-md-3">{sidebar}</div>
            <div class="col-md-9 article-body">
                <h1>{title}</h1>
                {banner}
                {html_body}
                {source}
            </div>
        </div>
    </div>
    <script>
    document.addEventListener('DOMContentLoaded',()=>{{
        const links=document.querySelectorAll('.article-toc .nav-link');
        const heads=[];
        links.forEach(l=>{{const id=l.getAttribute('href').slice(1);const el=document.getElementById(id);if(el)heads.push({{el,l}})}});
        if(!heads.length)return;
        const obs=new IntersectionObserver(entries=>{{entries.forEach(e=>{{if(e.isIntersecting){{
            links.forEach(l=>l.classList.remove('active'));
            const m=heads.find(h=>h.el===e.target);if(m)m.l.classList.add('active');
        }}}});}},{{rootMargin:'-80px 0px -60% 0px',threshold:0.1}});
        heads.forEach(h=>obs.observe(h.el));
    }});
    </script>"""
    return _page(title, body, bc)


# ── Search page ───────────────────────────────────────────────

@app.get("/search", response_class=HTMLResponse)
def search_page():
    body = """
    <div class="hero-hc">
        <h1>Search</h1>
        <p>Semantic search across all documentation</p>
        <input type="text" class="form-control" id="q" placeholder="Search for articles..."
            autofocus autocomplete="off">
    </div>
    <div class="container py-4" style="max-width:750px">
        <div id="status" class="text-center text-muted small mb-3"></div>
        <div id="results">
            <div class="text-center text-muted py-5">
                <div style="font-size:2.5rem">&#x1F4DA;</div>
                <p>Type a question or keyword to search</p>
            </div>
        </div>
    </div>
    <script>
    let timer=null;
    const input=document.getElementById('q');
    const resultsDiv=document.getElementById('results');
    const statusDiv=document.getElementById('status');
    const params=new URLSearchParams(window.location.search);
    if(params.get('q')){input.value=params.get('q');doSearch();}
    fetch('/api/stats').then(r=>r.json()).then(d=>{statusDiv.textContent=d.total_articles+' articles, '+d.total_chunks.toLocaleString()+' indexed sections'});
    input.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(doSearch,250)});
    input.addEventListener('keydown',e=>{if(e.key==='Enter'){clearTimeout(timer);doSearch()}});
    async function doSearch(){
        const q=input.value.trim();
        if(q.length<2){resultsDiv.innerHTML='<div class="text-center text-muted py-5"><p>Type to search</p></div>';return}
        statusDiv.textContent='Searching...';
        const resp=await fetch('/api/search?q='+encodeURIComponent(q)+'&n=15');
        const data=await resp.json();
        statusDiv.textContent=data.count+' results';
        if(!data.results.length){resultsDiv.innerHTML='<div class="text-center text-muted py-5"><p>No results found.</p></div>';return}
        resultsDiv.innerHTML=data.results.map(r=>{
            const bc=r.relevance>=70?'bg-success-subtle text-success':r.relevance>=50?'bg-warning-subtle text-warning':'bg-danger-subtle text-danger';
            const snippet=hl(esc(r.snippet),q);
            return '<a href="/article/'+r.file+'" class="card search-result-hc p-3 mb-2 text-decoration-none d-block">'
                +'<div class="d-flex justify-content-between align-items-start">'
                +'<strong class="text-primary">'+esc(r.title)+'</strong>'
                +'<span class="badge '+bc+' ms-2">'+r.relevance+'%</span></div>'
                +(r.collection?'<div class="small text-muted mt-1"><span class="badge bg-light text-dark border">'+esc(r.collection)+'</span>'
                +(r.heading?' <span>&sect; '+esc(r.heading)+'</span>':'')+'</div>':'')
                +'<div class="small mt-1">'+snippet+'</div></a>'
        }).join('');
    }
    function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
    function hl(t,q){const terms=q.split(/\\s+/).filter(x=>x.length>2);terms.forEach(w=>{t=t.replace(new RegExp('('+w.replace(/[.*+?^${}()|[\\]\\\\]/g,'\\\\$&')+')','gi'),'<mark>$1</mark>')});return t}
    </script>"""
    return _page("Search", body)


# ── Main ──────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-dir", default="search_db")
    parser.add_argument("--md-dir", default="site/markdown")
    parser.add_argument("--theme", default="theme.yaml")
    parser.add_argument("--static-dir", default="static")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    load_theme(args.theme)
    init_db(args.db_dir)
    build_site_index(Path(args.md_dir))

    static_path = Path(args.static_dir)
    if static_path.exists():
        app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

    print(f"Starting server on http://localhost:{args.port}")
    uvicorn.run(app, host="0.0.0.0", port=args.port)
