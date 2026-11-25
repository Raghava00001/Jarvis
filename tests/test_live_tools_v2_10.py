"""
Gemini Live voice tools and shared handlers, fixed after calling every tool the
way Gemini does (v2.10). Each test pins one bug.
"""

import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _engine(server=None):
    import jarvis.core.gemini_live_engine as g
    eng = object.__new__(g.GeminiLiveEngine)
    eng.server, eng.perception = server, None
    eng._push_to_chat = MagicMock()
    eng.audio_in_queue = None
    return eng


def _call(eng, name, args):
    resp = eng._execute_tool(SimpleNamespace(name=name, args=args, id="t"))
    out = getattr(resp, "response", resp)
    return out.get("result", out) if isinstance(out, dict) else out


# ── alarms: Gemini passes "7 am" as text; every alarm rang at midnight ──────

@pytest.mark.parametrize("text,when", [
    ("set alarm for 7 am wake up", "7 am"), ("wake me at 6:30 pm", "6:30 pm"),
    ("in 10 minutes", "in 10 minutes"), ("set an alarm for noon", "12:00 pm"), ("no time here", None),
])
def test_alarm_time_from_text(text, when):
    from jarvis.core.intent_handlers import alarm_time_text
    assert alarm_time_text(text) == when


def test_alarm_tool_sets_the_spoken_time():
    alarms = MagicMock()
    alarms.set_alarm.return_value = True
    # Tools get the same handler context as the router (server._handler_context)
    server = SimpleNamespace(alarm_system=alarms, _handler_context=lambda: {"alarm_system": alarms, "title": "sir"})
    out = _call(_engine(server), "set_alarm", {"time": "7 am", "label": "wake up"})
    assert out.startswith("Alarm set for 7 am")
    assert alarms.set_alarm.call_args[0][0] == "7 am"


# ── system status read zeros when the caller passed no stats ────────────────

def test_system_status_reads_the_machine():
    from jarvis.core.intent_handlers import handle_system_status
    stats = {"cpu": 12, "memory": 40, "disk": 50, "battery": 80, "charging": False}
    with patch("jarvis.gui.data_providers.get_system_stats", return_value=stats):
        assert "CPU at 12%" in handle_system_status("system status", {}, {}).response
        assert handle_system_status("battery level", {}, {}).response.startswith("Battery at 80%")


# ── news: the topic was ignored ─────────────────────────────────────────────

def test_news_with_a_topic_is_a_topic_briefing():
    from jarvis.core import intent_handlers as h
    with patch.object(h, "handle_search_news", return_value=h.HandlerResult(True, "[briefing]")) as search:
        r = h.handle_news("", {"topic": "cricket"}, {"news_handler": object()})
    assert r.response == "[briefing]" and search.call_args[0][1] == {"keyword": "cricket"}


# ── calendar called a method that doesn't exist: always "no events" ─────────

def test_calendar_reads_todays_events():
    from jarvis.core import intent_handlers as h
    from jarvis.core.calendar_manager import CalendarEvent
    cal = MagicMock()
    cal.get_today_events.return_value = [CalendarEvent(1, "Standup", datetime(2026, 11, 25, 9, 30))]
    with patch.object(h, "shared", return_value=cal):
        r = h.handle_calendar("events today", {}, {"title": "sir"})
    assert r.response == "Today's events: Standup at 9:30 AM"


# ── habits: add called tracker.add_habit(), which doesn't exist ─────────────

def test_adding_a_habit():
    from jarvis.core import intent_handlers as h
    tracker = MagicMock(spec=["create_habit", "list_habits"])
    with patch.object(h, "shared", return_value=tracker):
        r = h.handle_habit("add habit stretch", {}, {"title": "sir"})
    assert r.success and "stretch" in r.response
    tracker.create_habit.assert_called_once()


# ── music: media keys, not Ctrl+Right / Space in whatever window has focus ──

@pytest.mark.parametrize("handler,key", [("handle_next_track", "next_track"),
                                         ("handle_previous_track", "previous_track"),
                                         ("handle_pause_music", "play_pause")])
def test_music_uses_media_keys(handler, key):
    from jarvis.core import intent_handlers as h
    import pyautogui
    with patch(f"jarvis.core.music_handler.MediaKeyController.{key}", return_value=True) as mk, \
         patch.object(pyautogui, "press") as press, patch.object(pyautogui, "hotkey") as hotkey:
        getattr(h, handler)("", {}, {})
    mk.assert_called_once()
    press.assert_not_called(); hotkey.assert_not_called()


def test_fast_path_pause_uses_the_media_key():
    from jarvis.gui.fast_path import try_fast_path
    import pyautogui
    with patch("jarvis.core.music_handler.MediaKeyController.play_pause", return_value=True) as mk, \
         patch.object(pyautogui, "press") as press:
        out = try_fast_path(SimpleNamespace(hud_perception=SimpleNamespace(user_title="sir")), "pause music")
    assert out.startswith("Paused") and mk.called and not press.called


# ── computer_settings: "volume_up" never matched "up"; next_tab was "noted" ─

def test_computer_settings_sends_words_not_identifiers():
    import jarvis.core.gemini_live_engine as g
    seen = {}
    def fake_volume(cmd, entities, context):
        seen["cmd"] = cmd
        return SimpleNamespace(response="ok")
    with patch.dict(g.HANDLER_MAP, {"volume": fake_volume}):
        _call(_engine(), "computer_settings", {"action": "volume_up"})
    assert seen["cmd"] == "volume up"


def test_computer_settings_screen_keys_are_pressed():
    import pyautogui
    with patch.object(pyautogui, "hotkey") as hotkey, \
         patch("jarvis.core.screen_control.focus_away_from_jarvis", return_value=None):
        out = _call(_engine(), "computer_settings", {"action": "next_tab"})
    hotkey.assert_called_once_with("ctrl", "tab")
    assert "noted" not in out


# ── send_email said "sent" whatever happened ───────────────────────────────

def test_send_email_reports_the_real_outcome():
    mail = MagicMock()
    mail.send_email.return_value = "Email sending is not configured, sir. Set JARVIS_EMAIL_PASSWORD in .env."
    out = _call(_engine(SimpleNamespace(email_handler_obj=mail)), "send_email",
                {"to": "a@example.com", "subject": "s", "body": "b"})
    assert "not configured" in out and "sent to" not in out


# ── YouTube: no blind key presses ──────────────────────────────────────────

def test_youtube_opens_the_first_video_without_pressing_keys():
    from jarvis.core import youtube_play
    import pyautogui
    page = '... "videoId":"dQw4w9WgXcQ" ...'
    resp = MagicMock()
    resp.__enter__.return_value.read.return_value = page.encode()
    with patch("urllib.request.urlopen", return_value=resp), patch("webbrowser.open") as wb, \
         patch.object(pyautogui, "press") as press:
        youtube_play.play_on_youtube("never gonna", wait=True)
    wb.assert_called_once_with("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    press.assert_not_called()
    for f in ("jarvis/gui/fast_path.py", "jarvis/core/gemini_live_engine.py"):
        assert "presses=8" not in (ROOT / f).read_text(encoding="utf-8")


# ── screen questions: one implementation, nothing saved to disk ─────────────

def test_read_screen_tool_uses_screen_vision():
    from jarvis.core import screen_vision
    with patch.object(screen_vision, "vision_available", return_value=True), \
         patch.object(screen_vision, "ask_about_screen", return_value="A code editor.") as ask:
        out = _call(_engine(), "read_screen", {"question": "what is this"})
    assert out == "A code editor." and ask.call_args[0][0] == "what is this"


# ── conversation search read "ChatMessage(id=857, ...)" ─────────────────────

def test_conversation_search_shows_the_words():
    import jarvis.gui.websocket_server as ws
    srv = object.__new__(ws.JARVISWebSocketServer)
    msg = SimpleNamespace(role="user", content="what's the weather", timestamp="2026-11-22T23:55:00")
    srv._chat_history = MagicMock()
    srv._chat_history.search.return_value = [msg]
    with patch.object(type(srv), "chat_history", property(lambda self: self._chat_history)):
        out = srv.recall_conversation("weather")
    assert "[Nov 22, 11:55 PM] You: what's the weather" in out


# ── the tool table matches what Gemini is told it can call ──────────────────

def test_every_declared_tool_has_a_method_and_vice_versa():
    import jarvis.core.gemini_live_engine as g
    declared = {d["name"] for d in g.TOOL_DECLARATIONS}
    table = set(_engine()._tools())
    assert declared == table, {"declared, no method": declared - table, "method, not declared": table - declared}


# ── a reply with no spoken input (typed in the HUD) never reached the chat ──

def test_reply_to_typed_input_reaches_the_chat():
    """_now was set only when the user's speech was transcribed; with typed
    input the reply branch raised NameError, swallowed by an except."""
    eng = _engine()
    eng._current_turn_id, eng._wake_gate, eng._turn_addressed = 1, False, False
    eng._turn_suppressed, eng._muted, eng._raw_in = False, False, ""
    eng.is_awake = lambda: False
    sc = SimpleNamespace(input_transcription=None, turn_complete=True,
                         output_transcription=SimpleNamespace(text="It's 4 PM, sir."))
    in_buf, out_buf = [], []
    eng._on_server_content(sc, in_buf, out_buf)
    eng._push_to_chat.assert_called_once()
    assert eng._push_to_chat.call_args[0][0] == "It's 4 PM, sir." and eng._push_to_chat.call_args.kwargs["role"] == "jarvis"
    assert out_buf == []
