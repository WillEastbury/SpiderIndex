#!/usr/bin/env python3
"""
md2html.py — Convert a frontmatter-enabled Markdown file into a clean,
responsive HTML page with an auto-generated table of contents.

Usage:
    python md2html.py <input.md> [output.html]

If output.html is omitted, it writes to the same name with .html extension.
"""

import sys
import re
import yaml
import markdown
from pathlib import Path


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split YAML frontmatter from markdown body."""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            meta = yaml.safe_load(parts[1]) or {}
            body = parts[2].strip()
            return meta, body
    return {}, text


def slugify(text: str) -> str:
    """Create a URL-friendly anchor from heading text."""
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s]+", "-", text).strip("-")


def build_toc(html: str) -> tuple[str, str]:
    """Extract h2/h3 headings, inject anchor IDs, and return (toc_html, updated_html)."""
    toc_items = []
    heading_pattern = re.compile(r"<(h[23])>(.*?)</\1>", re.DOTALL)

    def replace_heading(match):
        tag = match.group(1)
        content = match.group(2)
        clean = re.sub(r"<[^>]+>", "", content).strip()
        slug = slugify(clean)
        level = int(tag[1])
        indent = "toc-h3" if level == 3 else "toc-h2"
        toc_items.append(f'<li class="{indent}"><a href="#{slug}">{clean}</a></li>')
        return f'<{tag} id="{slug}">{content}</{tag}>'

    updated = heading_pattern.sub(replace_heading, html)
    toc_html = '<nav class="toc"><h2>Contents</h2><ul>\n' + "\n".join(toc_items) + "\n</ul></nav>"
    return toc_html, updated


def render_meta_banner(meta: dict) -> str:
    """Render frontmatter metadata as a subtle header banner."""
    parts = []
    if meta.get("author"):
        parts.append(f'<span class="meta-item">By <strong>{meta["author"]}</strong></span>')
    if meta.get("product"):
        parts.append(f'<span class="meta-item">{meta["product"]}</span>')
    if meta.get("category"):
        parts.append(f'<span class="meta-item">{meta["category"]}</span>')
    if meta.get("last_updated"):
        parts.append(f'<span class="meta-item">Updated {meta["last_updated"]}</span>')
    if meta.get("audience"):
        parts.append(f'<span class="meta-item">Audience: {meta["audience"]}</span>')

    tags_html = ""
    if meta.get("tags"):
        tags = "".join(f'<span class="tag">{t}</span>' for t in meta["tags"])
        tags_html = f'<div class="tags">{tags}</div>'

    return f'<div class="meta-banner"><div class="meta-items">{"  &middot;  ".join(parts)}</div>{tags_html}</div>'


CSS = """
:root {
    --accent: #0b8888;
    --accent-light: #e9faf7;
    --text: #1a1a1a;
    --text-secondary: #555;
    --border: #e0e0e0;
    --bg: #ffffff;
    --sidebar-width: 240px;
}

*, *::before, *::after { box-sizing: border-box; }

body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    color: var(--text);
    background: var(--bg);
    margin: 0;
    padding: 0;
    line-height: 1.7;
    font-size: 16px;
}

.page {
    display: flex;
    max-width: 1100px;
    margin: 0 auto;
    padding: 2rem 1.5rem;
    gap: 2.5rem;
}

/* --- Sidebar TOC --- */
.toc {
    position: sticky;
    top: 2rem;
    flex: 0 0 var(--sidebar-width);
    max-height: calc(100vh - 4rem);
    overflow-y: auto;
    padding-right: 1rem;
    border-right: 2px solid var(--border);
}

.toc h2 {
    font-size: 0.85rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text-secondary);
    margin: 0 0 0.75rem 0;
}

.toc ul {
    list-style: none;
    padding: 0;
    margin: 0;
}

.toc li a {
    display: block;
    padding: 0.3rem 0.5rem;
    color: var(--text-secondary);
    text-decoration: none;
    font-size: 0.9rem;
    border-left: 3px solid transparent;
    transition: all 0.15s ease;
}

.toc li a:hover,
.toc li a.active {
    color: var(--accent);
    border-left-color: var(--accent);
    background: var(--accent-light);
}

.toc-h3 a { padding-left: 1.25rem; font-size: 0.85rem; }

/* --- Main content --- */
.content {
    flex: 1;
    min-width: 0;
}

.content h1 {
    font-size: 2rem;
    font-weight: 700;
    margin: 0 0 0.5rem 0;
    color: var(--text);
}

.content h2 {
    font-size: 1.35rem;
    font-weight: 600;
    margin: 2rem 0 0.75rem 0;
    padding-top: 1rem;
    border-top: 1px solid var(--border);
    color: var(--text);
}

.content h2:first-of-type { border-top: none; padding-top: 0; }

.content h3 {
    font-size: 1.1rem;
    font-weight: 600;
    margin: 1.5rem 0 0.5rem 0;
    color: var(--text);
}

.content p { margin: 0.75rem 0; }

.content img {
    max-width: 100%;
    height: auto;
    border-radius: 8px;
    border: 1px solid var(--border);
    margin: 1rem 0;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}

.content hr {
    border: none;
    border-top: 1px solid var(--border);
    margin: 2rem 0;
}

.content ul, .content ol {
    padding-left: 1.5rem;
    margin: 0.75rem 0;
}

.content li { margin: 0.3rem 0; }

.content a {
    color: var(--accent);
    text-decoration: none;
}

.content a:hover { text-decoration: underline; }

/* --- Metadata banner --- */
.meta-banner {
    background: var(--accent-light);
    border-radius: 8px;
    padding: 0.75rem 1rem;
    margin-bottom: 1.5rem;
    font-size: 0.85rem;
    color: var(--text-secondary);
}

.meta-items { display: flex; flex-wrap: wrap; gap: 0.25rem; align-items: center; }

.tags { margin-top: 0.5rem; display: flex; flex-wrap: wrap; gap: 0.4rem; }

.tag {
    background: var(--accent);
    color: white;
    padding: 0.15rem 0.55rem;
    border-radius: 10px;
    font-size: 0.75rem;
    font-weight: 500;
}

/* --- Responsive --- */
@media (max-width: 768px) {
    .page { flex-direction: column; padding: 1rem; }
    .toc {
        position: static;
        flex: none;
        border-right: none;
        border-bottom: 2px solid var(--border);
        padding: 0 0 1rem 0;
        margin-bottom: 1rem;
        max-height: none;
    }
}

/* --- Scroll-spy highlight (JS-driven) --- */
.toc li a.active { font-weight: 600; }
"""

JS = """
document.addEventListener('DOMContentLoaded', () => {
    const tocLinks = document.querySelectorAll('.toc a');
    const headings = [];

    tocLinks.forEach(link => {
        const id = link.getAttribute('href').slice(1);
        const el = document.getElementById(id);
        if (el) headings.push({ el, link });
    });

    const observer = new IntersectionObserver(entries => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                tocLinks.forEach(l => l.classList.remove('active'));
                const match = headings.find(h => h.el === entry.target);
                if (match) match.link.classList.add('active');
            }
        });
    }, { rootMargin: '-80px 0px -60% 0px', threshold: 0.1 });

    headings.forEach(h => observer.observe(h.el));
});
"""


def convert(input_path: str, output_path: str | None = None):
    src = Path(input_path)
    if not src.exists():
        print(f"Error: {src} not found")
        sys.exit(1)

    dst = Path(output_path) if output_path else src.with_suffix(".html")

    raw = src.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(raw)

    # Convert markdown to HTML
    md = markdown.Markdown(extensions=["extra", "sane_lists"])
    html_body = md.convert(body)

    # Build TOC and inject heading IDs
    toc_html, html_body = build_toc(html_body)

    # Metadata banner
    meta_html = render_meta_banner(meta) if meta else ""

    title = meta.get("title", src.stem)
    description = meta.get("description", "")

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="{description}">
    <title>{title}</title>
    <style>{CSS}</style>
</head>
<body>
    <div class="page">
        {toc_html}
        <article class="content">
            {meta_html}
            {html_body}
        </article>
    </div>
    <script>{JS}</script>
</body>
</html>"""

    dst.write_text(page, encoding="utf-8")
    print(f"Generated: {dst}  ({dst.stat().st_size:,} bytes)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python md2html.py <input.md> [output.html]")
        sys.exit(1)

    convert(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
