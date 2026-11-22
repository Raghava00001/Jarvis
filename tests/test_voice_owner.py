"""
One voice owner, and a WebSocket that can't be overloaded.

Double voice had two causes: a handler spoke a reply through the server's TTS
AND returned it for the browser to speak; or a handler only spoke and returned
"", so the router treated the command as unanswered and asked the AI as well.
These tests pin the fix: during a command, speech is recorded, the server turns
it into the reply, and that reply is spoken once.
"""

import asyncio
import re
import threading
import time
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _hud(announcer=None):
    from jarvis.gui.hud_types import HUDPerception
    hud = HUDPerception()
    hud.voice_out = MagicMock(return_value=True)
    hud.announcer = announcer
    return hud


# ─── Turn capture ──────────────────────────────────────────────────────────

def test_speech_inside_a_command_is_recorded_not_played():
    from jarvis.gui.hud_types import command_turn, turn_text
    announcer = MagicMock()
    hud = _hud(announcer)
    with command_turn() as said:
        hud.speak("Here are the headlines.")
        hud.speak("Here are the headlines.")  # same line twice: kept once
        assert turn_text() == "Here are the headlines."
    assert said == ["Here are the headlines."]
    hud.voice_out.assert_not_called()
    announcer.assert_not_called()
    assert turn_text() == ""  # turn is over


def test_speech_outside_a_command_is_announced_once():
    announcer = MagicMock()
    hud = _hud(announcer)
    hud.speak("Reminder: drink water")
    hud.speak("Reminder: drink water")  # duplicate within 2 s
    announcer.assert_called_once_with("Reminder: drink water")
    hud.voice_out.assert_not_called()  # the announcer owns voicing


def _server_stub():
    from jarvis.gui.websocket_server import JARVISWebSocketServer
    srv = types.SimpleNamespace()
    srv._run_blocking = types.MethodType(JARVISWebSocketServer._run_blocking, srv)
    srv._run_turn = types.MethodType(JARVISWebSocketServer._run_turn, srv)
    return srv


def test_turn_reaches_the_router_worker_thread():
    """The router runs in a worker thread; what its handlers say must still land in the turn."""
    from jarvis.gui.hud_types import command_turn
    hud = _hud(MagicMock())
    srv = _server_stub()
    seen_threads = []

    def handler():
        seen_threads.append(threading.current_thread())
        hud.speak("Top story: rain in Hyderabad.")
        return ""

    async def go():
        with command_turn() as said:
            await srv._run_blocking(handler)
        return said

    said = asyncio.run(go())
    assert said == ["Top story: rain in Hyderabad."]
    assert seen_threads[0] is not threading.main_thread()
    hud.announcer.assert_not_called()


def test_spoken_only_answer_becomes_the_reply_and_ai_is_not_asked():
    hud = _hud(MagicMock())
    srv = _server_stub()
    ai = MagicMock(return_value="[a second, different answer]")

    async def process_command(command, websocket):
        def handler():
            hud.speak("Cricket: India win by 5 wickets.")
            return None  # spoke instead of returning text
        reply = await srv._run_blocking(handler)
        return reply  # router: falsy -> before the fix the AI was asked next

    srv.process_command = process_command
    reply = asyncio.run(srv._run_turn("search news about cricket", None))
    assert reply == "Cricket: India win by 5 wickets."
    ai.assert_not_called()


def test_router_uses_turn_text_for_handlers_that_speak():
    src = (ROOT / "jarvis/gui/websocket_server.py").read_text(encoding="utf-8")
    assert "result.response = turn_text()" in src


# ─── Server output: one voice ──────────────────────────────────────────────

def test_browser_only_speaks_when_server_could_not():
    src = (ROOT / "jarvis/gui/websocket_server.py").read_text(encoding="utf-8")
    assert "'speak': bool(response) and not silent and not live and not server_spoke" in src


def test_announce_in_live_mode_goes_to_gemini_not_local_tts():
    from jarvis.gui.websocket_server import JARVISWebSocketServer
    srv = types.SimpleNamespace(clients=set(), _voice_loop=None)
    srv.hud_perception = _hud()
    srv.dispatch = MagicMock(return_value=None)
    srv._run_on_loop = MagicMock()
    srv._live_ready = lambda: True
    srv._push_live_text = MagicMock()
    JARVISWebSocketServer._announce(srv, "Alarm: wake up")
    srv._push_live_text.assert_called_once()
    assert "Alarm: wake up" in srv._push_live_text.call_args[0][0]
    assert srv._push_live_text.call_args.kwargs.get("wake") is False
    srv.hud_perception.voice_out.assert_not_called()

    # Live session down: the local voice says it instead of nothing
    srv._live_ready = lambda: False
    JARVISWebSocketServer._announce(srv, "Alarm: wake up")
    srv.hud_perception.voice_out.assert_called_once_with("Alarm: wake up")


def test_alarms_and_reminders_are_not_dropped_in_live_mode():
    for rel in ("jarvis/core/alarm_system.py", "jarvis/core/reminder_manager.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "live mode - suppressed" not in src, rel


# ─── "stop" ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "stop", "Stop.", "jarvis stop", "hey jarvis, stop talking", "shut up", "keep quiet please",
    "that's enough", "ok stop", "stop it",
])
def test_stop_speaking_commands(text):
    from jarvis.gui.command_rules import is_stop_speaking_command
    assert is_stop_speaking_command(text)


@pytest.mark.parametrize("text", [
    "stop the music", "stop gesture control", "stop the timer", "stop recording",
    "how do I stop procrastinating", "bus stop near me",
])
def test_tasks_starting_with_stop_are_not_silence(text):
    """These used to put JARVIS into quiet mode instead of doing the task."""
    from jarvis.gui.command_rules import is_stop_speaking_command
    assert not is_stop_speaking_command(text)


def test_stop_and_state_queries_skip_the_command_queue():
    from jarvis.gui.command_rules import is_urgent_message
    assert is_urgent_message({"type": "stop_speaking"})
    assert is_urgent_message({"type": "command", "text": "stop"})
    assert is_urgent_message({"type": "get_state"})
    assert not is_urgent_message({"type": "command", "text": "what is quantum computing"})
    assert not is_urgent_message({"type": "command", "text": "stop the music"})


# ─── WebSocket: no sends that bypass the per-client queues ────────────────

def test_no_direct_socket_sends_outside_the_sender():
    """Direct ws.send() from threads raced each client's sender task."""
    src = (ROOT / "jarvis/gui/websocket_server.py").read_text(encoding="utf-8")
    offenders = re.findall(r"\b(?:ws|client)\.send\(", src)
    assert offenders == []
    assert "asyncio.run_coroutine_threadsafe(q.put(" not in src


def test_client_tasks_cancelled_however_the_connection_ends():
    src = (ROOT / "jarvis/gui/websocket_server.py").read_text(encoding="utf-8")
    body = src.split("async def handle_client", 1)[1].split("async def send_periodic_updates", 1)[0]
    finally_block = body.split("finally:", 1)[1]
    assert "stats_task.cancel()" in finally_block
    assert "worker_task.cancel()" in finally_block


def test_boot_payload_does_not_block_the_event_loop():
    src = (ROOT / "jarvis/gui/websocket_server.py").read_text(encoding="utf-8")
    body = src.split("async def handle_client", 1)[1].split("async def send_periodic_updates", 1)[0]
    assert "'weather': self.get_weather_data()" not in body
    assert "self._run_blocking(self.get_weather_data)" in body


# ─── Gemini Live: reconnects and interrupts ────────────────────────────────

def _live_engine(loop):
    from jarvis.core.gemini_live_engine import GeminiLiveEngine
    eng = object.__new__(GeminiLiveEngine)
    eng._loop = loop
    eng._running = True
    eng._interrupt_flag = False
    eng._current_turn_id = 0
    eng._speaking_until = 0.0
    eng.audio_in_queue = None
    return eng


def test_interrupt_does_nothing_while_idle():
    """Setting the skip flag while idle would swallow the user's next reply."""
    loop = asyncio.new_event_loop()
    try:
        eng = _live_engine(loop)
        eng.audio_in_queue = asyncio.Queue()
        eng.interrupt()
        loop.run_until_complete(asyncio.sleep(0.01))
        assert eng._interrupt_flag is False
    finally:
        loop.close()


def test_interrupt_cuts_off_a_spoken_answer():
    loop = asyncio.new_event_loop()
    try:
        eng = _live_engine(loop)
        eng.audio_in_queue = asyncio.Queue()
        for _ in range(5):
            eng.audio_in_queue.put_nowait(b"pcm")
        eng.interrupt()
        loop.run_until_complete(asyncio.sleep(0.01))
        assert eng._interrupt_flag is True
        assert eng.audio_in_queue.empty()
        assert eng._current_turn_id == 1
    finally:
        loop.close()


def test_live_session_ends_when_any_loop_ends():
    """gather() waited for the mic and playback loops, which never end: a
    dropped session hung instead of reconnecting."""
    src = (ROOT / "jarvis/core/gemini_live_engine.py").read_text(encoding="utf-8")
    assert "return_when=asyncio.FIRST_COMPLETED" in src
    assert "await asyncio.gather(*tasks)" not in src
