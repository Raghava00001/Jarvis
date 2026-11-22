"""
End-to-end routing corpus (v2.6).

Boots the real JARVIS server (Gemini Live off), sends real commands through the
real text pipeline, and checks the answers. Every side effect is stubbed: no
apps open, no keys are pressed, no volume changes, no PC power action and no
network LLM call. This harness found most of the v2.6 bugs, e.g.:

  "bluetooth on"               -> crashed (UnboundLocalError)
  "weather in london"          -> Hyderabad's weather
  "set a timer for 5 minutes"  -> told the current time
  "set an alarm for 7 am"      -> "What time should I set the alarm for?"
  "hello" / "help"             -> "I'm about 56% sure I understand. Should I proceed?"
  "what is quantum computing"  -> opened a Google search instead of answering
  "send a whatsapp to dad ..." -> "Message sent to to dad"
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# command -> substrings that must appear in the reply (case-insensitive), and
# substrings that must NOT appear
EXPECT = {
    "bluetooth on": (["bluetooth"], ["exception", "error"]),
    "weather in london": (["london"], ["hyderabad"]),
    "what is the weather in new york": (["new york"], []),
    "set a timer for 5 minutes": (["timer"], ["current time"]),
    "set an alarm for 7 am": (["alarm set", "7:00"], ["what time should"]),
    "hello": ([], ["% sure"]),
    "help": ([], ["% sure"]),
    "goodbye": ([], ["% sure"]),
    "how are you": ([], ["% sure"]),
    "what is quantum computing": (["[knowledge answer]"], ["searching for"]),
    "search for python tutorials": (["'python tutorials'"], ["for python"]),
    "send a whatsapp to dad saying hi": (["dad"], ["to to dad"]),
    "battery level": (["cpu"], []),
    "what time is it": (["it's"], []),
    "what's the date today": (["today is"], []),
    "tell me a joke": ([], ["% sure"]),
    "restart my pc": (["confirm"], []),
    "lock my screen": (["locking"], []),
    "open notepad": (["opening notepad"], []),
    "close notepad": (["closed notepad"], []),
    "who are you": (["jarvis"], []),
    "switch to friday": (["friday"], []),
    "switch to jarvis": (["jarvis"], []),
}

HARNESS = r'''
import asyncio, json, os, sys, types
from unittest.mock import MagicMock, patch
sys.path.insert(0, ".")
os.environ["JARVIS_USE_GEMINI_LIVE"] = "0"
CORPUS = json.loads(sys.argv[1])

async def main():
    import pyautogui
    stubs = [patch("subprocess.Popen"), patch("subprocess.run"), patch("os.startfile", create=True),
             patch("webbrowser.open"), patch("os.system"),
             patch("jarvis.core.safe_exec.start_app"), patch("jarvis.core.safe_exec.kill_process"),
             patch("jarvis.core.safe_exec.lock_workstation", return_value=True)]
    for name in ("hotkey", "press", "scroll", "click", "typewrite", "write", "moveTo", "screenshot",
                 "keyDown", "keyUp", "doubleClick", "rightClick"):
        stubs.append(patch.object(pyautogui, name, MagicMock(return_value=None)))
    client = MagicMock()
    client.models.generate_content.return_value = types.SimpleNamespace(text="[LLM answer]")
    stubs.append(patch("google.genai.Client", return_value=client))
    for s in stubs:
        s.start()

    import jarvis.gui.websocket_server as w
    srv = w.JARVISWebSocketServer()
    srv._deferred_thread.join(timeout=180)
    if srv.system_control:
        for m in dir(srv.system_control):
            if not m.startswith("_") and callable(getattr(srv.system_control, m)):
                setattr(srv.system_control, m, MagicMock(return_value=None))
    # Never write to the user's real alarms, reminders or tasks
    for obj_name, methods in {"alarm_system": ("set_alarm", "add_alarm", "set_timer"),
                              "reminder_manager": ("add_reminder", "set_reminder", "add"),
                              "task_manager_obj": ("add_task", "add")}.items():
        obj = getattr(srv, obj_name, None)
        for m in methods:
            if obj is not None and hasattr(obj, m):
                setattr(obj, m, MagicMock(return_value=None))
    srv._execute_power_action = MagicMock(return_value="[power]")
    srv._stop_speaking = MagicMock()
    if srv.knowledge:
        srv.knowledge.answer_question = MagicMock(return_value="[knowledge answer]")
    wa = getattr(srv, "whatsapp_handler", None)
    if wa:
        wa.send_message = MagicMock(side_effect=lambda c, m: f"Message sent to {c}.")

    out = {}
    for text in CORPUS:
        srv._pending_power_action = None
        srv._pending_clarify = None
        try:
            reply = srv._try_fast_path(text) or await srv.process_command(text, MagicMock())
        except Exception as e:
            reply = f"EXCEPTION {type(e).__name__}: {e}"
        out[text] = str(reply)
    print("RESULT=" + json.dumps(out))

asyncio.run(main())
'''


@pytest.fixture(scope="module")
def replies():
    proc = subprocess.run([sys.executable, "-c", HARNESS, json.dumps(list(EXPECT))], cwd=ROOT,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=420)
    line = next((l for l in proc.stdout.splitlines() if l.startswith("RESULT=")), None)
    assert line, proc.stdout[-3000:] + proc.stderr[-3000:]
    return json.loads(line[len("RESULT="):])


@pytest.mark.parametrize("command", list(EXPECT))
def test_command_routes_correctly(replies, command):
    reply = replies[command].lower()
    must, must_not = EXPECT[command]
    for s in must:
        assert s.lower() in reply, f"{command!r} -> {replies[command]!r} (missing {s!r})"
    for s in must_not:
        assert s.lower() not in reply, f"{command!r} -> {replies[command]!r} (contains {s!r})"
