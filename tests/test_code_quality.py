"""
Code-quality rules, enforced so they can't quietly slide back.

* No print(): every module logs through logging (see jarvis/logging_setup.py),
  so output has levels and JARVIS_LOG_LEVEL can quiet or expand it.
* No silent `except ...: pass` and no bare `except:`: an error JARVIS recovers
  from is still logged (at debug level if it's routine).
* The HUD server stays split by responsibility (jarvis/gui/server/): neither
  websocket_server.py nor any of its parts may grow back into a giant file.
* Function length is a ratchet: nothing new may exceed MAX_FUNCTION_LINES,
  and the few functions still over it may only get shorter.
"""

import ast
import io
import logging
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
JARVIS = ROOT / "jarvis"

MAX_FUNCTION_LINES = 120

# Long functions that predate the limit, with their current length. Lower a
# number when you shorten one; remove the entry once it is under the limit.
LONG_FUNCTION_BUDGET = {
    ("jarvis/core/jarvis_ultimate.py", "_process_single_command"): 463,   # console mode
    ("jarvis/gui/fallback_processor.py", "process"): 265,                  # short rules, kept inline
    ("jarvis/core/gemini_live_engine.py", "_execute_tool"): 239,
    ("jarvis/core/intent_classifier.py", "classify_intent"): 220,          # short rules, kept inline
    ("jarvis/gui/server/messages.py", "_on_input"): 213,
    ("jarvis/gui/server/router.py", "_route_through_router"): 194,
    ("jarvis/core/gemini_live_engine.py", "_receive_audio"): 184,
    ("jarvis/core/understanding.py", "__init__"): 140,
    ("jarvis/gui/fast_path.py", "try_fast_path"): 129,
    ("jarvis/gui/websocket_server.py", "handle_client"): 122,
}

MAX_SERVER_FILE_LINES = 550


def _modules():
    for p in sorted(JARVIS.rglob("*.py")):
        if "__pycache__" not in p.parts:
            yield p, ast.parse(p.read_text(encoding="utf-8-sig"))


def _rel(p):
    return p.relative_to(ROOT).as_posix()


def test_no_print_calls():
    found = [f"{_rel(p)}:{n.lineno}" for p, t in _modules() for n in ast.walk(t)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "print"]
    assert found == [], "use the module logger (_log = logging.getLogger(__name__)):\n" + "\n".join(found)


def test_no_silent_or_bare_except():
    silent, bare = [], []
    for p, t in _modules():
        for n in ast.walk(t):
            if isinstance(n, ast.ExceptHandler):
                if n.type is None:
                    bare.append(f"{_rel(p)}:{n.lineno}")
                if len(n.body) == 1 and isinstance(n.body[0], ast.Pass):
                    silent.append(f"{_rel(p)}:{n.lineno}")
    assert bare == [], "bare except: also catches KeyboardInterrupt/SystemExit:\n" + "\n".join(bare)
    assert silent == [], ('log it instead of `pass`, e.g. _log.debug("Ignored error", exc_info=True):\n'
                          + "\n".join(silent))


def test_no_control_characters_in_source():
    """A regex's word boundary once became a literal backspace character (written
    through a script): invisible, and the pattern could never match."""
    allowed = {9, 12}   # tab, form feed
    found = []
    for p in sorted(list(JARVIS.rglob("*.py")) + list((ROOT / "tests").rglob("*.py"))):
        for i, line in enumerate(p.read_text(encoding="utf-8-sig").splitlines(), 1):
            if any(ord(c) < 32 and ord(c) not in allowed for c in line):
                found.append(f"{_rel(p)}:{i}")
    assert found == [], ", ".join(found)


def test_function_length_ratchet():
    over, grew, done = [], [], []
    seen = set()
    for p, t in _modules():
        for n in ast.walk(t):
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            length = n.end_lineno - n.lineno + 1
            key = (_rel(p), n.name)
            if key in LONG_FUNCTION_BUDGET:
                seen.add(key)
                if length > LONG_FUNCTION_BUDGET[key]:
                    grew.append(f"{key[0]} {key[1]}: {length} > {LONG_FUNCTION_BUDGET[key]}")
                elif length <= MAX_FUNCTION_LINES:
                    done.append(f"{key[0]} {key[1]} is now {length} lines: remove it from LONG_FUNCTION_BUDGET")
            elif length > MAX_FUNCTION_LINES:
                over.append(f"{key[0]}:{n.lineno} {key[1]} is {length} lines (max {MAX_FUNCTION_LINES})")
    assert over == [], "split into named steps:\n" + "\n".join(over)
    assert grew == [], "these may only get shorter:\n" + "\n".join(grew)
    assert done == [], "\n".join(done)
    stale = set(LONG_FUNCTION_BUDGET) - seen
    assert not stale, f"no longer exist, remove from LONG_FUNCTION_BUDGET: {sorted(stale)}"


def test_server_stays_split():
    files = [JARVIS / "gui/websocket_server.py"] + sorted((JARVIS / "gui/server").glob("*.py"))
    too_big = [f"{_rel(f)}: {len(f.read_text(encoding='utf-8').splitlines())} lines"
               for f in files if len(f.read_text(encoding="utf-8").splitlines()) > MAX_SERVER_FILE_LINES]
    assert too_big == [], ("the server is split by responsibility (jarvis/gui/server/); "
                           "put new code in the part it belongs to, or add a part:\n" + "\n".join(too_big))
    import jarvis.gui.websocket_server as ws
    parts = [c.__name__ for c in ws.JARVISWebSocketServer.__mro__[1:] if c.__module__.startswith("jarvis.gui.server.")]
    assert len(parts) == 10, parts


# ── the console logging itself ─────────────────────────────────────────────

def _capture(level=logging.INFO, name="jarvis.test_quality"):
    from jarvis.logging_setup import install
    install(level)
    buf = io.StringIO()
    return logging.getLogger(name), buf


def test_console_output_looks_like_before(monkeypatch):
    log, buf = _capture()
    monkeypatch.setattr("sys.stdout", buf)
    log.info("[ALARMS] System Ready")
    log.debug("hidden at INFO")
    assert buf.getvalue() == "[ALARMS] System Ready\n"


def test_debug_level_shows_recovered_errors_with_location(monkeypatch):
    log, buf = _capture(logging.DEBUG)
    monkeypatch.setattr("sys.stdout", buf)
    try:
        {}["missing"]
    except KeyError:
        log.debug("Ignored error", exc_info=True)
    out = buf.getvalue()
    assert out.startswith("[debug] jarvis.test_quality:") and "KeyError: 'missing'" in out
    _capture(logging.INFO)


def test_unprintable_characters_never_crash(monkeypatch):
    class Cp1252(io.StringIO):
        encoding = "cp1252"

        def write(self, s):
            s.encode("cp1252")   # raises like a Windows console would
            return super().write(s)

    log, _ = _capture()
    out = Cp1252()
    monkeypatch.setattr("sys.stdout", out)
    log.info("[JARVIS] done ✓ 🚀")
    assert out.getvalue().startswith("[JARVIS] done ?")


def test_pipeline_logger_does_not_swallow_module_output():
    """core/logger.py used to own the 'jarvis' logger with propagate=False,
    which would have hidden every module's messages."""
    from jarvis.core.logger import JarvisLogger
    assert JarvisLogger().logger.name == "jarvis.pipeline"
