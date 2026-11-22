"""
Wake-word gate for Gemini Live.

Bug it fixes: the mic streams to Gemini nonstop, so during live testing JARVIS
acted on background speech (paused a video, reopened Paint) without anyone
saying its name. Now JARVIS only acts after "Jarvis"/"Friday" (or typed HUD
input), then stays awake for a short follow-up window.

The receive-loop tests drive the real GeminiLiveEngine._receive_audio with a
fake Live session, so the tool and audio gates are exercised end to end.
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def g():
    import jarvis.core.gemini_live_engine as module
    return module


@pytest.fixture
def engine(g, monkeypatch):
    monkeypatch.delenv("JARVIS_WAKE_WORD", raising=False)
    server = MagicMock()
    server.clients = set()
    with patch.object(g, "pya"):
        eng = g.GeminiLiveEngine(api_key="test-key", server=server)
    eng._execute_tool = MagicMock(side_effect=lambda fc: g.types.FunctionResponse(
        id=fc.id, name=fc.name, response={"result": "done"}))
    return eng


# ─── wake-word matching ───────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "Jarvis open notepad", "hey JARVIS", "open notepad, jarvis", "hey jar vis",
    "Friday, play music", "జార్విస్ నోట్‌ప్యాడ్ తెరువు", "जार्विस गाना चलाओ",
])
def test_wake_word_detected(g, text):
    assert g.WAKE_WORD_RE.search(text)


@pytest.mark.parametrize("text", [
    "pause the video", "my friend travis called", "open the jarvis_test file",
    "fridays are fun", "", "close paint",
])
def test_no_wake_word(g, text):
    assert not g.WAKE_WORD_RE.search(text)


# ─── awake window ─────────────────────────────────────────────────────────

def test_starts_asleep_and_ignores_background_speech(engine):
    assert not engine.is_awake()
    assert engine.note_user_speech("close paint") is False
    assert not engine.is_awake()


def test_wake_word_opens_window_and_follow_ups_extend_it(engine, g):
    assert engine.note_user_speech("Jarvis open paint") is True
    assert engine.is_awake()
    first_deadline = engine._awake_until
    assert engine.note_user_speech("and make it bigger") is True  # follow-up, no name
    assert engine._awake_until >= first_deadline


def test_window_expires(engine, g):
    engine.wake("test")
    assert not engine.is_awake(now=engine._awake_until + 0.01)
    engine._awake_until = 0
    assert engine.note_user_speech("close paint") is False


def test_gate_can_be_disabled(g, monkeypatch):
    monkeypatch.setenv("JARVIS_WAKE_WORD", "0")
    with patch.object(g, "pya"):
        eng = g.GeminiLiveEngine(api_key="k", server=MagicMock())
    assert eng.is_awake()


def test_typed_hud_text_wakes_jarvis():
    src = (ROOT / "jarvis/gui/websocket_server.py").read_text(encoding="utf-8")
    assert 'le.wake("typed in HUD")' in src


def test_prompt_tells_model_about_wake_word(engine):
    assert "WAKE WORD RULES" in engine._get_system_prompt()


# ─── receive loop: tools and audio are gated ──────────────────────────────

def _content(user=None, model=None, turn_complete=False):
    return SimpleNamespace(
        interrupted=False, turn_complete=turn_complete,
        input_transcription=SimpleNamespace(text=user) if user else None,
        output_transcription=SimpleNamespace(text=model) if model else None)


def _resp(content=None, data=None, tool=None):
    return SimpleNamespace(server_content=content, data=data, tool_call=tool)


def _tool(name="open_app"):
    fc = SimpleNamespace(id="call-1", name=name, args={"app_name": "paint"})
    return SimpleNamespace(function_calls=[fc])


def _run(engine, responses):
    """Feed responses through the real _receive_audio with a fake session."""
    session = MagicMock()
    sent = []

    async def send_tool_response(function_responses):
        sent.extend(function_responses)

    session.send_tool_response = send_tool_response

    async def main():
        engine._running = True
        engine._tool_lock = asyncio.Lock()
        engine.audio_in_queue = asyncio.Queue()

        async def receive():
            for r in responses:
                yield r
            engine._running = False

        session.receive = receive
        engine.session = session
        await engine._receive_audio()
        return engine.audio_in_queue.qsize()

    queued = asyncio.run(main())
    return sent, queued


def test_background_speech_cannot_run_tools(engine, g):
    sent, _ = _run(engine, [
        _resp(_content(user="close paint")),
        _resp(tool=_tool("close_app")),
    ])
    engine._execute_tool.assert_not_called()
    assert sent[0].response == {"result": g.NOT_ADDRESSED_RESULT}


def test_addressed_speech_runs_tools(engine):
    sent, _ = _run(engine, [
        _resp(_content(user="Jarvis, close paint")),
        _resp(tool=_tool("close_app")),
    ])
    engine._execute_tool.assert_called_once()
    assert sent[0].response == {"result": "done"}


def test_reply_to_background_speech_is_muted_and_kept_out_of_chat(engine):
    _, queued = _run(engine, [
        _resp(_content(user="pause the video")),
        _resp(data=b"\x00" * 64),
        _resp(_content(model="Paused the video, sir.")),
        _resp(_content(turn_complete=True)),
    ])
    assert queued == 0
    engine.server.push_live_transcription.assert_not_called()


def test_reply_to_addressed_speech_plays(engine):
    _, queued = _run(engine, [
        _resp(_content(user="Jarvis what time is it")),
        _resp(data=b"\x00" * 64),
        _resp(_content(model="It's ten o'clock, sir.")),
        _resp(_content(turn_complete=True)),
    ])
    assert queued == 1
    assert engine.server.push_live_transcription.called


def test_wake_word_split_across_transcript_fragments(engine):
    """Real Gemini Live sends "Ja" + "rvis, ..." as separate fragments. They used
    to be stripped and space-joined into "Ja rvis", so the wake word never matched."""
    sent, _ = _run(engine, [
        _resp(_content(user="Ja")),
        _resp(_content(user="rvis, close paint")),
        _resp(tool=_tool("close_app")),
    ])
    engine._execute_tool.assert_called_once()


def test_chat_shows_words_not_fragments(engine):
    _run(engine, [
        _resp(_content(user="Jarvis, o")),
        _resp(_content(user="pen notepad")),
        _resp(_content(turn_complete=True)),
    ])
    texts = [c.args[0] if c.args else c.kwargs.get("text")
             for c in engine.server.push_live_transcription.call_args_list]
    assert any("open notepad" in str(t) for t in texts), texts
