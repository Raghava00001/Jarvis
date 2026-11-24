"""
Fast path: instant answers for common commands (open/close app, volume,
brightness, screenshot, YouTube, time, date), before the full routing chain.

Extracted from websocket_server.py (v2.6). `server` is the JARVISWebSocketServer.
"""

import logging
import re
_log = logging.getLogger(__name__)

import threading
import time
from datetime import datetime
from pathlib import Path


def _fast_path_applies(cmd: str, text: str) -> bool:
    """Not for tab commands ("open a new tab", "close this tab": screen control)
    or several commands at once ("open notepad and set a timer"): the open/close
    rules took the whole sentence as an app name."""
    from jarvis.core.screen_control import is_tab_command
    from jarvis.gui.command_processor import split_compound_command
    return not (is_tab_command(cmd) or len(split_compound_command(text)) > 1)


def try_fast_path(server, text: str):
    """Instant execution for common commands — no routing chain."""
    cmd = text.lower().strip()
    if not _fast_path_applies(cmd, text):
        return None
    title = getattr(getattr(server, 'hud_perception', None), 'user_title', 'sir')

    # ── CLOSE APP (instant via taskkill) ──
    close_match = re.match(r'^close\s+(.+)', cmd)
    if close_match:
        app = close_match.group(1).strip()
        try:
            # Map common names to process names
            APP_PROCESS = {
                'whatsapp': 'WhatsApp', 'chrome': 'chrome',
                'brave': 'brave', 'firefox': 'firefox',
                'spotify': 'Spotify', 'discord': 'Discord',
                'notepad': 'notepad', 'calculator': 'Calculator',
                'edge': 'msedge', 'vscode': 'Code', 'vs code': 'Code',
                'telegram': 'Telegram', 'explorer': 'explorer',
            }
            proc = APP_PROCESS.get(app, app)
            from jarvis.core.safe_exec import kill_process, is_safe_app_name
            if not is_safe_app_name(proc):
                return f"I can't close '{app}', {title}. That isn't a valid app name."
            kill_process(proc)
            _log.info(f"[FAST] Closed {app}")
            return f"Closed {app}, {title}."
        except Exception:
            return None  # Fall through to normal pipeline

    # ── RESUME/PAUSE VIDEO (space key, not media keys) ──
    if any(w in cmd for w in ['resume video', 'resume the video', 'play video',
                               'pause video', 'pause the video', 'resume youtube',
                               'play youtube', 'pause youtube']):
        try:
            import pyautogui
            pyautogui.press('space')  # Space = play/pause in YouTube
            action = 'Resumed' if 'resume' in cmd or 'play' in cmd else 'Paused'
            _log.info(f"[FAST] {action} video (space key)")
            return f"{action} the video, {title}."
        except Exception:
            return None

    # ── SCREENSHOT (instant) ──
    if 'screenshot' in cmd or 'screen capture' in cmd:
        try:
            import pyautogui
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            path = Path.home() / 'Pictures' / f'jarvis_screenshot_{ts}.png'
            pyautogui.screenshot(str(path))
            _log.info(f"[FAST] Screenshot saved: {path}")
            return f"Screenshot saved, {title}."
        except Exception:
            return None

    # ── VOLUME / BRIGHTNESS (instant; the reply is what really happened) ──
    for kind in ('volume', 'brightness'):
        if kind in cmd and server.system_control:
            from jarvis.core.system_control import parse_level_request
            if parse_level_request(cmd) is not None:
                return server.system_control.adjust(kind, cmd)

    # ── PLAY IN YOUTUBE (instant — prevents Spotify conflict) ──
    yt_match = re.search(r'play\s+(.+?)\s+(?:in|on)\s+youtube', cmd)
    if yt_match:
        query = yt_match.group(1).strip()
        try:
            import urllib.parse, webbrowser
            url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
            webbrowser.open(url)
            # Auto-click first video after page loads
            def _auto_play():
                import pyautogui
                time.sleep(3.5)
                pyautogui.press('tab', presses=8, interval=0.05)
                time.sleep(0.2)
                pyautogui.press('enter')
            threading.Thread(target=_auto_play, daemon=True).start()
            _log.info(f"[FAST] YouTube search: {query}")
            return f"Playing {query} on YouTube, {title}."
        except Exception:
            return None

    # ── OPEN APP (instant) ──
    open_match = re.match(r'^(?:open|launch|start)\s+(.+)', cmd)
    if open_match:
        app = open_match.group(1).strip()
        try:
            # Try AppSwitcher first, then fallback to os.startfile
            switcher = getattr(server, 'app_switcher', None)
            if switcher and hasattr(switcher, 'open_app'):
                switcher.open_app(app)
            else:
                from jarvis.core.safe_exec import start_app, is_safe_app_name
                if not is_safe_app_name(app):
                    return f"I can't open '{app}', {title}. That isn't a valid app name."
                start_app(app)
            _log.info(f"[FAST] Opened {app}")
            return f"Opening {app}, {title}."
        except Exception:
            return None

    # ── TIME (instant) ──
    if cmd in ['time', 'what time is it', 'what is the time', 'tell me the time', "what's the time"]:
        now = datetime.now().strftime('%I:%M %p')
        return f"It's {now}, {title}."

    # ── DATE (instant) ──
    if cmd in ['date', 'what date is it', "what's the date", 'what is the date', "what's today's date"]:
        now = datetime.now().strftime('%A, %B %d, %Y')
        return f"It's {now}, {title}."

    # ── STOP / PAUSE / RESUME VIDEO (instant) ──
    if any(p in cmd for p in ['stop video', 'pause video', 'stop the video', 'pause the video',
                               'resume video', 'resume the video', 'unpause',
                               'stop playing', 'stop music', 'pause music',
                               'play pause', 'play/pause']):
        try:
            import pyautogui
            pyautogui.press('space')
            _log.info(f"[FAST] Toggled playback")
            if 'resume' in cmd or 'unpause' in cmd:
                return f"Resuming playback, {title}."
            return f"Paused, {title}."
        except Exception:
            return None

    return None  # No fast path — use normal pipeline
