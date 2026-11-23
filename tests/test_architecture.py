"""
Architecture invariants (v2.6).

Before: 37 modules were loaded twice (as core.X and jarvis.core.X), and the
server and JARVISUltimate each built their own copy of ~25 subsystems. One
running JARVIS had 2 state managers, 2 alarm systems, 2 reminder checkers
(reminders could fire twice), 2 hotkey registrations and 3 HUDPerception
objects over its lifetime.
"""

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ─── service registry ─────────────────────────────────────────────────────

class _Thing:
    built = 0

    def __init__(self):
        type(self).built += 1
        time.sleep(0.05)  # widen the race window


@pytest.fixture
def services():
    from jarvis.core import services as s
    yield s
    s._instances.pop(_Thing, None)
    s._locks.pop(_Thing, None)


def test_shared_builds_once(services):
    _Thing.built = 0
    a = services.shared(_Thing)
    b = services.shared(_Thing, lambda: _Thing())
    assert a is b and _Thing.built == 1


def test_shared_is_thread_safe(services):
    _Thing.built = 0
    results = []
    threads = [threading.Thread(target=lambda: results.append(services.shared(_Thing))) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert _Thing.built == 1
    assert all(r is results[0] for r in results)


def test_factory_may_request_other_services(services):
    class Outer:
        def __init__(self):
            self.inner = services.shared(_Thing)
    try:
        outer = services.shared(Outer)
        assert outer.inner is services.peek(_Thing)
    finally:
        services._instances.pop(Outer, None)


def test_peek_does_not_create(services):
    assert services.peek(_Thing) is None


# ─── module identity ──────────────────────────────────────────────────────

def test_legacy_import_name_returns_the_same_module():
    import jarvis  # installs the alias finder
    import importlib
    legacy = importlib.import_module("core.state_manager")
    canonical = importlib.import_module("jarvis.core.state_manager")
    assert legacy is canonical


def test_no_bare_package_imports_left():
    import re
    pat = re.compile(r"^\s*(from|import)\s+(core|gui|utils)\b", re.M)
    offenders = [str(p.relative_to(ROOT)) for p in (ROOT / "jarvis").rglob("*.py")
                 if pat.search(p.read_text(encoding="utf-8-sig", errors="ignore"))]
    assert offenders == []


def test_gui_package_import_is_lazy():
    code = ("import sys; sys.path.insert(0,'.'); import jarvis.gui; "
            "print('LOADED=' + str('jarvis.gui.advanced_hud' in sys.modules or 'pygame' in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert "LOADED=False" in out.stdout, out.stdout + out.stderr


# ─── whole app: one instance of everything ────────────────────────────────

BOOT_CHECK = r"""
import sys, os, time, gc, threading, collections
sys.path.insert(0, '.')
os.environ['JARVIS_USE_GEMINI_LIVE'] = '0'
import jarvis.gui.websocket_server as w
s = w.JARVISWebSocketServer()
s._deferred_thread.join(timeout=150)
names = ('StateManager AlarmSystem ReminderManager HotkeySystem PerceptionLayer HUDPerception '
         'NewsHandler WeatherHandler SystemControl TaskManager HabitTracker WhatsAppHandler '
         'ChatHistory ContextMemory KnowledgeLayer AppFinder AppSwitcher CalendarIntegration '
         'CalendarManager SmartNotes ScreenshotHandler').split()
counts = {n: len([o for o in gc.get_objects() if type(o).__name__ == n]) for n in names}
print('JARVIS_CORE=' + str(s.jarvis is not None))
print('WRONG=' + repr({k: v for k, v in counts.items() if v != 1}))
dups = [m for m in list(sys.modules) for p in ('core.', 'gui.', 'utils.')
        if m.startswith(p) and sys.modules.get('jarvis.' + m) is not sys.modules[m]]
print('DUPMODS=' + repr(dups))
print('SHARED=' + str(s.jarvis.alarm_system is s.alarm_system and s.jarvis.news_handler is s.news_handler))
loops = [t.name for t in threading.enumerate() if '_check_loop' in t.name or '(_run)' in t.name]
print('CHECKERS=' + str(len(loops)))
"""


@pytest.fixture(scope="module")
def boot_report():
    from _subproc import run_python
    out = run_python(BOOT_CHECK, cwd=ROOT, timeout=240)
    report = {}
    for line in out.stdout.splitlines():
        if "=" in line and line.split("=", 1)[0].isupper():
            k, v = line.split("=", 1)
            report[k] = v
    assert "WRONG" in report, out.stdout[-3000:] + out.stderr[-3000:]
    return report


def test_every_subsystem_exists_exactly_once(boot_report):
    assert boot_report["JARVIS_CORE"] == "True"
    assert boot_report["WRONG"] == "{}"


def test_no_module_loaded_twice(boot_report):
    assert boot_report["DUPMODS"] == "[]"


def test_server_and_core_share_services(boot_report):
    assert boot_report["SHARED"] == "True"


def test_one_reminder_checker_and_one_alarm_scheduler(boot_report):
    assert boot_report["CHECKERS"] == "2"


# ─── specific bugs ────────────────────────────────────────────────────────

def test_hud_perception_attach_keeps_identity():
    from jarvis.gui.hud_types import HUDPerception

    class Layer:
        assistant_name = "FRIDAY"
        user_title = "boss"

    hud = HUDPerception()
    hud._gemini_live_active = True
    hud.attach(Layer())
    assert hud.is_friday and hud.user_title == "boss"
    assert hud._gemini_live_active  # state on the same object survives


def test_calendar_integration_is_not_overwritten():
    src = (ROOT / "jarvis/core/jarvis_ultimate.py").read_text(encoding="utf-8-sig")
    assert "self.calendar_integration = shared(CalendarIntegration" in src
    assert "self.calendar_integration.get_upcoming_events()" in src


# ─── Python scoping trap ──────────────────────────────────────────────────

def test_no_local_import_shadows_a_module_import():
    """A local `import re` anywhere in a function makes `re` local to the WHOLE
    function, so other branches raise UnboundLocalError. "bluetooth on" crashed
    this way (subprocess imported further down process_command)."""
    import ast
    offenders = []
    for path in sorted((ROOT / "jarvis").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        module_names = {(a.asname or a.name).split(".")[0]
                        for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            stack = list(ast.iter_child_nodes(fn))
            while stack:
                node = stack.pop()
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
                    continue
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    for a in node.names:
                        name = (a.asname or a.name).split(".")[0]
                        if name in module_names:
                            offenders.append(f"{path.relative_to(ROOT)}:{node.lineno} {fn.name}() re-imports {name}")
                stack.extend(ast.iter_child_nodes(node))
    assert offenders == [], "\n".join(offenders)


# ─── static checks ────────────────────────────────────────────────────────

def test_no_undefined_names():
    """pyflakes found real crashes: action.search_web used `re` without importing
    it, fallback_processor used `time`, and code moved out of websocket_server
    lost its `time`/`threading` imports."""
    pyflakes = pytest.importorskip("pyflakes.api")
    import io
    from pyflakes import reporter as pf_reporter

    out = io.StringIO()
    rep = pf_reporter.Reporter(out, out)
    for path in sorted((ROOT / "jarvis").rglob("*.py")):
        pyflakes.check(path.read_text(encoding="utf-8-sig"), str(path.relative_to(ROOT)), rep)
    problems = [l for l in out.getvalue().splitlines()
                if "undefined name" in l or "referenced before assignment" in l]
    assert problems == [], "\n".join(problems)


# ─── entry points load when run as scripts ────────────────────────────────

@pytest.mark.parametrize("script", [
    "jarvis/gui/websocket_server.py",   # README: python jarvis/gui/websocket_server.py
    "jarvis/gui/desktop_gui.py",
    "jarvis/gui/web_hud_launcher.py",
    "jarvis/main.py",
])
def test_entry_point_imports_when_run_as_a_script(script, tmp_path):
    """Run as a script, only the script's own folder is on sys.path, not the
    project root. An import placed above the path setup broke
    `python jarvis/gui/websocket_server.py` (ModuleNotFoundError: jarvis)."""
    path = (ROOT / script).resolve()
    code = (
        "import sys, os, runpy\n"
        f"banned = {{os.path.normcase({str(ROOT)!r}), os.path.normcase({str(ROOT / 'jarvis')!r})}}\n"
        f"sys.path = [{str(path.parent)!r}] + [p for p in sys.path[1:] "
        "if p and os.path.normcase(os.path.abspath(p)) not in banned]\n"
        f"runpy.run_path({str(path)!r}, run_name='loaded_as_script')\n"
        "print('LOADED_OK')\n"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=240,
                         env={**__import__("os").environ, "JARVIS_USE_GEMINI_LIVE": "0"})
    assert "LOADED_OK" in out.stdout, (out.stdout[-1500:] + out.stderr[-2500:])
