#!/usr/bin/env python3
"""
spider.py — Spider an Intercom-based Help Centre, download all articles,
convert to frontmatter-enabled Markdown, then render to HTML with a
site-wide table of contents matching the original site layout.

Usage:
    python spider.py --base-url URL [--output-dir DIR] [--collection URL]

Stages:
    1. Discover collections and articles from the site
    2. Download each article page
    3. Convert to Markdown with YAML frontmatter
    4. Render each article to standalone HTML via md2html.py
    5. Generate a site-wide index.html with full TOC
"""

import re
import os
import sys
import time
import json
import yaml
import hashlib
import argparse
import markdown
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from html.parser import HTMLParser
from datetime import date


BASE = ""  # Set via --base-url, e.g. "https://support.example.com"
USER_AGENT = "HelpCentreSpider/1.0"
DELAY = 1.0  # seconds between requests (be polite)


# ── HTTP helpers ──────────────────────────────────────────────

def fetch(url: str) -> str:
    """Fetch a URL and return its text content."""
    req = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (URLError, HTTPError) as e:
        print(f"  ⚠ Failed to fetch {url}: {e}")
        return ""


class LinkExtractor(HTMLParser):
    """Extract href links from HTML."""
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for name, val in attrs:
                if name == "href" and val:
                    self.links.append(val)


def extract_links(html: str) -> list[str]:
    parser = LinkExtractor()
    parser.feed(html)
    return parser.links


class TextExtractor(HTMLParser):
    """Extract visible text from HTML, stripping tags."""
    def __init__(self):
        super().__init__()
        self.pieces = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            self.pieces.append(data)

    def get_text(self):
        return " ".join(self.pieces)


def html_to_text(html: str) -> str:
    p = TextExtractor()
    p.feed(html)
    return p.get_text()


# ── Markdown conversion ──────────────────────────────────────

def extract_article_body(html: str) -> str:
    """Pull the article body content from an Intercom help center page."""
    # The article content sits inside <article> tags
    m = re.search(r"<article[^>]*>(.*?)</article>", html, re.DOTALL)
    if not m:
        # Fallback: look for article_body div
        m = re.search(r'class="[^"]*article_body[^"]*"[^>]*>(.*?)</div>\s*</div>\s*</div>', html, re.DOTALL)
    return m.group(1).strip() if m else ""


def extract_title(html: str) -> str:
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.DOTALL)
    if m:
        return re.sub(r"<[^>]+>", "", m.group(1)).strip()
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.DOTALL)
    if m:
        return m.group(1).split("|")[0].strip()
    return "Untitled"


def extract_author(html: str) -> str:
    m = re.search(r'Written by\s*(?:</span>)?\s*<span>(.*?)</span>', html, re.DOTALL)
    if m:
        return re.sub(r"<[^>]+>", "", m.group(1)).strip()
    m = re.search(r'Written by\s*([\w\s]+)', html)
    if m:
        return m.group(1).strip()
    return ""


def html_article_to_markdown(body_html: str) -> str:
    """Convert Intercom article HTML to Markdown."""
    text = body_html

    # Headings
    for i in range(1, 7):
        hashes = "#" * i
        text = re.sub(rf"<h{i}[^>]*>(.*?)</h{i}>", lambda m: f"\n{hashes} {re.sub(r'<[^>]+>', '', m.group(1)).strip()}\n", text, flags=re.DOTALL)

    # Bold
    text = re.sub(r"<(?:b|strong)[^>]*>(.*?)</(?:b|strong)>", r"**\1**", text, flags=re.DOTALL)
    # Italic
    text = re.sub(r"<(?:i|em)[^>]*>(.*?)</(?:i|em)>", r"*\1*", text, flags=re.DOTALL)

    # Images
    def img_replace(m):
        attrs = m.group(1)
        src = re.search(r'src="([^"]+)"', attrs)
        alt = re.search(r'alt="([^"]*)"', attrs)
        if src:
            src_url = src.group(1).split("?")[0]  # Strip query params for cleanliness
            alt_text = alt.group(1) if alt else ""
            return f"\n![{alt_text}]({src.group(1)})\n"
        return ""
    text = re.sub(r"<img([^>]+)/?>", img_replace, text, flags=re.DOTALL)

    # Links (but not image links we already handled)
    text = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', lambda m: f"[{re.sub(r'<[^>]+>', '', m.group(2)).strip()}]({m.group(1)})" if not m.group(2).strip().startswith("![") else m.group(2), text, flags=re.DOTALL)

    # List items
    text = re.sub(r"<li[^>]*>(.*?)</li>", lambda m: f"- {re.sub(r'<[^>]+>', '', m.group(1)).strip()}", text, flags=re.DOTALL)

    # Horizontal rules
    text = re.sub(r"<hr\s*/?>", "\n---\n", text)

    # Paragraphs and divs → newlines
    text = re.sub(r"</?(?:p|div|section|ul|ol|br)[^>]*>", "\n", text, flags=re.DOTALL)

    # Strip remaining tags
    text = re.sub(r"<[^>]+>", "", text)

    # HTML entities
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&#x27;", "'").replace("&quot;", '"').replace("&nbsp;", " ")
    text = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), text)

    # Clean up whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def make_frontmatter(title: str, author: str, url: str, collection: str, subcollection: str) -> str:
    meta = {
        "title": title,
        "author": author or "Unknown",
        "date_scraped": str(date.today()),
        "source_url": url,
        "product": "",
        "collection": collection,
    }
    if subcollection:
        meta["subcollection"] = subcollection
    meta["audience"] = "Clinical professionals"
    return "---\n" + yaml.dump(meta, default_flow_style=False, allow_unicode=True) + "---\n"


# ── Site discovery ────────────────────────────────────────────

def discover_collections(html: str) -> list[dict]:
    """Parse the home page to find top-level collections."""
    collections = []
    domain = re.escape(BASE.replace("https://", "").replace("http://", ""))
    pattern = rf'href="(https?://{domain}/en/collections/[^"]+)"'
    for m in re.finditer(pattern, html):
        url = m.group(1).replace("http://", "https://")
        if url not in [c["url"] for c in collections]:
            collections.append({"url": url, "subcollections": [], "articles": []})
    return collections


def discover_collection_contents(html: str, parent_name: str) -> tuple[list[dict], list[dict]]:
    """Parse a collection page to find sub-collections and articles."""
    subcollections = []
    articles = []

    domain = re.escape(BASE.replace("https://", "").replace("http://", ""))
    links = re.findall(rf'href="(https?://{domain}/en/(?:collections|articles)/[^"]+)"', html)

    for raw_url in links:
        url = raw_url.replace("http://", "https://")
        if "/collections/" in url and url not in [s["url"] for s in subcollections]:
            subcollections.append({"url": url, "parent": parent_name, "articles": []})
        elif "/articles/" in url and url not in [a["url"] for a in articles]:
            articles.append({"url": url, "collection": parent_name, "subcollection": ""})

    return subcollections, articles


def collection_name_from_url(url: str) -> str:
    slug = url.rstrip("/").split("/")[-1]
    # Remove numeric prefix
    name = re.sub(r"^\d+-", "", slug)
    return name.replace("-", " ").title()


def safe_filename(text: str) -> str:
    """Create a filesystem-safe filename from text."""
    text = re.sub(r"[^\w\s-]", "", text.lower())
    text = re.sub(r"[\s]+", "-", text).strip("-")
    return text[:80]


# ── HTML rendering (reuses md2html logic) ─────────────────────

def slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s]+", "-", text).strip("-")


def build_toc(html: str) -> tuple[str, str]:
    toc_items = []
    pattern = re.compile(r"<(h[23])>(.*?)</\1>", re.DOTALL)

    def repl(match):
        tag, content = match.group(1), match.group(2)
        clean = re.sub(r"<[^>]+>", "", content).strip()
        slug = slugify(clean)
        cls = "toc-h3" if tag == "h3" else "toc-h2"
        toc_items.append(f'<li class="{cls}"><a href="#{slug}">{clean}</a></li>')
        return f'<{tag} id="{slug}">{content}</{tag}>'

    updated = pattern.sub(repl, html)
    toc_html = '<nav class="toc"><h2>Contents</h2><ul>\n' + "\n".join(toc_items) + "\n</ul></nav>"
    return toc_html, updated


ARTICLE_CSS = Path(__file__).parent / "md2html.py"  # We'll inline the CSS

def render_article_html(md_text: str, meta: dict) -> str:
    """Render a markdown article to a standalone HTML page."""
    md_engine = markdown.Markdown(extensions=["extra", "sane_lists"])
    html_body = md_engine.convert(md_text)
    toc_html, html_body = build_toc(html_body)

    title = meta.get("title", "Article")
    desc = meta.get("description", "")
    author = meta.get("author", "")
    collection = meta.get("collection", "")
    subcollection = meta.get("subcollection", "")

    breadcrumb = f'<a href="../index.html">Home</a>'
    if collection:
        col_slug = safe_filename(collection)
        breadcrumb += f' &rsaquo; <a href="../index.html#{col_slug}">{collection}</a>'
    if subcollection:
        breadcrumb += f" &rsaquo; {subcollection}"

    meta_parts = []
    if author:
        meta_parts.append(f"By <strong>{author}</strong>")
    if meta.get("date_scraped"):
        meta_parts.append(f"Scraped {meta['date_scraped']}")

    meta_banner = ""
    if meta_parts:
        meta_banner = f'<div class="meta-banner"><div class="meta-items">{" &middot; ".join(meta_parts)}</div></div>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>{SITE_CSS}</style>
</head>
<body>
<div class="breadcrumb">{breadcrumb}</div>
<div class="page">
{toc_html}
<article class="content">
{meta_banner}
{html_body}
</article>
</div>
<script>{SCROLL_JS}</script>
</body>
</html>"""


def render_index_html(site_structure: list[dict], output_dir: Path) -> str:
    """Generate the site-wide index.html with full TOC matching site layout."""
    sections = []

    for col in site_structure:
        col_name = col["name"]
        col_slug = safe_filename(col_name)
        items = []

        # Top-level articles in this collection
        for art in col.get("articles", []):
            fname = art.get("filename", "")
            title = art.get("title", "Untitled")
            if fname:
                items.append(f'<li><a href="articles/{fname}">{title}</a></li>')

        # Sub-collections
        for sub in col.get("subcollections", []):
            sub_name = sub["name"]
            sub_items = []
            for art in sub.get("articles", []):
                fname = art.get("filename", "")
                title = art.get("title", "Untitled")
                if fname:
                    sub_items.append(f'<li><a href="articles/{fname}">{title}</a></li>')

            if sub_items:
                items.append(f'<li class="subcollection"><h4>{sub_name}</h4><ul>{"".join(sub_items)}</ul></li>')

        section = f"""
        <section class="collection" id="{col_slug}">
            <h2>{col_name}</h2>
            <p class="collection-desc">{col.get('description', '')}</p>
            <ul>{"".join(items)}</ul>
        </section>"""
        sections.append(section)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Help Centre</title>
<style>{INDEX_CSS}</style>
</head>
<body>
<header>
    <h1>Help Centre</h1>
    <p>Complete documentation library &mdash; scraped {date.today()}</p>
</header>
<main>
{"".join(sections)}
</main>
</body>
</html>"""


# ── CSS constants ─────────────────────────────────────────────

SITE_CSS = """
:root {
    --accent: #0b8888; --accent-light: #e9faf7;
    --text: #1a1a1a; --text-secondary: #555; --border: #e0e0e0; --bg: #fff;
}
*, *::before, *::after { box-sizing: border-box; }
body { font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    color: var(--text); background: var(--bg); margin: 0; line-height: 1.7; font-size: 16px; }
.breadcrumb { padding: 0.75rem 2rem; font-size: 0.85rem; color: var(--text-secondary);
    border-bottom: 1px solid var(--border); }
.breadcrumb a { color: var(--accent); text-decoration: none; }
.breadcrumb a:hover { text-decoration: underline; }
.page { display: flex; max-width: 1100px; margin: 0 auto; padding: 2rem 1.5rem; gap: 2.5rem; }
.toc { position: sticky; top: 2rem; flex: 0 0 240px; max-height: calc(100vh - 4rem);
    overflow-y: auto; padding-right: 1rem; border-right: 2px solid var(--border); }
.toc h2 { font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--text-secondary); margin: 0 0 0.75rem 0; }
.toc ul { list-style: none; padding: 0; margin: 0; }
.toc li a { display: block; padding: 0.3rem 0.5rem; color: var(--text-secondary);
    text-decoration: none; font-size: 0.9rem; border-left: 3px solid transparent;
    transition: all 0.15s ease; }
.toc li a:hover, .toc li a.active { color: var(--accent); border-left-color: var(--accent);
    background: var(--accent-light); }
.toc-h3 a { padding-left: 1.25rem; font-size: 0.85rem; }
.content { flex: 1; min-width: 0; }
.content h1 { font-size: 2rem; font-weight: 700; margin: 0 0 0.5rem 0; }
.content h2 { font-size: 1.35rem; font-weight: 600; margin: 2rem 0 0.75rem 0;
    padding-top: 1rem; border-top: 1px solid var(--border); }
.content h2:first-of-type { border-top: none; padding-top: 0; }
.content h3 { font-size: 1.1rem; font-weight: 600; margin: 1.5rem 0 0.5rem 0; }
.content p { margin: 0.75rem 0; }
.content img { max-width: 100%; height: auto; border-radius: 8px; border: 1px solid var(--border);
    margin: 1rem 0; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
.content hr { border: none; border-top: 1px solid var(--border); margin: 2rem 0; }
.content ul, .content ol { padding-left: 1.5rem; margin: 0.75rem 0; }
.content li { margin: 0.3rem 0; }
.content a { color: var(--accent); text-decoration: none; }
.content a:hover { text-decoration: underline; }
.meta-banner { background: var(--accent-light); border-radius: 8px; padding: 0.75rem 1rem;
    margin-bottom: 1.5rem; font-size: 0.85rem; color: var(--text-secondary); }
.meta-items { display: flex; flex-wrap: wrap; gap: 0.25rem; align-items: center; }
@media (max-width: 768px) {
    .page { flex-direction: column; padding: 1rem; }
    .toc { position: static; flex: none; border-right: none; border-bottom: 2px solid var(--border);
        padding: 0 0 1rem 0; margin-bottom: 1rem; max-height: none; }
}
"""

INDEX_CSS = """
:root { --accent: #0b8888; --accent-light: #e9faf7; --text: #1a1a1a;
    --text-secondary: #555; --border: #e0e0e0; }
*, *::before, *::after { box-sizing: border-box; }
body { font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    color: var(--text); background: #fafafa; margin: 0; line-height: 1.6; }
header { background: var(--accent); color: white; padding: 2.5rem 2rem; text-align: center; }
header h1 { margin: 0; font-size: 2rem; }
header p { margin: 0.5rem 0 0 0; opacity: 0.85; }
main { max-width: 960px; margin: 2rem auto; padding: 0 1.5rem; }
.collection { background: white; border-radius: 10px; padding: 1.5rem 2rem; margin-bottom: 1.5rem;
    border: 1px solid var(--border); box-shadow: 0 1px 4px rgba(0,0,0,0.04); }
.collection h2 { margin: 0 0 0.25rem 0; font-size: 1.3rem; color: var(--accent); }
.collection-desc { color: var(--text-secondary); font-size: 0.9rem; margin: 0 0 1rem 0; }
.collection ul { list-style: none; padding: 0; margin: 0; }
.collection > ul > li { padding: 0.35rem 0; border-bottom: 1px solid #f0f0f0; }
.collection > ul > li:last-child { border-bottom: none; }
.collection a { color: var(--text); text-decoration: none; font-size: 0.95rem; }
.collection a:hover { color: var(--accent); }
.subcollection { margin-top: 1rem; }
.subcollection h4 { margin: 0 0 0.5rem 0; font-size: 1rem; color: var(--accent);
    border-bottom: 1px solid var(--border); padding-bottom: 0.25rem; }
.subcollection ul { padding-left: 1rem; }
.subcollection li { padding: 0.25rem 0; font-size: 0.9rem; }
"""

SCROLL_JS = """
document.addEventListener('DOMContentLoaded', () => {
    const tocLinks = document.querySelectorAll('.toc a');
    const headings = [];
    tocLinks.forEach(link => {
        const id = link.getAttribute('href').slice(1);
        const el = document.getElementById(id);
        if (el) headings.push({ el, link });
    });
    const obs = new IntersectionObserver(entries => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                tocLinks.forEach(l => l.classList.remove('active'));
                const m = headings.find(h => h.el === entry.target);
                if (m) m.link.classList.add('active');
            }
        });
    }, { rootMargin: '-80px 0px -60% 0px', threshold: 0.1 });
    headings.forEach(h => obs.observe(h.el));
});
"""


# ── Main spider ───────────────────────────────────────────────

def spider(output_dir: str, single_collection: str = None):
    out = Path(output_dir)
    articles_dir = out / "articles"
    md_dir = out / "markdown"
    articles_dir.mkdir(parents=True, exist_ok=True)
    md_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Help Centre Spider")
    print("=" * 60)

    # Step 1: Discover collections
    print("\n[1/5] Fetching site home page...")
    home_html = fetch(f"{BASE}/en/")
    if not home_html:
        print("Failed to fetch home page. Aborting.")
        sys.exit(1)

    raw_collections = discover_collections(home_html)
    if single_collection:
        raw_collections = [c for c in raw_collections if single_collection in c["url"]]

    print(f"  Found {len(raw_collections)} collections")

    # Step 2: Discover articles in each collection
    print("\n[2/5] Discovering articles in each collection...")
    site_structure = []

    for col in raw_collections:
        col_url = col["url"]
        col_name = collection_name_from_url(col_url)
        print(f"\n  📂 {col_name}")
        time.sleep(DELAY)

        col_html = fetch(col_url)
        if not col_html:
            continue

        # Extract description
        desc_m = re.search(r'<meta name="description" content="([^"]*)"', col_html)
        col_desc = desc_m.group(1) if desc_m else ""

        subcollections, top_articles = discover_collection_contents(col_html, col_name)

        col_entry = {
            "name": col_name,
            "url": col_url,
            "description": col_desc,
            "articles": top_articles,
            "subcollections": [],
        }

        for sub in subcollections:
            sub_url = sub["url"]
            sub_name = collection_name_from_url(sub_url)
            print(f"    📁 {sub_name}")
            time.sleep(DELAY)

            sub_html = fetch(sub_url)
            if not sub_html:
                continue

            _, sub_articles = discover_collection_contents(sub_html, col_name)
            for a in sub_articles:
                a["subcollection"] = sub_name

            # Deduplicate against top-level articles
            existing_urls = {a["url"] for a in top_articles}
            new_articles = [a for a in sub_articles if a["url"] not in existing_urls]

            col_entry["subcollections"].append({
                "name": sub_name,
                "url": sub_url,
                "articles": new_articles,
            })

        site_structure.append(col_entry)

    # Count total articles
    total = sum(
        len(c["articles"]) + sum(len(s["articles"]) for s in c["subcollections"])
        for c in site_structure
    )
    print(f"\n  Total articles discovered: {total}")

    # Step 3: Download and convert each article
    print(f"\n[3/5] Downloading and converting {total} articles...")
    count = 0
    all_articles = []

    for col in site_structure:
        def process_articles(articles, col_name, sub_name=""):
            nonlocal count
            for art in articles:
                count += 1
                url = art["url"]
                print(f"  [{count}/{total}] {url.split('/')[-1][:60]}")
                time.sleep(DELAY)

                html = fetch(url)
                if not html:
                    continue

                title = extract_title(html)
                author = extract_author(html)
                body_html = extract_article_body(html)
                md_body = html_article_to_markdown(body_html)

                if not md_body.strip():
                    print(f"    ⚠ Empty body, skipping")
                    continue

                frontmatter = make_frontmatter(title, author, url, col_name, sub_name)
                full_md = frontmatter + f"\n# {title}\n\n{md_body}\n"

                # Save markdown
                fname = safe_filename(title) or f"article-{count}"
                md_path = md_dir / f"{fname}.md"
                md_path.write_text(full_md, encoding="utf-8")

                # Save article HTML
                meta = yaml.safe_load(frontmatter.replace("---", "")) or {}
                html_content = render_article_html(md_body, meta)
                html_path = articles_dir / f"{fname}.html"
                html_path.write_text(html_content, encoding="utf-8")

                art["title"] = title
                art["filename"] = f"{fname}.html"
                all_articles.append(art)

        process_articles(col["articles"], col["name"])
        for sub in col["subcollections"]:
            process_articles(sub["articles"], col["name"], sub["name"])

    print(f"\n  Converted {len(all_articles)} articles")

    # Step 4: Generate site index
    print("\n[4/5] Generating site index...")
    index_html = render_index_html(site_structure, out)
    (out / "index.html").write_text(index_html, encoding="utf-8")

    # Step 5: Save site manifest
    print("[5/5] Saving site manifest...")
    manifest = {
        "scraped": str(date.today()),
        "total_articles": len(all_articles),
        "collections": [
            {
                "name": c["name"],
                "article_count": len(c["articles"]) + sum(len(s["articles"]) for s in c["subcollections"]),
                "subcollections": [s["name"] for s in c["subcollections"]],
            }
            for c in site_structure
        ],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"\n{'=' * 60}")
    print(f"Done! Output in: {out}")
    print(f"  {len(all_articles)} articles as HTML in articles/")
    print(f"  {len(all_articles)} articles as Markdown in markdown/")
    print(f"  index.html — site-wide TOC")
    print(f"  manifest.json — site structure")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Spider an Intercom Help Centre")
    parser.add_argument("--base-url", required=True, help="Base URL e.g. https://support.example.com")
    parser.add_argument("--output-dir", default="site", help="Output directory")
    parser.add_argument("--collection", default=None, help="Spider only one collection (URL substring match)")
    args = parser.parse_args()

    global BASE
    BASE = args.base_url.rstrip("/")
    spider(args.output_dir, args.collection)
