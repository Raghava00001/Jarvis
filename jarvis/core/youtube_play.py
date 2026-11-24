"""
"Play X on YouTube": open the first matching video directly.

This used to open the search page, wait 3.5 s, and press Tab 8 times and
Enter, blind. Whatever window had focus by then got those keys (and a slow
page meant the wrong element was "clicked"). Now the first video's link is
read from the results page in a background thread and opened; if that fails,
the search page opens. No key presses.
"""

import logging
import re
import threading
import urllib.parse
import urllib.request
import webbrowser
from typing import Optional

_log = logging.getLogger(__name__)

_VIDEO_ID = re.compile(r'"videoId":"([A-Za-z0-9_-]{11})"')


def search_url(query: str) -> str:
    return f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"


def first_video_url(query: str, timeout: float = 6.0) -> Optional[str]:
    """The watch URL of the first search result, or None."""
    try:
        req = urllib.request.Request(search_url(query), headers={"User-Agent": "Mozilla/5.0",
                                                                 "Accept-Language": "en"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            html = r.read(2_000_000).decode("utf-8", errors="replace")
    except Exception as e:
        _log.warning(f"[YOUTUBE] Search failed: {e}")
        return None
    m = _VIDEO_ID.search(html)
    return f"https://www.youtube.com/watch?v={m.group(1)}" if m else None


def play_on_youtube(query: str, wait: bool = False) -> None:
    """Open the first video for query (or the search page). Returns at once
    unless wait=True: the lookup is a network call."""
    def _open():
        url = first_video_url(query) or search_url(query)
        _log.info(f"[YOUTUBE] Opening {url}")
        webbrowser.open(url)
    if wait:
        _open()
    else:
        threading.Thread(target=_open, daemon=True, name="YouTubePlay").start()
