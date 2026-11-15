"""sitemap.xml and robots.txt. Unreviewed pages carry noindex, so they are left out of the sitemap as well."""

from datetime import date
from xml.sax.saxutils import escape

from .urls import absolute


def sitemap_xml(pages: list[tuple[str, date | None]]) -> str:
    """pages: (site-relative path, last modified or None)."""
    urls = "\n".join(
        f"  <url><loc>{escape(absolute(path))}</loc>{f'<lastmod>{modified.isoformat()}</lastmod>' if modified else ''}</url>"
        for path, modified in pages
    )
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}\n</urlset>\n'


def robots_txt() -> str:
    return f"User-agent: *\nAllow: /\n\nSitemap: {absolute('/sitemap.xml')}\n"
