"""
v2.4: real news instead of invented headlines, honest fallbacks, correct
spoken weather, and a working "lock my screen".

Bugs these pin down:
  * News parsing used BeautifulSoup(..., "xml"), which needs lxml (never a
    dependency). Every fetch raised, a bare except returned [], and the HUD
    showed invented headlines ("AI research achieves breakthrough…") as news.
  * When weather failed, the HUD showed invented numbers (24°, Partly Cloudy).
  * The weather voice reply read keys WeatherHandler never returns, so it said
    "Current conditions in your area: N/A°C, unknown".
  * "lock my screen" had no handler.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>News</title>
<item><title>First real headline - Source A</title><link>https://a.example/1</link>
<pubDate>Sun, 22 Nov 2026 10:00:00 GMT</pubDate></item>
<item><title>Second headline &amp; more - Source B</title><link>https://b.example/2</link></item>
<item><title>Third headline</title></item>
</channel></rss>"""


# ─── RSS parsing ──────────────────────────────────────────────────────────

class TestRss:
    def test_parses_titles_links_and_dates(self):
        from jarvis.core.rss import parse_rss_items
        items = parse_rss_items(FEED)
        assert [i.title.text for i in items] == [
            "First real headline - Source A", "Second headline & more - Source B", "Third headline"]
        assert items[0].link.text == "https://a.example/1"
        assert items[0].pubDate.text.startswith("Sun, 22 Nov 2026")
        assert items[2].link is None and items[2].pubDate is None  # missing -> None, like bs4

    def test_limit(self):
        from jarvis.core.rss import parse_rss_items
        assert len(parse_rss_items(FEED, limit=2)) == 2

    def test_works_without_lxml(self):
        with patch.dict(sys.modules, {"lxml": None, "lxml.etree": None}):
            from jarvis.core.rss import parse_rss_items
            assert len(parse_rss_items(FEED)) == 3

    def test_search_url_is_encoded(self):
        from jarvis.core.rss import google_news_search_url
        url = google_news_search_url("AI & robotics?")
        assert url.endswith("q=AI+%26+robotics%3F")

    def test_no_xml_beautifulsoup_left(self):
        for path in (ROOT / "jarvis").rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            assert 'BeautifulSoup(response.content, "xml")' not in text, path


# ─── News: real headlines, honest fallback ────────────────────────────────

class TestNews:
    def test_news_handler_returns_real_headlines(self, tmp_path):
        from jarvis.core.news_handler import NewsHandler
        handler = NewsHandler(MagicMock())
        handler._load_cache = lambda: {}
        handler._save_cache = lambda cache: None
        with patch("jarvis.core.news_handler.requests.get",
                   return_value=SimpleNamespace(status_code=200, content=FEED)):
            result = handler.get_news("general", 2)
        assert len(result["items"]) == 2
        assert "First real headline" in result["items"][0]

    def test_fallback_says_unavailable_instead_of_inventing(self):
        from jarvis.gui.data_providers import get_news_data, NEWS_UNAVAILABLE
        broken = MagicMock()
        broken.get_news.return_value = {"items": []}
        data = get_news_data(broken, "general", 5)
        assert data["items"] == [NEWS_UNAVAILABLE]
        assert data["unavailable"] is True

    def test_no_invented_headlines_remain(self):
        src = (ROOT / "jarvis/gui/data_providers.py").read_text(encoding="utf-8")
        for invented in ("AI research achieves breakthrough", "Space exploration milestone",
                         "Global markets rally"):
            assert invented not in src


# ─── Weather: honest fallback, correct voice reply ────────────────────────

class TestWeather:
    def test_fallback_has_no_fake_numbers(self):
        from jarvis.gui.data_providers import get_weather_data
        broken = MagicMock()
        broken.get_weather.return_value = None
        data = get_weather_data(broken, "Hyderabad")
        assert data["unavailable"] is True
        assert data["temp"] == "--"
        assert "unavailable" in data["condition"].lower()

    def test_fallback_processor_admits_weather_is_down(self):
        src = (ROOT / "jarvis/gui/fallback_processor.py").read_text(encoding="utf-8")
        assert "if weather.get('unavailable'):" in src

    def test_spoken_weather_uses_real_fields(self):
        from jarvis.core.intent_handlers import handle_weather
        wh = MagicMock()
        wh.get_weather.return_value = {"city": "Hyderabad", "temp_c": 23, "description": "Clear ",
                                       "humidity": 40, "wind_speed_kmh": 9}
        res = handle_weather("weather", {}, {"title": "sir", "weather_handler": wh})
        assert "Hyderabad: 23°C, Clear." in res.response
        assert "wind 9 kilometers" in res.response
        assert "N/A" not in res.response and "unknown" not in res.response


# ─── Lock screen ──────────────────────────────────────────────────────────

class TestLockScreen:
    def test_brain_intent_reaches_handler(self):
        from jarvis.core.intent_handlers import HANDLER_MAP, resolve_brain_intent
        name, _ = resolve_brain_intent("lock_screen", {})
        assert name in HANDLER_MAP

    def test_handler_locks_without_a_shell(self):
        from jarvis.core.intent_handlers import handle_lock_screen
        with patch("jarvis.core.safe_exec.lock_workstation", return_value=True) as lock, \
                patch("subprocess.run") as run, patch("subprocess.Popen") as popen:
            res = handle_lock_screen("lock my screen", {}, {"title": "sir"})
        lock.assert_called_once()
        run.assert_not_called(); popen.assert_not_called()
        assert res.success and "Locking" in res.response

    def test_handler_reports_failure(self):
        from jarvis.core.intent_handlers import handle_lock_screen
        with patch("jarvis.core.safe_exec.lock_workstation", side_effect=OSError("no")):
            res = handle_lock_screen("lock", {}, {})
        assert not res.success

    def test_gemini_lock_tool_has_no_shell(self):
        src = (ROOT / "jarvis/core/gemini_live_engine.py").read_text(encoding="utf-8")
        assert "LockWorkStation\", shell=True" not in src
