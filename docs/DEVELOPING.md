# Developing JARVIS

How to run, test and change JARVIS without breaking it. The design is described in
[ARCHITECTURE.md](ARCHITECTURE.md).

## Setup

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
copy .env.example .env      # then add GEMINI_API_KEY (and optionally Groq/OpenRouter keys)
```

Use the project's `.venv` for everything below. The system Python may have
different versions of torch/numpy, and the ML brain then fails silently.

## Running

```powershell
python jarvis/main.py                     # desktop launcher + HUD
python jarvis/gui/websocket_server.py     # the server and HUD only
```

The HUD is served at http://localhost:8080; the WebSocket listens on
127.0.0.1:8765 and only accepts the HUD (origin check + per-session token).

### Console output

Every module logs through `logging` (`_log = logging.getLogger(__name__)`); there
is no `print()`. Set `JARVIS_LOG_LEVEL` in `.env`:

| Level | Shows |
|---|---|
| `INFO` (default) | the usual console output |
| `WARNING` | only problems |
| `DEBUG` | also every error JARVIS recovered from, with file, line and traceback |

## Tests

```powershell
python -m pytest tests -q
```

About 670 tests, ~2 minutes. CI runs the same suite on Windows for every pull request.

Some tests boot the real server in a subprocess (`test_architecture.py`,
`test_routing_corpus.py`) and send real commands through it, with every side
effect stubbed.

### Rules the tests enforce

| Rule | Why |
|---|---|
| No `print()`; no `except: pass`; no bare `except:` | errors are logged, never hidden |
| No function over 120 lines (a few older ones are budgeted and may only shrink) | long functions hid bugs; split into named steps |
| pyflakes warnings only go down (a budget); no undefined names | unused code and typos caught early |
| No control characters in source | a `\b` written through a script once became a backspace and silently broke a regex |
| Server files under 550 lines; the server keeps its parts | it was a 3,262-line file |
| Every `self.method()` call exists | a call to a missing method threw away every news reply |
| Every declared Gemini tool has a method | a declared but unwired tool fails only when spoken |
| One module identity; one instance of each subsystem | modules loaded twice meant two alarm systems |

When a budget test says a function or the warning count went **down**, lower the
number in `tests/test_code_quality.py`: that locks the improvement in.

## Testing with real commands, safely

When you run the real server to check a feature, it acts on your PC and your data
unless you stop it. Stub, at least:

- key presses and mouse: every `pyautogui` function, and `focus_away_from_jarvis`
- app launch / close / lock: `jarvis.core.safe_exec.start_app`, `kill_process`, `lock_workstation`
- shutdown / restart: `server._execute_power_action`
- **email: `smtplib.SMTP` and `smtplib.SMTP_SSL`** (a test once tried to send real mail)
- WhatsApp: the handler's `send_message`
- screenshots and screen vision: `ScreenshotHandler.take_screenshot`,
  `screen_vision.capture_screen_png` / `ask_about_screen`
- audio: `hud_perception.voice_out`; media keys: `MediaKeyController`
- your data: alarms, reminders, tasks, notes (`SmartNotes.add_note`), chat history,
  habit learning (`PatternLearner._save`), memory (`memory_store.MEMORY_FILE`),
  gesture preference (`GESTURE_PREFS`), workflows

And back up `jarvis/data` and `jarvis_data` first, then compare afterwards.
`tests/test_routing_corpus.py` shows a complete harness.

## Adding a feature

See "Adding a feature" in [ARCHITECTURE.md](ARCHITECTURE.md). In short: one
handler in `HANDLER_MAP`, example phrases, an optional keyword rule, an optional
Gemini tool entry, and a line in the routing corpus.
