"""
Minimal RSS parsing with the standard library.

The news code used BeautifulSoup(content, "xml"), which needs the lxml package.
lxml was never a dependency, so parsing always raised, a bare `except` swallowed
it, and the HUD silently showed hard-coded placeholder headlines instead of news.

parse_rss_items() returns objects with the same attribute shape the existing
code reads (item.title.text, item.link.text, item.pubDate.text), so call sites
only change the parse line. A missing child element is None, as with bs4.
"""

import xml.etree.ElementTree as ET
from types import SimpleNamespace
from typing import List, Optional
from urllib.parse import quote_plus

_FIELDS = ("title", "link", "pubDate", "description", "source")


def _node(element) -> Optional[SimpleNamespace]:
    if element is None:
        return None
    return SimpleNamespace(text=(element.text or ""))


def parse_rss_items(content: bytes, limit: Optional[int] = None) -> List[SimpleNamespace]:
    """Parse an RSS 2.0 feed into items exposing .title/.link/.pubDate/.description/.source."""
    root = ET.fromstring(content)
    items = []
    for element in root.iter("item"):
        items.append(SimpleNamespace(**{f: _node(element.find(f)) for f in _FIELDS}))
        if limit is not None and len(items) >= limit:
            break
    return items


def google_news_search_url(query: str) -> str:
    """Google News RSS search URL with the query safely encoded."""
    return f"https://news.google.com/rss/search?q={quote_plus(query)}"
