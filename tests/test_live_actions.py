"""
Voice actions must DO what JARVIS says they did (v2.9.1).

Found in real use: "brightness decreased" while nothing changed. Gemini's voice
tools called the volume/brightness handler without saying up or down, the
handler answered "Adjusting brightness" anyway, and SystemControl spoke its own
"Brightness decreased" (a second voice) even when every method had failed.
Also: "next tab" by voice was an unknown action; gestures showed as ON in the
HUD while off and couldn't be switched on by voice; a follow-up after a long
answer was muted because the awake window ran out while JARVIS was talking.
"""

import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ─── fakes for the lowest layer only ───────────────────────────────────────

class FakeSpeaker:
    def __init__(self, level=0.5):
        self.level, self.muted = level, False

    def GetMasterVolumeLevelScalar(self):
        return self.level

    def SetMasterVolumeLevelScalar(self, v, _):
        self.level = v

    def GetMute(self):
        return self.muted

    def SetMute(self, m, _):
        self.muted = m


@pytest.fixture
def sc():
    """A real SystemControl on a pretend speaker and screen."""
    import jarvis.core.system_control as m
    speaker, screen = FakeSpeaker(), {"b": 50, "obeys": True}

    def set_b(v, *a, **k):
        if screen["obeys"]:
            screen["b"] = v

    perception = MagicMock(user_title="sir")
    with patch.object(m.SystemControl, "_endpoint", lambda self: speaker), \
         patch.object(m, "BRIGHTNESS_AVAILABLE", True), \
         patch.object(m, "sbc", SimpleNamespace(get_brightness=lambda *a, **k: [screen["b"]],
                                                set_brightness=set_b), create=True), \
         patch.object(m.time, "sleep", lambda s: None), \
         patch.object(m.subprocess, "run", MagicMock()):
        obj = object.__new__(m.SystemControl)
        obj.perception = perception
        obj.speaker, obj.screen = speaker, screen
        yield obj
    perception.speak.assert_not_called()      # never a second voice


@pytest.mark.parametrize("text,expected", [
    ("volume_down", ("down", None)), ("turn the brightness down", ("down", None)),
    ("brightness up", ("up", None)), ("increase the volume", ("up", None)),
    ("dim the screen", ("down", None)), ("set volume to 40", ("set", 40)),
    ("brightness 75 percent", ("set", 75)), ("max volume", ("set", 100)),
    ("mute", ("mute", None)), ("unmute", ("unmute", None)), ("brightness", None),
])
def test_requests_are_understood(text, expected):
    from jarvis.core.system_control import parse_level_request
    assert parse_level_request(text) == expected


def test_volume_changes_and_the_reply_says_the_real_level(sc):
    assert sc.adjust("volume", "down") == "Volume is now 40%, sir."
    assert round(sc.speaker.level * 100) == 40
    assert sc.adjust("volume", "set to 75") == "Volume is now 75%, sir."
    assert sc.adjust("volume", "mute") == "Sound muted, sir." and sc.speaker.muted


def test_brightness_changes(sc):
    assert sc.adjust("brightness", "down") == "Brightness is now 30%, sir."
    assert sc.screen["b"] == 30


def test_brightness_failure_is_reported_not_hidden(sc):
    """The display ignored the change: JARVIS used to say 'Brightness decreased'."""
    sc.screen["obeys"] = False
    reply = sc.adjust("brightness", "down")
    assert "didn't change" in reply and sc.screen["b"] == 50


def test_already_at_the_limit(sc):
    sc.screen["b"] = 100
    assert sc.adjust("brightness", "up") == "The brightness is already at 100%, sir."


def test_old_entry_points_return_the_real_result(sc):
    assert sc.brightness_down() == "Brightness is now 30%, sir."
    assert sc.volume_up() == "Volume is now 60%, sir."


def test_voice_tool_without_an_action_still_acts(sc):
    """Gemini's tools pass the action only in the command text."""
    from jarvis.core.intent_handlers import handle_brightness, handle_volume
    r = handle_brightness("brightness down", {"level": ""}, {"system_control": sc, "title": "sir"})
    assert r.response == "Brightness is now 30%, sir." and sc.screen["b"] == 30
    r = handle_volume("volume_down", {"level": ""}, {"system_control": sc, "title": "sir"})
    assert r.response == "Volume is now 40%, sir."


# ─── the live engine's tools ───────────────────────────────────────────────

def _engine(server):
    import jarvis.core.gemini_live_engine as g
    eng = object.__new__(g.GeminiLiveEngine)
    eng.server, eng.perception = server, None
    eng._push_to_chat = MagicMock()
    return eng


def _call(eng, name, args):
    resp = eng._execute_tool(SimpleNamespace(name=name, args=args, id="t"))
    out = getattr(resp, "response", resp)
    return out.get("result", out) if isinstance(out, dict) else out


def _server(**kw):
    s = SimpleNamespace(hud_perception=SimpleNamespace(user_title="sir"))
    for k in ("youtube_downloader", "whatsapp_handler", "reminder_manager", "entertainment", "news_handler",
              "alarm_manager", "screen_control", "dictionary_handler", "chat_history", "context_memory",
              "weather_handler", "knowledge", "ocr_handler", "screenshot_handler", "alarm_system",
              "face_recognition", "system_control"):
        setattr(s, k, None)
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def test_live_brightness_tool_changes_brightness(sc):
    eng = _engine(_server(system_control=sc))
    assert _call(eng, "brightness_control", {"action": "down"}) == "Brightness is now 30%, sir."
    assert _call(eng, "computer_settings", {"action": "volume_down"}) == "Volume is now 40%, sir."


def test_live_next_tab_presses_the_keys_in_your_app():
    import pyautogui
    eng = _engine(_server())
    with patch.object(pyautogui, "hotkey") as hk, \
         patch("jarvis.core.screen_control.focus_away_from_jarvis") as focus:
        _call(eng, "screen_action", {"action": "next tab"})
    focus.assert_called_once()
    hk.assert_called_once_with("ctrl", "tab")


def test_gestures_can_be_switched_by_voice():
    calls = []
    srv = _server(set_gesture_enabled=lambda on, title='sir': calls.append(on) or "Gesture control on.")
    eng = _engine(srv)
    assert _call(eng, "gesture_control", {"enabled": True}) == "Gesture control on."
    _call(eng, "gesture_control", {"enabled": "false"})
    assert calls == [True, False]


# ─── HUD shows the real gesture state ──────────────────────────────────────

def test_hud_gesture_switch_starts_off():
    from jarvis.gui.state_controller import UIStateController
    assert UIStateController().gesture_enabled is False


def test_switching_gestures_updates_what_the_hud_shows(tmp_path):
    import jarvis.gui.websocket_server as ws
    srv = object.__new__(ws.JARVISWebSocketServer)
    srv.GESTURE_PREFS = tmp_path / "prefs.json"
    srv.state_manager = SimpleNamespace(gesture_enabled=False)
    type(srv).gesture_controller = property(lambda self: SimpleNamespace(active=True))
    try:
        srv.set_gesture_enabled(True)
        assert srv.state_manager.gesture_enabled is True
        srv.set_gesture_enabled(False)
        assert srv.state_manager.gesture_enabled is False
    finally:
        del type(srv).gesture_controller


# ─── conversation: no muted follow-ups, no cut-off sentences ───────────────

def _wake_engine():
    import jarvis.core.gemini_live_engine as g
    eng = object.__new__(g.GeminiLiveEngine)
    eng._wake_gate, eng._awake_until, eng._speaking_until = True, 0.0, 0.0
    return eng


def test_awake_window_counts_from_when_jarvis_stops_speaking():
    """A story plays for a minute; the window used to run out meanwhile, and
    'continue the story' got a muted reply."""
    import jarvis.core.gemini_live_engine as g
    eng = _wake_engine()
    now = time.time()
    eng._awake_until = now - 1                    # window from the wake word has passed...
    eng._speaking_until = now + 60                # ...but JARVIS is still telling the story
    assert eng.is_awake(now + 30)
    assert eng.is_awake(now + 60 + g.AWAKE_WINDOW_S - 1)   # follow-up after it finishes
    assert not eng.is_awake(now + 60 + g.AWAKE_WINDOW_S + 1)


def test_asleep_without_wake_word_or_speech():
    eng = _wake_engine()
    assert not eng.is_awake()


def test_live_session_waits_for_the_end_of_your_sentence():
    import jarvis.core.gemini_live_engine as g
    eng = object.__new__(g.GeminiLiveEngine)
    eng.server = eng.perception = None
    cfg = eng._build_config()
    vad = cfg.realtime_input_config.automatic_activity_detection
    assert vad.silence_duration_ms >= 800
    # The Gemini API rejects a transcription language: the session wouldn't start
    assert not cfg.input_audio_transcription.language_codes
    assert "Reply in English by default" in eng._get_system_prompt()


def test_conversation_keeps_going_without_saying_jarvis_each_time():
    """Found in use: 'Yes sir', 'Hello', 'continue the story' were heard,
    answered by Gemini, and the answers muted after 20-30 s."""
    import jarvis.core.gemini_live_engine as g
    assert g.AWAKE_WINDOW_S >= 180
    eng = _wake_engine()
    assert eng.note_user_speech("Hey Jarvis") is True
    now = time.time()
    eng._speaking_until = now + 5                         # JARVIS answers
    assert eng.is_awake(now + 5 + 120)                    # two minutes later: still listening
    assert eng.note_user_speech("hello") is True


def test_good_night_is_answered_then_jarvis_sleeps():
    eng = _wake_engine()
    eng.note_user_speech("Jarvis what's the time")
    assert eng.note_user_speech("ok good night") is True  # the goodbye gets a reply
    assert eng._sleep_after_reply
    eng.sleep()                                           # after that reply
    eng._speaking_until = time.time() + 3                 # goodbye still playing
    assert not eng.is_awake(time.time() + 10)
    assert eng.note_user_speech("hello") is False         # needs the wake word again
    assert eng.note_user_speech("Jarvis, are you there") is True


def test_story_is_handed_to_gemini_to_narrate():
    """Gemini got the bare story and replied 'Sweet dreams, sir' without telling it."""
    from jarvis.core import intent_handlers
    eng = _engine(_server())
    fake = MagicMock(return_value=SimpleNamespace(response="Once upon a time, a kid could fly."))
    with patch.dict(intent_handlers.HANDLER_MAP, {"story": fake}):
        out = _call(eng, "tell_story", {"genre": "fantasy", "topic": "a kid with super powers"})
    assert out.startswith("Narrate this story to the user now")
    assert out.endswith("Once upon a time, a kid could fly.")
    assert fake.call_args.kwargs["cmd"] == "tell me a fantasy story about a kid with super powers"
