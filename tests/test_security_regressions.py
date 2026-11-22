"""
Regression tests for the security/robustness fixes in the v2.1 hardening pass.

Each test pins down a bug that existed before:
  * shell injection through app names ("close chrome & calc")
  * any website could drive JARVIS over ws://localhost:8765 (no origin/token check)
  * "my phone rebooted" restarted the PC; "how do I shutdown linux?" quit JARVIS
  * PC shutdown/restart (incl. Gemini's tool) ran without confirmation
  * the HUD HTTP server listened on the LAN and os.chdir()'d the whole process
  * LLM/news text was injected into the HUD with innerHTML (XSS)
  * the release zip shipped chat databases, face data and logs
  * a failed embedding-model load silently returned (None, 0.0)
"""

import asyncio
import os
import re
import socket
import sys
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ─── helpers ──────────────────────────────────────────────────────────────

def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def ws_module():
    import jarvis.gui.websocket_server as ws
    return ws


@pytest.fixture
def server(ws_module):
    """A JARVISWebSocketServer shell without the heavy __init__ (no mic/camera/LLM)."""
    srv = object.__new__(ws_module.JARVISWebSocketServer)
    srv._pending_power_action = None
    srv.hud_perception = MagicMock(assistant_name="JARVIS", user_title="sir")
    srv.quiet_mode = False
    return srv


# ─── 1. Shell injection ───────────────────────────────────────────────────

class TestShellInjection:
    @pytest.mark.parametrize("name", [
        "chrome & calc", "notepad | whoami", "x && del C:\\x", "a;b", "$(calc)",
        "x^y", "%PATH%", 'x"y', "..\\..\\evil", "../evil", "",
    ])
    def test_unsafe_names_rejected(self, name):
        from jarvis.core.safe_exec import is_safe_app_name, kill_process, start_app
        assert not is_safe_app_name(name)
        with patch("subprocess.run") as run, patch("subprocess.Popen") as popen, \
                patch("os.startfile", create=True) as startfile:
            with pytest.raises(ValueError):
                kill_process(name)
            with pytest.raises(ValueError):
                start_app(name)
        run.assert_not_called(); popen.assert_not_called(); startfile.assert_not_called()

    @pytest.mark.parametrize("name", ["chrome", "vs code", "notepad.exe", "msedge", "7zip"])
    def test_plain_names_allowed(self, name):
        from jarvis.core.safe_exec import is_safe_app_name
        assert is_safe_app_name(name)

    def test_kill_process_uses_arg_list_without_shell(self):
        from jarvis.core.safe_exec import kill_process
        with patch("subprocess.run", return_value=SimpleNamespace(returncode=0)) as run:
            assert kill_process("chrome") is True
        args, kwargs = run.call_args
        assert args[0] == ["taskkill", "/IM", "chrome.exe", "/F"]
        assert not kwargs.get("shell")

    @pytest.mark.parametrize("text", ["close chrome & calc", "open calc & del x"])
    def test_fast_path_refuses_injected_app_names(self, server, text):
        with patch("subprocess.run") as run, patch("subprocess.Popen") as popen, \
                patch("os.startfile", create=True) as startfile:
            reply = server._try_fast_path(text)
        assert "isn't a valid app name" in reply
        run.assert_not_called(); popen.assert_not_called(); startfile.assert_not_called()

    def test_no_shell_string_formatting_left(self):
        """No f-string/format command handed to a shell anywhere in jarvis/."""
        offenders = []
        pattern = re.compile(r"(subprocess\.\w+|os\.system)\(\s*f['\"]")
        for py in (ROOT / "jarvis").rglob("*.py"):
            text = py.read_text(encoding="utf-8", errors="ignore")
            for m in pattern.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                snippet = text[m.start():m.start() + 120]
                # macOS/Linux-only sound/open helpers with fixed, quoted paths
                if "afplay" in snippet or "paplay" in snippet or "speaker-test" in snippet \
                        or "xdg-open" in snippet or "open \"" in snippet:
                    continue
                offenders.append(f"{py.relative_to(ROOT)}:{line}")
        assert offenders == []


# ─── 2. WebSocket origin + token ──────────────────────────────────────────

class TestWebSocketAccess:
    def _attempt(self, ws_module, path, origin):
        import websockets

        async def scenario():
            port = _free_port()

            async def handler(conn):
                await conn.send("ok")

            async with websockets.serve(handler, "127.0.0.1", port,
                                        origins=ws_module.ALLOWED_WS_ORIGINS,
                                        process_request=ws_module.check_ws_token):
                kw = {"origin": origin} if origin else {}
                try:
                    async with websockets.connect(f"ws://127.0.0.1:{port}{path}", **kw) as c:
                        return await c.recv()
                except Exception:
                    return "rejected"

        return asyncio.run(scenario())

    def test_hud_with_token_accepted(self, ws_module):
        from jarvis.gui.session_token import get_ws_token
        assert self._attempt(ws_module, f"/?token={get_ws_token()}",
                             "http://localhost:8080") == "ok"

    def test_bad_origin_refused_even_with_token(self, ws_module):
        from jarvis.gui.session_token import get_ws_token
        assert self._attempt(ws_module, f"/?token={get_ws_token()}",
                             "https://evil.example") == "rejected"

    @pytest.mark.parametrize("path", ["/", "/?token=", "/?token=wrong"])
    def test_missing_or_wrong_token_refused(self, ws_module, path):
        assert self._attempt(ws_module, path, "http://localhost:8080") == "rejected"
        assert self._attempt(ws_module, path, None) == "rejected"

    def test_server_passes_origin_and_token_checks(self):
        src = (ROOT / "jarvis/gui/websocket_server.py").read_text(encoding="utf-8")
        assert "origins=ALLOWED_WS_ORIGINS" in src
        assert "process_request=check_ws_token" in src


# ─── 3. Shutdown / reboot matching and confirmation ───────────────────────

class TestPowerCommands:
    @pytest.mark.parametrize("text", [
        "my phone rebooted", "how do i shutdown linux?", "remind me to shutdown the server",
        "the restart button is broken", "what does power off mean",
    ])
    def test_ordinary_sentences_trigger_nothing(self, ws_module, text):
        cmd = ws_module.normalize_command(text)
        assert not ws_module.is_jarvis_exit_command(cmd)
        assert ws_module.detect_pc_power_action(cmd) is None

    @pytest.mark.parametrize("text,expected", [
        ("shutdown laptop", "shutdown"), ("shut down the computer", "shutdown"),
        ("turn off my pc", "shutdown"), ("restart the laptop", "restart"),
        ("reboot", "restart"), ("jarvis, reboot the system", "restart"),
    ])
    def test_pc_power_phrases(self, ws_module, text, expected):
        assert ws_module.detect_pc_power_action(ws_module.normalize_command(text)) == expected

    @pytest.mark.parametrize("text", ["shutdown", "jarvis shutdown", "exit jarvis",
                                      "hey jarvis, shut down", "go offline"])
    def test_exit_phrases(self, ws_module, text):
        assert ws_module.is_jarvis_exit_command(ws_module.normalize_command(text))

    def test_restart_needs_confirmation(self, server):
        with patch("subprocess.Popen") as popen:
            reply = asyncio.run(server.process_command("restart the computer", None))
            assert "confirm" in reply.lower()
            popen.assert_not_called()
            asyncio.run(server.process_command("confirm", None))
        assert popen.call_args[0][0] == ["shutdown", "/r", "/t", "5"]
        assert not popen.call_args[1].get("shell")

    def test_cancel_and_expiry(self, server, ws_module):
        with patch("subprocess.Popen") as popen:
            asyncio.run(server.process_command("shutdown laptop", None))
            assert "Cancelled" in asyncio.run(server.process_command("cancel", None))
            asyncio.run(server.process_command("shutdown laptop", None))
            # Let the confirmation window lapse
            action, _ = server._pending_power_action
            server._pending_power_action = (action, time.time() - 1)
            assert server._get_pending_power_action() is None
        popen.assert_not_called()

    def test_gemini_restart_tool_requires_second_confirmed_call(self, server):
        from jarvis.core.gemini_live_engine import GeminiLiveEngine
        with patch("jarvis.core.gemini_live_engine.pya"):
            engine = GeminiLiveEngine(api_key="test-key", server=server)
        engine._push_to_chat = MagicMock()
        fc = SimpleNamespace(id="call-1", name="computer_settings", args={"action": "restart"})
        with patch("subprocess.Popen") as popen:
            engine._execute_tool(fc)
            assert not any(c[0][0][:1] == ["shutdown"] for c in popen.call_args_list)
            assert server._get_pending_power_action() == "restart"
            engine._execute_tool(fc)  # user said yes -> model calls again
        assert popen.call_args[0][0] == ["shutdown", "/r", "/t", "5"]


# ─── 4. HUD HTTP server + XSS ─────────────────────────────────────────────

class TestHudServer:
    def test_loopback_only_token_injected_cwd_unchanged(self):
        from jarvis.gui.web_hud_launcher import start_http_server
        from jarvis.gui.session_token import get_ws_token
        cwd = os.getcwd()
        port = _free_port()
        httpd = start_http_server(port)
        try:
            assert httpd.server_address[0] == "127.0.0.1"
            assert os.getcwd() == cwd
            html = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5).read().decode()
            assert f'window.JARVIS_WS_TOKEN = "{get_ws_token()}"' in html
            assert "__JARVIS_WS_TOKEN__" not in html
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_untrusted_text_not_injected_as_html(self):
        html = (ROOT / "jarvis/gui/web_hud/index.html").read_text(encoding="utf-8")
        assert "function escapeHtml" in html
        # Chat messages and news items must not be interpolated raw into innerHTML
        assert '<div class="chat-sender">${senderName}</div>${text}' not in html
        assert "<span>${item}</span>" not in html
        assert "</span> ${item}</div>" not in html


# ─── 5. Release zip never ships personal data ─────────────────────────────

class TestReleaseExclusions:
    @pytest.mark.parametrize("path", [
        "jarvis/data/chat_history.db", "jarvis/data/memory/memories.db",
        "jarvis/data/faces/face_encodings.json", "jarvis/data/faces/raghava.jpg",
        "jarvis/data/faces/face_encodings.pkl", "jarvis/gui/server_debug.log",
        "jarvis/logs/jarvis_20260203.log", ".env", "jarvis/.env",
        "client_secret_123.apps.googleusercontent.com.json",
        "jarvis_data/gmail_credentials.json", "user_profile.json",
    ])
    def test_sensitive_paths_excluded(self, path):
        sys.path.insert(0, str(ROOT))
        import zip_release
        assert zip_release.is_excluded(path) or "user_profile.json" in path and \
            "user_profile.json" in (ROOT / ".gitignore").read_text(encoding="utf-8")

    @pytest.mark.parametrize("path", ["jarvis/core/safe_exec.py", "README.md",
                                      "jarvis/gui/web_hud/index.html"])
    def test_source_files_included(self, path):
        import zip_release
        assert not zip_release.is_excluded(path)


# ─── 6. Intent model fails loudly ─────────────────────────────────────────

class TestIntentModelFailure:
    def test_classify_raises_when_model_failed_to_load(self, monkeypatch):
        import jarvis.core.intent_model as im
        import jarvis.core.shared_embeddings as se
        monkeypatch.setattr(im, "_get_model", lambda: None)
        monkeypatch.setattr(se, "_load_error", "ImportError: broken transformers install")
        model = im.IntentModel(lazy=True)
        with pytest.raises(im.IntentModelUnavailable, match="broken transformers"):
            model.classify("turn up the volume")
        with pytest.raises(im.IntentModelUnavailable):
            model.classify_detailed("turn up the volume")
        # Explicit degraded path still available
        assert isinstance(model.classify_keyword("open chrome"), tuple)

    def test_shared_model_load_failure_recorded_and_not_retried(self, monkeypatch):
        import jarvis.core.shared_embeddings as se
        calls = []

        def boom(name):
            calls.append(name)
            raise ImportError("Could not import module 'PreTrainedModel'")

        monkeypatch.setitem(sys.modules, "sentence_transformers",
                            SimpleNamespace(SentenceTransformer=boom))
        monkeypatch.setattr(se, "_shared_model", None)
        monkeypatch.setattr(se, "_load_error", None)
        assert se.get_shared_embedding_model() is None
        assert se.get_shared_embedding_model() is None
        assert len(calls) == 1
        assert "PreTrainedModel" in se.get_embedding_load_error()

    def test_brain_adapter_reports_degraded_mode(self):
        from jarvis.core.brain_adapter import BrainAdapter
        from jarvis.core.intent_model import IntentModelUnavailable
        with patch("jarvis.core.brain_adapter._safe_import", return_value=None):
            brain = BrainAdapter()
        brain.intent_model = MagicMock()
        brain.intent_model.classify.side_effect = IntentModelUnavailable("no model")
        brain.intent_model.classify_keyword.return_value = ("open_app", 0.75)
        result = brain.process("open chrome", source="text")
        assert any("DEGRADED" in line for line in result.pipeline_log)
        assert result.action == "open_app"
