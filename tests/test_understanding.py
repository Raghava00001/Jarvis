"""
Understanding-layer fixes (v2.6): keyword fallback, clarification, entities,
search routing, screen control, WhatsApp contact, per-city weather cache.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="module")
def model():
    from jarvis.core.intent_model import IntentModel
    return IntentModel(lazy=True)


# ─── keyword fallback: whole words, no false positives ────────────────────

@pytest.mark.parametrize("text", [
    "translate hello to spanish",  # was: greeting
    "sometimes I wonder",          # was: get_time ("time" in "sometimes")
    "brunch ideas",                # was: open_app ("run" in "brunch")
    "the alarming news",           # alarm only as a whole word
])
def test_keyword_fallback_no_substring_matches(model, text):
    intent, _ = model.classify_keyword(text)
    assert intent not in ("greeting", "get_time", "open_app", "set_alarm")


@pytest.mark.parametrize("text,expected", [
    ("remind me to call mom", "set_reminder"),   # was: set_alarm
    ("set a timer", "set_timer"),
    ("turn up the volume", "volume_up"),
    ("turn the volume down", "volume_down"),
    ("whats the time", "get_time"),
    ("whats the date", "get_date"),
    ("hello there", "greeting"),
    ("open chrome", "open_app"),
    ("weather in paris", "weather"),
])
def test_keyword_fallback_positives(model, text, expected):
    assert model.classify_keyword(text)[0] == expected


# ─── decision engine: no "are you sure?" for harmless intents ─────────────

@pytest.mark.parametrize("intent", ["greeting", "help", "goodbye", "get_time", "weather", "how_are_you"])
def test_low_risk_intents_never_clarify(intent):
    from jarvis.core.decision_engine import DecisionEngine
    engine = object.__new__(DecisionEngine)
    assert engine._consider_confidence(intent, 0.55) is None


def test_side_effect_intents_still_clarify_when_unsure():
    from jarvis.core.decision_engine import DecisionEngine
    engine = object.__new__(DecisionEngine)
    decision = engine._consider_confidence("send_whatsapp", 0.55)
    assert decision is not None and "sure" in decision.message


def test_clarify_question_is_answerable(monkeypatch):
    """'Should I proceed?' used to be a dead end; 'yes' now runs the original command."""
    import asyncio
    import jarvis.gui.websocket_server as w
    srv = object.__new__(w.JARVISWebSocketServer)
    srv._pending_power_action = None
    srv.hud_perception = MagicMock(assistant_name="JARVIS", user_title="sir")
    srv.quiet_mode = False
    srv._route_through_router = MagicMock(return_value="Message sent to dad.")
    srv._pending_clarify = ("send a whatsapp to dad saying hi", 9e18)
    reply = asyncio.run(srv.process_command("yes", None))
    srv._route_through_router.assert_called_once_with("send a whatsapp to dad saying hi", force=True)
    assert reply == "Message sent to dad."
    srv._pending_clarify = ("send a whatsapp to dad saying hi", 9e18)
    assert "never mind" in asyncio.run(srv.process_command("cancel", None)).lower()


# ─── entities ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,city", [
    ("weather in london", "london"),
    ("what is the weather in new york", "new york"),  # was "new"
    ("weather like in san francisco today?", "san francisco"),
])
def test_multi_word_cities(text, city):
    from jarvis.core.intent_classifier import classify_intent
    assert classify_intent(text) == ("weather", {"city": city})


def test_weather_cache_is_per_city():
    """'weather in london' used to return the cached Hyderabad result."""
    from jarvis.core.weather_handler import WeatherHandler
    wh = object.__new__(WeatherHandler)
    wh.cached_weather = wh.cache_time = None
    wh.cache_duration = 600
    wh.api_key = ""
    wh.perception = None
    wh._get_weather_free = lambda city: {"city": city, "temp_c": 1}
    assert wh.get_weather("hyderabad")["city"] == "hyderabad"
    assert wh.get_weather("london")["city"] == "london"
    assert wh.get_weather("london")["city"] == "london"


# ─── search vs. question ──────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("what is quantum computing", "conversation"),   # v2.2 alias opened a Google search
    ("search for python tutorials", "search"),
    ("google the weather", "search"),
    ("please look up cats", "search"),
])
def test_search_only_when_asked(text, expected):
    from jarvis.core.intent_handlers import resolve_brain_intent
    assert resolve_brain_intent("search_web", {}, text)[0] == expected


def test_search_query_cleaned_and_encoded():
    from jarvis.core.intent_handlers import handle_search
    with patch("webbrowser.open") as wb:
        res = handle_search("search for c++ & rust", {"query": "for c++ & rust"}, {"title": "sir"})
    assert "'c++ & rust'" in res.response
    assert wb.call_args[0][0].endswith("q=c%2B%2B+%26+rust")


# ─── handlers ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,keys", [
    ("next tab", ("ctrl", "tab")),
    ("previous tab", ("ctrl", "shift", "tab")),
    ("zoom in", ("ctrl", "+")),
    ("minimize window", ("win", "down")),
])
def test_screen_control_handler_works(text, keys):
    """It imported a non-existent ScreenController, so voice screen control never worked."""
    import pyautogui
    from jarvis.core.intent_handlers import handle_screen_control
    with patch.object(pyautogui, "hotkey") as hotkey:
        res = handle_screen_control(text, {}, {"title": "sir"})
    assert res.success
    hotkey.assert_called_once_with(*keys)


def test_screen_control_unknown_action_fails_cleanly():
    from jarvis.core.intent_handlers import handle_screen_control
    assert not handle_screen_control("do a barrel roll", {}, {}).success


def test_whatsapp_contact_parsing():
    from jarvis.core.intent_handlers import handle_send_message
    wa = MagicMock()
    wa.send_message.side_effect = lambda c, m: f"Message sent to {c}."
    res = handle_send_message("", {"contact": "to dad", "message": "hi"}, {"whatsapp_handler": wa})
    wa.send_message.assert_called_once_with("dad", "hi")
    assert "to to" not in res.response
    assert not handle_send_message("", {"contact": "dad"}, {"whatsapp_handler": wa}).success
