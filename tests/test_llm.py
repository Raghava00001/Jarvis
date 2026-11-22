"""
Text LLM access (v2.7). Google retired gemini-2.0-flash, hard-coded in three
places: every typed question and Gemini Live's screen reading returned 404, and
the pipeline then answered unrelated questions with a greeting. With no request
timeout, an overloaded model also froze the whole server.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _client(*outcomes):
    """Fake client: each outcome is either reply text or an exception."""
    calls = []

    def generate_content(model, contents):
        calls.append(model)
        out = outcomes[len(calls) - 1]
        if isinstance(out, Exception):
            raise out
        return SimpleNamespace(text=out)

    c = MagicMock()
    c.models.generate_content.side_effect = generate_content
    return c, calls


def test_no_retired_model_left_in_code():
    for path in (ROOT / "jarvis").rglob("*.py"):
        if path.name == "llm.py":
            continue
        assert "model='gemini-2.0-flash'" not in path.read_text(encoding="utf-8-sig"), path


def test_falls_back_when_a_model_is_overloaded_or_retired():
    from jarvis.core import llm
    client, calls = _client(Exception("503 UNAVAILABLE high demand"),
                            Exception("504 DEADLINE_EXCEEDED"), "hola, sir")
    with patch.object(llm, "gemini_client", return_value=client), \
            patch.object(llm, "FALLBACK_MODELS", ["a", "b", "c"]):
        assert llm.ask_gemini("translate hello") == "hola, sir"
    assert calls == ["a", "b", "c"]


def test_stops_on_non_retryable_error():
    from jarvis.core import llm
    client, calls = _client(Exception("400 API key not valid"), "never")
    with patch.object(llm, "gemini_client", return_value=client), \
            patch.object(llm, "FALLBACK_MODELS", ["a", "b"]):
        assert llm.ask_gemini("hi") is None
    assert calls == ["a"]


def test_no_key_means_no_call(monkeypatch):
    from jarvis.core import llm
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert llm.gemini_client(api_key="") is None
    assert llm.ask_gemini("hi", api_key="") is None


def test_client_has_a_request_timeout():
    from jarvis.core import llm
    created = {}

    class FakeClient:
        def __init__(self, api_key, http_options=None):
            created["timeout"] = getattr(http_options, "timeout", None)

    with patch("google.genai.Client", FakeClient):
        llm._clients.pop("test-key-timeout", None)
        llm.gemini_client("test-key-timeout")
    assert created["timeout"] == llm.REQUEST_TIMEOUT_MS > 0


def test_knowledge_falls_back_to_gemini_when_groq_rejects_the_key():
    from jarvis.core.knowledge import KnowledgeLayer
    kl = object.__new__(KnowledgeLayer)
    kl.api_type, kl.groq_key, kl.openrouter_key, kl.gemini_key = "groq", "bad", "bad", "good"
    kl._call_groq = MagicMock(return_value=None)        # 401
    kl._call_openrouter = MagicMock(return_value=None)  # 401
    with patch("jarvis.core.llm.ask_gemini", return_value="answer") as ask:
        assert kl._generate_response("system", "question") == "answer"
    ask.assert_called_once_with("question", system="system")


def test_router_runs_off_the_event_loop():
    """A slow handler (LLM call) used to block the event loop and freeze every reply."""
    src = (ROOT / "jarvis/gui/websocket_server.py").read_text(encoding="utf-8")
    assert "run_in_executor(\n            None, self._route_through_router, command)" in src.replace("\r\n", "\n")
