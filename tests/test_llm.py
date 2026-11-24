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
sys.path.insert(0, str(ROOT / "tests"))
from _server_src import server_source  # noqa: E402


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
    src = server_source()
    assert "await self._run_blocking(self._route_through_router, command)" in src
    # _run_blocking: a worker thread, with the command's context (turn) copied in
    body = src.split("async def _run_blocking", 1)[1].split("\n    async def ", 1)[0]
    assert "run_in_executor(None, ctx.run, call)" in body


# ---- Groq / OpenRouter model lists (v2.9) ------------------------------------
# Groq retired llama-3.3-70b-versatile and OpenRouter's free Llama went paid:
# with one hard-coded model each, every request failed with 404.

def _resp(status, content=None, text=""):
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.json.return_value = {"choices": [{"message": {"content": content}}]}
    return r


def _layer():
    from jarvis.core.knowledge import KnowledgeLayer
    kl = object.__new__(KnowledgeLayer)
    kl.groq_key, kl.openrouter_key, kl.gemini_key = "k", "k", None
    return kl


def test_retired_model_is_skipped_for_the_session():
    from jarvis.core import knowledge as K
    kl = _layer()
    models = ["old-model", "new-model"]
    with patch.object(K, "GROQ_MODELS", models), patch.object(K, "_retired_models", set()) as retired,          patch.object(K.requests, "post", side_effect=[
             _resp(404, text='{"error":{"code":"model_not_found"}}'), _resp(200, "hello"),
             _resp(200, "again")]) as post:
        assert kl._call_groq([{"role": "user", "content": "hi"}]) == "hello"
        assert retired == {"old-model"}
        assert kl._call_groq([{"role": "user", "content": "hi"}]) == "again"
    used = [c.kwargs["json"]["model"] for c in post.call_args_list]
    assert used == ["old-model", "new-model", "new-model"]   # not retried


def test_rate_limit_and_empty_reply_move_to_the_next_model():
    from jarvis.core import knowledge as K
    kl = _layer()
    with patch.object(K, "OPENROUTER_MODELS", ["a", "b", "c"]), patch.object(K, "_retired_models", set()) as retired,          patch.object(K.requests, "post", side_effect=[_resp(429), _resp(200, ""), _resp(200, "ok")]):
        assert kl._call_openrouter([{"role": "user", "content": "hi"}]) == "ok"
        assert retired == set()   # busy is not retired


def test_rejected_key_disables_provider():
    from jarvis.core import knowledge as K
    kl = _layer()
    with patch.object(K, "GROQ_MODELS", ["a", "b"]), patch.object(K, "_retired_models", set()),          patch.object(K.requests, "post", return_value=_resp(401)) as post:
        assert kl._call_groq([{"role": "user", "content": "hi"}]) is None
    assert post.call_count == 1 and kl.groq_key is None


def test_model_lists_are_configurable_and_have_no_retired_defaults():
    import importlib, os
    from jarvis.core import knowledge as K
    with patch.dict(os.environ, {"JARVIS_GROQ_MODEL": "my/model"}):
        importlib.reload(K)
        assert K.GROQ_MODELS[0] == "my/model"
    importlib.reload(K)
    assert "llama-3.3-70b-versatile" not in K.GROQ_MODELS
    assert "meta-llama/llama-3.1-8b-instruct:free" not in K.OPENROUTER_MODELS


def test_spoken_text_has_plain_spaces():
    from jarvis.core.knowledge import clean_for_speech
    assert clean_for_speech("Leonardo da Vinci **painted** it") == "Leonardo da Vinci painted it"
