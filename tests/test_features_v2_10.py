"""
Bugs found by sending ~110 commands through the real HUD path (v2.10).
Each test pins one of them.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ── calculator: "calculate 25 times 4" used to answer with the time ──────────

@pytest.mark.parametrize("text,result", [
    ("calculate 25 times 4", "100"), ("what is 15 percent of 200", "30"), ("square root of 81", "9"),
    ("12.5 divided by 4", "3.125"), ("what is 2 to the power of 10", "1,024"), ("what is 7 minus 10", "-3"),
    ("calculate (3 + 4) * 2", "14"), ("what is 9 squared", "81"),
])
def test_spoken_arithmetic(text, result):
    from jarvis.core.calculator import answer
    assert answer(text) == result


@pytest.mark.parametrize("text", ["what time is it", "2026", "set a timer for 5 minutes", "open notepad",
                                  "what is quantum computing", "tell me about 2 cats"])
def test_not_arithmetic(text):
    from jarvis.core.calculator import answer
    assert answer(text) is None


def test_calculator_never_evaluates_code():
    from jarvis.core.calculator import evaluate
    for bad in ("__import__('os')", "2 ** 99999999", "(1).__class__"):
        with pytest.raises((ValueError, SyntaxError)):
            evaluate(bad)


def test_calculation_is_classified_before_time():
    from jarvis.core.intent_classifier import classify_intent
    assert classify_intent("calculate 25 times 4")[0] == "calculate"


# ── typos in command words ───────────────────────────────────────────────────

@pytest.mark.parametrize("text,fixed", [
    ("wats the wether in paris", "wats the weather in paris"), ("whats the tiem", "whats the time"),
    ("opne notepad", "open notepad"), ("set an alram for 7", "set an alarm for 7"),
    ("check the batery", "check the battery"), ("turn the volum up", "turn the volume up"),
])
def test_typos_in_command_words_are_fixed(text, fixed):
    from jarvis.core.typo_fix import fix_typos
    assert fix_typos(text) == fixed


@pytest.mark.parametrize("text", ["tell me a story about a feather", "what is the tide today",
                                  "whether you like it or not", "the mews were quiet", "time flies"])
def test_real_words_are_left_alone(text):
    from jarvis.core.typo_fix import fix_typos
    assert fix_typos(text) == text


# ── memory: remember called knowledge.remember(), which doesn't exist ───────

def test_remember_and_recall(tmp_path):
    from jarvis.core import memory_store
    from jarvis.core.intent_handlers import handle_remember, handle_recall
    store = memory_store.MemoryStore(tmp_path / "memory.json")
    with patch.object(memory_store, "MemoryStore", lambda: store):
        r = handle_remember("remember that my favourite colour is blue", {}, {"title": "sir"})
        assert r.success and "favourite colour is blue" in r.response
        r = handle_recall("what is my favourite colour", {"query": "favourite colour"}, {"title": "sir"})
        assert r.success and "blue" in r.response
        # not a memory question after all: the router asks the AI instead
        assert handle_recall("what is my ip address", {"query": "ip address"}, {}).success is False
        # explicitly about memory: say so
        r = handle_recall("do you remember my wifi password", {"query": "wifi password"}, {"title": "sir"})
        assert r.success and "don't remember" in r.response
    assert json.loads((tmp_path / "memory.json").read_text())[0]["fact"] == "my favourite colour is blue"


# ── tasks / habits / notes / email read back what's really there ────────────

def test_tasks_show_their_text_in_both_formats():
    from jarvis.core.task_manager import TaskManager
    tm = object.__new__(TaskManager)
    tm.perception = MagicMock(user_title="sir")
    tm._get_title = lambda: "sir"
    tm.data = {"tasks": [{"task": "summarise my notifications", "completed": False},
                         {"description": "finish project report", "completed": False}]}
    out = tm.list_tasks()
    assert "summarise my notifications" in out and "finish project report" in out and "Task 1" not in out


def test_habits_are_listed_not_announced():
    from jarvis.core.habit_tracker import HabitTracker
    ht = object.__new__(HabitTracker)
    ht.perception = None
    ht.habits = [{"description": "drink water", "interval": "daily"}]
    assert ht.list_habits() == "You're tracking 1 habit, sir: drink water (daily)."
    ht.habits = []
    assert "aren't tracking any habits" in ht.list_habits()


def test_same_note_is_read_once():
    from jarvis.core import intent_handlers
    notes = [SimpleNamespace(content="buy groceries")] * 3 + [SimpleNamespace(content="call mom")]
    with patch.object(intent_handlers, "shared", lambda *a, **k: SimpleNamespace(get_recent_notes=lambda n: notes)):
        r = intent_handlers.handle_list_notes("show my notes", {}, {"title": "sir"})
    assert r.response == "Your latest notes, sir: buy groceries; call mom."


# ── opening apps: callers used AppManager methods on a bare AppFinder ────────

def test_app_opening_uses_the_manager():
    src = (ROOT / "jarvis/core/jarvis_ultimate.py").read_text(encoding="utf-8")
    assert "self.app_finder = shared(AppManager" in src
    from jarvis.core.app_finder import AppManager
    assert callable(getattr(AppManager, "open_app")) and callable(getattr(AppManager, "refresh_cache"))
    for f in ("jarvis/gui/server/commands.py", "jarvis/gui/server/router.py"):
        assert "shared(AppFinder).open_app" not in (ROOT / f).read_text(encoding="utf-8")


def test_start_menu_search_passes_the_name_as_data():
    """The app name was pasted into a PowerShell script: a quote in it could run commands."""
    from jarvis.core.app_finder import AppLauncher
    launcher = object.__new__(AppLauncher)
    evil = 'x"; Remove-Item C:\\important -Recurse; "'
    with patch("subprocess.run", return_value=SimpleNamespace(returncode=1)) as run:
        launcher._launch_via_powershell(evil)
    args, kwargs = run.call_args
    script = args[0][-1]
    assert evil not in script and "Remove-Item" not in script
    assert kwargs["env"]["JARVIS_APP_QUERY"] == evil


# ── fast path: tab commands and several commands at once ─────────────────────

@pytest.mark.parametrize("text", ["open a new tab", "close this tab", "open notepad and set a timer for 2 minutes"])
def test_fast_path_leaves_these_to_the_router(text):
    from jarvis.gui.fast_path import try_fast_path
    server = SimpleNamespace(hud_perception=SimpleNamespace(user_title="sir"))
    assert try_fast_path(server, text) is None
