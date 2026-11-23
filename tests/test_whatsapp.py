"""
WhatsApp sending: draft first, send only on confirmation.

The old sender pressed Enter on the first search result and said "Message sent"
without checking anything; its window lookup also matched browser tabs, and
focus changes from the background often failed, so keys went to the HUD.
Nothing here touches the real keyboard, clipboard or WhatsApp: the Win32
layer, pyautogui, pyperclip and os.startfile are all fakes.
"""

import asyncio
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

WA_HWND = 4242


class FakeWin:
    """A WhatsApp window that is found and focused unless told otherwise."""

    def __init__(self, present=True, focus_ok=True):
        self.present, self.focus_ok = present, focus_ok
        self.foreground = 0
        self.focus_calls = 0

    def find_whatsapp(self):
        return WA_HWND if self.present else 0

    def focus(self, hwnd):
        self.focus_calls += 1
        if self.focus_ok and self.present:
            self.foreground = hwnd
            return True
        return False

    def is_foreground(self, hwnd):
        return self.foreground == hwnd


@pytest.fixture
def keys():
    """Records every key/paste/launch instead of doing it."""
    import jarvis.core.whatsapp_handler as wa
    log = []
    clip = {"value": "user's clipboard"}
    fake_gui = SimpleNamespace(
        hotkey=lambda *k: log.append(("hotkey",) + k),
        press=lambda k: log.append(("press", k)),
        write=lambda t, interval=0: log.append(("write", t)),
    )
    fake_clip = SimpleNamespace(
        copy=lambda t: clip.__setitem__("value", t),
        paste=lambda: clip["value"],
    )

    def _hotkey(*k):
        if k == ("ctrl", "v"):
            log.append(("paste", clip["value"]))
        else:
            log.append(("hotkey",) + k)
    fake_gui.hotkey = _hotkey

    with patch.object(wa, "pyautogui", fake_gui, create=True), \
         patch.object(wa, "pyperclip", fake_clip, create=True), \
         patch.object(wa, "PYAUTOGUI_AVAILABLE", True), \
         patch.object(wa, "PYPERCLIP_AVAILABLE", True), \
         patch.object(wa.os, "name", "nt"), \
         patch.object(wa.os, "startfile", lambda uri: log.append(("startfile", uri)), create=True), \
         patch.object(wa.time, "sleep", lambda s: None):
        yield SimpleNamespace(log=log, clip=clip)


def _sent(log):
    """Enter pressed after the message was typed (an Enter also opens the chat)."""
    msg = max((i for i, e in enumerate(log) if e[0] == "paste"), default=-1)
    return ("press", "enter") in log[msg + 1:]


def _handler(tmp_path, win=None, contacts=None):
    from jarvis.core.whatsapp_handler import WhatsAppHandler
    f = tmp_path / "whatsapp_contacts.json"
    if contacts is not None:
        f.write_text(json.dumps(contacts), encoding="utf-8")
    return WhatsAppHandler(SimpleNamespace(user_title="sir", speak=MagicMock()),
                           win=win or FakeWin(), contacts_file=f)


# ─── drafting ──────────────────────────────────────────────────────────────

def test_message_is_typed_but_not_sent_until_confirmed(tmp_path, keys):
    wa = _handler(tmp_path)
    reply = wa.send_message("Mom", "I'll be late")
    assert "typed" in reply and "'send'" in reply
    assert ("paste", "Mom") in keys.log and ("paste", "I'll be late") in keys.log
    # Nothing after the message is pasted: Enter is NOT pressed
    assert keys.log[-1] == ("paste", "I'll be late")
    assert wa.pending_draft().contact == "Mom"

    reply = wa.confirm_send()
    assert reply.startswith("Sent to Mom")
    assert keys.log[-1] == ("press", "enter")
    assert wa.pending_draft() is None


def test_clipboard_is_restored(tmp_path, keys):
    _handler(tmp_path).send_message("Mom", "hi")
    assert keys.clip["value"] == "user's clipboard"


def test_saved_number_opens_that_exact_chat_with_text(tmp_path, keys):
    wa = _handler(tmp_path, contacts={"Mom": "+91 98765 43210"})
    wa.send_message("mom", "see you at 7 & bring cake")
    launches = [e for e in keys.log if e[0] == "startfile"]
    assert launches == [("startfile",
                         "whatsapp://send?phone=919876543210&text=see%20you%20at%207%20%26%20bring%20cake")]
    assert not [e for e in keys.log if e[0] in ("paste", "press")]   # nothing typed, nothing sent
    assert wa.pending_draft()


def test_no_keys_when_whatsapp_cannot_be_focused(tmp_path, keys):
    """Focus used to fail silently and the keys went to the HUD."""
    wa = _handler(tmp_path, win=FakeWin(focus_ok=False))
    reply = wa.send_message("Mom", "hi")
    assert "couldn't" in reply
    assert not [e for e in keys.log if e[0] in ("paste", "press", "hotkey")]
    assert wa.pending_draft() is None


def test_focus_lost_mid_draft_stops_typing(tmp_path, keys):
    win = FakeWin()
    wa = _handler(tmp_path, win=win)
    import jarvis.core.whatsapp_handler as mod
    real_paste = mod.WhatsAppHandler._paste

    def paste_then_click_away(self, hwnd, text, settle=0.3):
        ok = real_paste(self, hwnd, text, settle)
        win.foreground = 1   # the user clicked another window
        return ok

    with patch.object(mod.WhatsAppHandler, "_paste", paste_then_click_away):
        assert "couldn't" in wa.send_message("Mom", "hi")
    assert ("paste", "hi") not in keys.log
    assert not _sent(keys.log)


# ─── sending / cancelling ──────────────────────────────────────────────────

def test_send_never_presses_enter_outside_whatsapp(tmp_path, keys):
    win = FakeWin()
    wa = _handler(tmp_path, win=win)
    wa.send_message("Mom", "hi")
    win.focus_ok = False
    reply = wa.confirm_send()
    assert "didn't send" in reply
    assert not _sent(keys.log)


def test_cancel_clears_the_draft(tmp_path, keys):
    wa = _handler(tmp_path)
    wa.send_message("Mom", "hi")
    reply = wa.cancel_draft()
    assert "Cancelled" in reply
    assert keys.log[-2:] == [("hotkey", "ctrl", "a"), ("press", "backspace")]
    assert wa.confirm_send().startswith("There's no message")


def test_draft_expires(tmp_path, keys):
    wa = _handler(tmp_path)
    wa.send_message("Mom", "hi")
    wa._draft.expires_at = time.time() - 1
    assert wa.pending_draft() is None
    assert not _sent(keys.log)


def test_missing_parts_are_asked_for(tmp_path, keys):
    wa = _handler(tmp_path)
    assert "Who" in wa.send_message("", "hi")
    assert "What should I say to Mom" in wa.send_message("Mom", "")
    assert keys.log == []


# ─── matching ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("title,ok", [
    ("WhatsApp", True), ("(3) WhatsApp", True), ("WhatsApp Beta", True),
    ("WhatsApp - Google Chrome", False), ("(2) WhatsApp Web - Microsoft Edge", False),
    ("J.A.R.V.I.S HUD", False),
])
def test_only_the_desktop_window_counts(title, ok):
    from jarvis.core.whatsapp_handler import WHATSAPP_TITLE_RE
    assert bool(WHATSAPP_TITLE_RE.match(title)) is ok


@pytest.mark.parametrize("text,send", [
    ("send", True), ("send it", True), ("yes send it", True), ("yes", True),
    ("send the message", True), ("confirm", True), ("go ahead", True), ("send it now", True),
    ("send whatsapp message to mom saying hi", False), ("send an email", False),
    ("cancel", False), ("what's the weather", False),
])
def test_send_confirmation_phrases(text, send):
    from jarvis.core.whatsapp_handler import SEND_CONFIRM_RE
    assert bool(SEND_CONFIRM_RE.match(text)) is send


def test_contacts_file(tmp_path):
    from jarvis.core.whatsapp_handler import load_contacts
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"Mom": "+91 98765-43210", "bad": "12"}), encoding="utf-8")
    assert load_contacts(f) == {"mom": "919876543210"}
    assert load_contacts(tmp_path / "missing.json") == {}


# ─── server: "send" / "cancel" reach the draft, locally ────────────────────

@pytest.fixture
def server(tmp_path, keys):
    import jarvis.gui.websocket_server as ws
    srv = object.__new__(ws.JARVISWebSocketServer)
    srv._pending_power_action = None
    srv.hud_perception = MagicMock(assistant_name="JARVIS", user_title="sir")
    srv.quiet_mode = False
    srv.whatsapp_handler = _handler(tmp_path)
    return srv


def test_server_sends_the_draft_on_send(server, keys):
    server.whatsapp_handler.send_message("Mom", "hi")
    reply = asyncio.run(server.process_command("send it", None))
    assert reply.startswith("Sent to Mom")
    assert keys.log[-1] == ("press", "enter")


def test_server_cancels_the_draft(server, keys):
    server.whatsapp_handler.send_message("Mom", "hi")
    assert "Cancelled" in asyncio.run(server.process_command("cancel", None))
    assert not _sent(keys.log)


def test_send_and_cancel_stay_local_in_live_mode(server):
    assert not server._answers_whatsapp_draft("send")       # nothing pending
    server.whatsapp_handler.send_message("Mom", "hi")
    assert server._answers_whatsapp_draft("send")
    assert server._answers_whatsapp_draft("cancel")
    assert not server._answers_whatsapp_draft("what's the weather")


def test_live_engine_second_identical_call_sends():
    """In live mode the user's 'yes' goes to Gemini; it confirms by repeating the call."""
    src = (ROOT / "jarvis/core/gemini_live_engine.py").read_text(encoding="utf-8")
    assert "_wa.confirm_send()" in src
    assert "Not sent yet. Ask the user to confirm" in src


def test_thumbs_up_never_sends_but_thumbs_down_clears(server, keys):
    """A sent message can't be taken back and a thumbs-up happens by accident,
    so sending needs a spoken 'send'. Thumbs down ('cancel') is safe."""
    sent = []
    server._gesture_feedback = MagicMock()
    server._pending_clarify = None
    server._gesture_command = lambda text: sent.append(text) or _Done()
    server._run_on_loop = lambda coro: coro.close()
    server._on_gesture("thumbs_up")
    assert sent == []                                     # nothing pending: ignored
    server.whatsapp_handler.send_message("Mom", "hi")
    server._on_gesture("thumbs_up")
    assert sent == []                                     # not sent by a gesture
    assert "Say 'send'" in server._gesture_feedback.call_args.kwargs["note"]
    assert not _sent(keys.log)
    server._on_gesture("thumbs_down")
    assert sent == ["cancel"]
    assert "Cancelled" in asyncio.run(server.process_command("cancel", None))
    assert not _sent(keys.log)


class _Done:
    def close(self):
        pass
