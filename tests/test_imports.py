"""
Every optional feature the server imports must actually import.

A failing optional import switches its feature off. That was silent: gestures
never ran because the server also imported a non-existent GestureType, and
sound effects never loaded because it imported SoundEffects, a class that
doesn't exist. A missing third-party package (no camera library in CI, say)
is fine; a broken import of JARVIS's own code is a bug.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_no_broken_jarvis_imports_in_the_server():
    import jarvis.gui.websocket_server as ws
    broken = [e for e in ws.MISSING_IMPORTS
              if "cannot import name" in e or "jarvis" in e.lower()]
    assert broken == []


def test_every_bare_except_is_gone():
    """A bare `except:` also catches Ctrl+C and SystemExit, so JARVIS could
    ignore being told to quit, and it hides real crashes."""
    import re
    bad = []
    for p in (ROOT / "jarvis").rglob("*.py"):
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if re.match(r"\s*except\s*:", line):
                bad.append(f"{p.relative_to(ROOT)}:{i}")
    assert bad == []


def test_recovered_errors_are_reported(capsys):
    """Fallbacks used to be `except: pass`, hiding why the first way failed."""
    from jarvis.core.errors import recovered
    for _ in range(2):
        try:
            {}["news_api_key"]
        except KeyError as e:
            recovered("News", e)
    out = capsys.readouterr().out
    assert out.count("[News] recovered from KeyError: 'news_api_key'") == 2
    assert out.count("test_imports.py") == 1      # where it came from: once per spot


def test_command_path_has_no_silent_fallbacks():
    import re
    for f in ("jarvis/gui/fallback_processor.py", "jarvis/core/intent_handlers.py"):
        lines = (ROOT / f).read_text(encoding="utf-8").splitlines()
        silent = [i + 1 for i, l in enumerate(lines[:-1])
                  if re.match(r"\s*except Exception(?: as \w+)?:\s*$", l) and lines[i + 1].strip() == "pass"]
        assert silent == [], f


# ─── process_command: named steps, slow ones off the event loop ────────────

def _cmd_server():
    import types
    from unittest.mock import MagicMock
    import jarvis.gui.websocket_server as ws
    srv = object.__new__(ws.JARVISWebSocketServer)
    srv.hud_perception = types.SimpleNamespace(user_title="sir", assistant_name="JARVIS")
    srv._pending_power_action = None
    srv._pending_clarify = None
    srv.quiet_mode = False
    srv.whatsapp_handler = None
    srv._stop_speaking = MagicMock()
    return srv


def test_local_commands_run_off_the_event_loop():
    """Bluetooth (PowerShell, up to 10 s) and email used to run on the event
    loop and freeze every HUD client while they ran."""
    import asyncio
    import threading
    srv = _cmd_server()
    seen = {}

    def fake_local(cmd, command, title):
        seen["thread"] = threading.current_thread()
        return "Bluetooth is now off."

    srv._local_command = fake_local
    reply = asyncio.run(srv.process_command("turn off bluetooth", None))
    assert reply == "Bluetooth is now off."
    assert seen["thread"] is not threading.main_thread()


def test_step_order_is_kept():
    import asyncio
    from unittest.mock import patch
    srv = _cmd_server()
    assert "Say my name" in asyncio.run(srv.process_command("stop", None))      # voice control first
    assert srv.quiet_mode is True
    assert "back online" in asyncio.run(srv.process_command("back online", None))
    with patch("subprocess.Popen") as popen:
        assert "sure" in asyncio.run(srv.process_command("restart the computer", None)).lower()
        popen.assert_not_called()
    srv._local_command = lambda *a: "local"
    assert asyncio.run(srv.process_command("open notepad", None)) == "local"


def test_open_app_uses_the_direct_map():
    from unittest.mock import patch
    srv = _cmd_server()
    with patch("subprocess.Popen") as popen:
        assert srv._cmd_open_app("open notepad", "open notepad", "sir") == "Opening notepad, sir."
    popen.assert_called_once_with("notepad", shell=True)
    assert srv._cmd_open_app("what is notepad", "", "sir") is None
