#!/usr/bin/env python3
"""
renderer.py — On-the-fly Markdown renderer with theming support.

Reads a site-level theme.yaml for colours, branding, and layout config,
then renders any Markdown file to a themed HTML page with auto-generated
table of contents, breadcrumbs, and navigation.

Theme config (theme.yaml):
    site_name: "My Help Centre"
    accent: "#0b8888"
    accent_light: "#e9faf7"
    logo_url: ""
    footer_text: "© 2026 My Company"
    font_family: "system-ui, sans-serif"
    show_meta_banner: true
    show_reading_time: true
"""

import re
import yaml
import math
import markdown
from pathlib import Path

DEFAULT_THEME = {
    "site_name": "Help Centre",
    "accent": "#0b8888",
    "accent_light": "#e9faf7",
    "text": "#1a1a1a",
    "text_secondary": "#555",
    "border": "#e0e0e0",
    "bg": "#ffffff",
    "logo_url": "",
    "footer_text": "",
    "font_family": '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
    "show_meta_banner": True,
    "show_reading_time": True,
    "max_width": "1100px",
    "toc_width": "240px",
}


def load_theme(theme_path: Path | str | None = None) -> dict:
    """Load theme.yaml and merge with defaults."""
    theme = dict(DEFAULT_THEME)
    if theme_path:
        p = Path(theme_path)
        if p.exists():
            with open(p, encoding="utf-8") as f:
                custom = yaml.safe_load(f) or {}
            theme.update({k: v for k, v in custom.items() if v is not None})
    return theme


def parse_frontmatter(text: str) -> tuple[dict, str]:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                meta = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                meta = {}
            return meta, parts[2].strip()
    return {}, text


def slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s]+", "-", text).strip("-")


def estimate_reading_time(text: str) -> int:
    words = len(re.findall(r"[a-zA-Z']+", text))
    return max(1, math.ceil(words / 200))


def build_toc(html: str) -> tuple[str, str]:
    """Extract h2/h3 headings, inject anchor IDs, return (toc_html, updated_html)."""
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
    if not toc_items:
        return "", updated

    toc_html = '<nav class="toc" id="toc"><h2>Contents</h2><ul>\n' + "\n".join(toc_items) + "\n</ul></nav>"
    return toc_html, updated


def render_markdown(md_text: str, meta: dict, theme: dict, collection_index: list[dict] | None = None) -> str:
    """Render a markdown string to a fully themed HTML page."""

    md_engine = markdown.Markdown(extensions=["extra", "sane_lists", "toc"])
    html_body = md_engine.convert(md_text)
    toc_html, html_body = build_toc(html_body)

    title = meta.get("title", "Untitled")
    author = meta.get("author", "")
    collection = meta.get("collection", "")
    subcollection = meta.get("subcollection", "")
    audience = meta.get("audience", "")
    tags = meta.get("tags", [])
    source_url = meta.get("source_url", "")
    date_scraped = meta.get("date_scraped", "")

    t = theme
    site_name = t["site_name"]
    reading_time = estimate_reading_time(md_text)

    # Breadcrumbs
    crumbs = [f'<a href="/">{site_name}</a>']
    if collection:
        crumbs.append(f'<span>{collection}</span>')
    if subcollection:
        crumbs.append(f'<span>{subcollection}</span>')
    breadcrumb_html = ' <span class="sep">›</span> '.join(crumbs)

    # Meta banner
    meta_banner = ""
    if t["show_meta_banner"]:
        parts = []
        if author:
            parts.append(f'By <strong>{author}</strong>')
        if audience:
            parts.append(f'Audience: {audience}')
        if t["show_reading_time"]:
            parts.append(f'{reading_time} min read')
        if date_scraped:
            parts.append(f'Scraped {date_scraped}')

        tags_html = ""
        if tags:
            tags_html = '<div class="tags">' + "".join(
                f'<span class="tag">{t_}</span>' for t_ in tags
            ) + '</div>'

        if parts or tags_html:
            meta_banner = f'''<div class="meta-banner">
                <div class="meta-items">{" &middot; ".join(parts)}</div>
                {tags_html}
            </div>'''

    # Source link
    source_html = ""
    if source_url:
        source_html = f'<div class="source-link"><a href="{source_url}" target="_blank" rel="noopener">View original article ↗</a></div>'

    # Logo
    logo_html = f'<img src="{t["logo_url"]}" alt="{site_name}" class="logo">' if t["logo_url"] else ""

    # Footer
    footer_html = ""
    if t["footer_text"]:
        footer_html = f'<footer><p>{t["footer_text"]}</p></footer>'

    # Collection sidebar index (if provided)
    col_nav = ""
    if collection_index:
        col_items = ""
        for item in collection_index:
            active = "active" if item.get("title") == title else ""
            col_items += f'<li class="{active}"><a href="/article/{item["file"]}">{item["title"]}</a></li>'
        col_nav = f'<nav class="col-nav"><h3>{collection}</h3><ul>{col_items}</ul></nav>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="description" content="{meta.get('description', '')}">
<title>{title} — {site_name}</title>
<style>
:root {{
    --accent: {t['accent']};
    --accent-light: {t['accent_light']};
    --text: {t['text']};
    --text-sec: {t['text_secondary']};
    --border: {t['border']};
    --bg: {t['bg']};
    --max-width: {t['max_width']};
    --toc-width: {t['toc_width']};
    --font: {t['font_family']};
}}
*, *::before, *::after {{ box-sizing: border-box; }}
body {{ font-family: var(--font); color: var(--text); background: var(--bg);
    margin: 0; line-height: 1.7; font-size: 16px; }}

/* Header bar */
.site-header {{ background: var(--accent); color: white; padding: 0.75rem 2rem;
    display: flex; align-items: center; gap: 1rem; }}
.site-header .logo {{ height: 32px; }}
.site-header .site-title {{ font-weight: 700; font-size: 1.1rem; }}
.site-header a {{ color: white; text-decoration: none; }}
.site-header .nav-links {{ margin-left: auto; display: flex; gap: 1.25rem; font-size: 0.9rem; }}
.site-header .nav-links a:hover {{ opacity: 0.8; }}

/* Breadcrumb */
.breadcrumb {{ padding: 0.6rem 2rem; font-size: 0.85rem; color: var(--text-sec);
    border-bottom: 1px solid var(--border); background: #fafafa; }}
.breadcrumb a {{ color: var(--accent); text-decoration: none; }}
.breadcrumb a:hover {{ text-decoration: underline; }}
.breadcrumb .sep {{ margin: 0 0.2rem; color: #ccc; }}

/* Layout */
.page {{ display: flex; max-width: var(--max-width); margin: 0 auto;
    padding: 2rem 1.5rem; gap: 2.5rem; }}

/* TOC sidebar */
.toc {{ position: sticky; top: 2rem; flex: 0 0 var(--toc-width); max-height: calc(100vh - 4rem);
    overflow-y: auto; padding-right: 1rem; border-right: 2px solid var(--border); }}
.toc h2 {{ font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--text-sec); margin: 0 0 0.75rem 0; }}
.toc ul {{ list-style: none; padding: 0; margin: 0; }}
.toc li a {{ display: block; padding: 0.3rem 0.5rem; color: var(--text-sec);
    text-decoration: none; font-size: 0.88rem; border-left: 3px solid transparent;
    transition: all 0.15s ease; border-radius: 0 4px 4px 0; }}
.toc li a:hover, .toc li a.active {{ color: var(--accent); border-left-color: var(--accent);
    background: var(--accent-light); }}
.toc-h3 a {{ padding-left: 1.25rem; font-size: 0.82rem; }}

/* Collection nav */
.col-nav {{ margin-top: 2rem; padding-top: 1rem; border-top: 1px solid var(--border); }}
.col-nav h3 {{ font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.06em;
    color: var(--text-sec); margin: 0 0 0.5rem; }}
.col-nav ul {{ list-style: none; padding: 0; margin: 0; }}
.col-nav li a {{ display: block; padding: 0.25rem 0.5rem; font-size: 0.82rem;
    color: var(--text-sec); text-decoration: none; border-radius: 4px; }}
.col-nav li a:hover {{ background: var(--accent-light); color: var(--accent); }}
.col-nav li.active a {{ color: var(--accent); font-weight: 600; }}

/* Content */
.content {{ flex: 1; min-width: 0; }}
.content h1 {{ font-size: 2rem; font-weight: 700; margin: 0 0 0.25rem 0;
    line-height: 1.3; }}
.content h2 {{ font-size: 1.35rem; font-weight: 600; margin: 2.5rem 0 0.75rem;
    padding-top: 1.25rem; border-top: 1px solid var(--border); }}
.content h2:first-of-type {{ border-top: none; padding-top: 0; }}
.content h3 {{ font-size: 1.1rem; font-weight: 600; margin: 1.5rem 0 0.5rem; }}
.content p {{ margin: 0.75rem 0; }}
.content img {{ max-width: 100%; height: auto; border-radius: 8px;
    border: 1px solid var(--border); margin: 1rem 0;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
.content hr {{ border: none; border-top: 1px solid var(--border); margin: 2rem 0; }}
.content ul, .content ol {{ padding-left: 1.5rem; margin: 0.75rem 0; }}
.content li {{ margin: 0.35rem 0; }}
.content a {{ color: var(--accent); text-decoration: none; }}
.content a:hover {{ text-decoration: underline; }}
.content blockquote {{ border-left: 3px solid var(--accent); margin: 1rem 0;
    padding: 0.5rem 1rem; background: var(--accent-light); border-radius: 0 6px 6px 0; }}
.content code {{ background: #f4f4f5; padding: 0.15rem 0.4rem; border-radius: 4px;
    font-size: 0.9em; }}
.content pre {{ background: #f4f4f5; padding: 1rem; border-radius: 8px;
    overflow-x: auto; font-size: 0.88rem; }}

/* Meta banner */
.meta-banner {{ background: var(--accent-light); border-radius: 8px; padding: 0.75rem 1rem;
    margin-bottom: 1.5rem; font-size: 0.85rem; color: var(--text-sec); }}
.meta-items {{ display: flex; flex-wrap: wrap; gap: 0.25rem; align-items: center; }}
.tags {{ margin-top: 0.5rem; display: flex; flex-wrap: wrap; gap: 0.35rem; }}
.tag {{ background: var(--accent); color: white; padding: 0.12rem 0.5rem;
    border-radius: 10px; font-size: 0.72rem; font-weight: 500; }}
.source-link {{ margin-top: 2rem; padding-top: 1rem; border-top: 1px solid var(--border);
    font-size: 0.85rem; }}
.source-link a {{ color: var(--accent); }}

/* Footer */
footer {{ max-width: var(--max-width); margin: 3rem auto 0; padding: 1.5rem 2rem;
    border-top: 1px solid var(--border); text-align: center;
    font-size: 0.85rem; color: var(--text-sec); }}

/* Responsive */
@media (max-width: 768px) {{
    .page {{ flex-direction: column; padding: 1rem; }}
    .toc {{ position: static; flex: none; border-right: none;
        border-bottom: 2px solid var(--border); padding: 0 0 1rem 0;
        margin-bottom: 1rem; max-height: none; }}
    .site-header {{ padding: 0.75rem 1rem; }}
    .breadcrumb {{ padding: 0.5rem 1rem; }}
}}

/* Scroll-spy active state */
.toc li a.active {{ font-weight: 600; }}

/* Print */
@media print {{
    .site-header, .toc, .breadcrumb, .col-nav, .source-link {{ display: none; }}
    .page {{ display: block; padding: 0; }}
}}
</style>
</head>
<body>
<div class="site-header">
    {logo_html}
    <span class="site-title"><a href="/">{site_name}</a></span>
    <div class="nav-links">
        <a href="/">Home</a>
        <a href="/search">Search</a>
    </div>
</div>
<div class="breadcrumb">{breadcrumb_html}</div>
<div class="page">
    <div style="flex: 0 0 var(--toc-width);">
        {toc_html}
        {col_nav}
    </div>
    <article class="content">
        <h1>{title}</h1>
        {meta_banner}
        {html_body}
        {source_html}
    </article>
</div>
{footer_html}
<script>
document.addEventListener('DOMContentLoaded', () => {{
    const tocLinks = document.querySelectorAll('.toc a');
    const headings = [];
    tocLinks.forEach(link => {{
        const id = link.getAttribute('href').slice(1);
        const el = document.getElementById(id);
        if (el) headings.push({{ el, link }});
    }});
    if (!headings.length) return;
    const obs = new IntersectionObserver(entries => {{
        entries.forEach(entry => {{
            if (entry.isIntersecting) {{
                tocLinks.forEach(l => l.classList.remove('active'));
                const m = headings.find(h => h.el === entry.target);
                if (m) m.link.classList.add('active');
            }}
        }});
    }}, {{ rootMargin: '-80px 0px -60% 0px', threshold: 0.1 }});
    headings.forEach(h => obs.observe(h.el));
}});
</script>
</body>
</html>"""


def render_file(md_path: Path | str, theme: dict | None = None,
                collection_index: list[dict] | None = None) -> str:
    """Convenience: read a .md file and render it."""
    p = Path(md_path)
    raw = p.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(raw)
    if theme is None:
        theme = DEFAULT_THEME
    return render_markdown(body, meta, theme, collection_index)
