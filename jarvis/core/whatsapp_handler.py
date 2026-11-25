"""
WhatsApp Handler: send messages through WhatsApp Desktop, safely.

Sending is two steps, so a misheard name or message never goes out:

  1. send_message(contact, message) opens the chat and types the message into
     the box WITHOUT sending it. JARVIS says what it typed and to whom.
  2. The user looks at the chat on screen and says "send" (or "yes"), and only
     then confirm_send() presses Enter. "cancel" clears the draft.

How the chat is opened:
  * A saved number (jarvis_data/whatsapp_contacts.json, {"mom": "+91 98..."})
    opens exactly that chat with the text filled in, via whatsapp://send.
  * Otherwise the name is searched in WhatsApp and the top result opened.

Why the old version was unreliable:
  * It pressed Enter on whatever the first search result was and reported
    "Message sent" without checking anything.
  * Its window lookup matched any title containing "WhatsApp", such as a
    browser tab, so keys could go to the wrong window. And Windows refuses
    focus changes from a background process, so activate() often failed
    silently while the HUD stayed in front, and keys went to the HUD.
  * It overwrote the user's clipboard.
Keys are now sent only after checking that WhatsApp Desktop itself is in the
foreground, and the clipboard is restored afterwards.
"""

import logging
_log = logging.getLogger(__name__)

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import quote

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False

try:
    import pyperclip
    PYPERCLIP_AVAILABLE = True
except ImportError:
    PYPERCLIP_AVAILABLE = False


DRAFT_WINDOW_S = 90            # how long "send" still sends the draft
CONTACTS_FILE = Path(__file__).resolve().parent.parent.parent / "jarvis_data" / "whatsapp_contacts.json"

# The WhatsApp Desktop window: "WhatsApp", "(3) WhatsApp", "WhatsApp Beta".
# A browser tab is "WhatsApp - Google Chrome" and must not match.
WHATSAPP_TITLE_RE = re.compile(r"^(?:\(\d+\)\s*)?WhatsApp(?:\s+Beta)?$", re.I)

# "send", "send it", "send the message now", "yes send it", "yes", "confirm"...
SEND_CONFIRM_RE = re.compile(
    r"^(?:(?:yes|yeah|yep|ok(?:ay)?)[\s,]*)?(?:send(?:\s+it|\s+(?:the|that)\s+message|\s+message)?(?:\s+now)?|"
    r"yes|yeah|yep|confirm(?:ed)?|do it|go ahead|proceed)[.!]?$", re.I)
DRAFT_CANCEL_RE = re.compile(r"^(?:no|nope|cancel|abort|don'?t(?:\s+send(?:\s+it)?)?|never ?mind|stop)\b", re.I)


@dataclass
class Draft:
    contact: str
    message: str
    expires_at: float
    hwnd: int = 0


# ─── Win32: find and focus the real WhatsApp window ────────────────────────

class _Win32:
    """The few Win32 calls the handler needs (replaced by a fake in tests)."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ctypes, self.wintypes = ctypes, wintypes
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32

    def _title(self, hwnd) -> str:
        n = self.user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return ""
        buf = self.ctypes.create_unicode_buffer(n + 1)
        self.user32.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value

    def _exe(self, hwnd) -> str:
        pid = self.wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, self.ctypes.byref(pid))
        h = self.kernel32.OpenProcess(0x1000, False, pid.value)  # QUERY_LIMITED_INFORMATION
        if not h:
            return ""
        try:
            buf = self.ctypes.create_unicode_buffer(520)
            size = self.wintypes.DWORD(520)
            if self.kernel32.QueryFullProcessImageNameW(h, 0, buf, self.ctypes.byref(size)):
                return os.path.basename(buf.value)
            return ""
        finally:
            self.kernel32.CloseHandle(h)

    def find_whatsapp(self) -> int:
        """The WhatsApp Desktop main window handle, or 0."""
        found = []

        @self.ctypes.WINFUNCTYPE(self.wintypes.BOOL, self.wintypes.HWND, self.wintypes.LPARAM)
        def _each(hwnd, _):
            if self.user32.IsWindowVisible(hwnd) and WHATSAPP_TITLE_RE.match(self._title(hwnd)):
                exe = self._exe(hwnd).lower()
                # Title alone is enough if the exe can't be read; it is exact
                if not exe or exe.startswith("whatsapp") or exe == "applicationframehost.exe":
                    found.append(hwnd)
                    return False
            return True

        self.user32.EnumWindows(_each, 0)
        return found[0] if found else 0

    def focus(self, hwnd) -> bool:
        """Bring hwnd to the front; True if it really is the foreground window."""
        if self.user32.IsIconic(hwnd):
            self.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        # Windows only lets the foreground process change focus; a synthetic
        # Alt press lifts that lock (the old activate() failed silently).
        self.user32.keybd_event(0x12, 0, 0, 0)
        self.user32.keybd_event(0x12, 0, 0x2, 0)
        self.user32.SetForegroundWindow(hwnd)
        for _ in range(10):
            if self.user32.GetForegroundWindow() == hwnd:
                time.sleep(0.15)
                return True
            time.sleep(0.05)
        return False

    def is_foreground(self, hwnd) -> bool:
        return bool(hwnd) and self.user32.GetForegroundWindow() == hwnd


def load_contacts(path: Path = CONTACTS_FILE) -> Dict[str, str]:
    """Saved numbers, lower-case name -> digits with country code."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for name, number in (raw.items() if isinstance(raw, dict) else []):
        digits = re.sub(r"\D", "", str(number))
        if len(digits) >= 8:
            out[str(name).strip().lower()] = digits
    return out


class WhatsAppHandler:
    """Opens a chat, types a draft, and sends it only after the user confirms."""

    def __init__(self, perception, win=None, contacts_file: Path = CONTACTS_FILE):
        self.perception = perception
        self._win = win
        self.contacts_file = contacts_file
        self._draft: Optional[Draft] = None
        _log.info("[WHATSAPP] Handler Ready")

    # ── helpers ──
    @property
    def win(self):
        if self._win is None:
            self._win = _Win32()
        return self._win

    def _speak(self, text: str):
        if self.perception:
            self.perception.speak(text)
        else:
            _log.info(f"[WHATSAPP] {text}")

    def _get_title(self):
        return getattr(self.perception, 'user_title', 'sir')

    def _t(self) -> str:
        title = self._get_title()
        return f", {title}" if title else ""

    def _launch(self, uri: str = "whatsapp:") -> bool:
        try:
            os.startfile(uri)
            return True
        except OSError:
            _log.debug("Ignored error", exc_info=True)
        for path in (r'%LOCALAPPDATA%\WhatsApp\WhatsApp.exe',
                     r'%LOCALAPPDATA%\Programs\whatsapp-desktop\WhatsApp.exe'):
            path = os.path.expandvars(path)
            if os.path.exists(path):
                os.startfile(path)
                return True
        return False

    def _wait_for_window(self, timeout: float = 10.0) -> int:
        end = time.time() + timeout
        while time.time() < end:
            hwnd = self.win.find_whatsapp()
            if hwnd:
                return hwnd
            time.sleep(0.4)
        return 0

    def _open_focused(self) -> int:
        """WhatsApp in front (launching it if needed); its hwnd, or 0."""
        hwnd = self.win.find_whatsapp()
        if not hwnd:
            if not self._launch():
                return 0
            hwnd = self._wait_for_window()
            if not hwnd:
                return 0
            time.sleep(1.5)  # let the chat list render
        return hwnd if self.win.focus(hwnd) else 0

    def _paste(self, hwnd, text: str, settle: float = 0.3) -> bool:
        """Paste text into WhatsApp, restoring the user's clipboard after."""
        if not self.win.is_foreground(hwnd):
            return False
        if PYPERCLIP_AVAILABLE:
            try:
                saved = pyperclip.paste()
            except Exception:
                saved = None
            pyperclip.copy(text)
            time.sleep(0.1)
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(settle)
            if saved is not None:
                try:
                    pyperclip.copy(saved)
                except Exception:
                    _log.debug("Ignored error", exc_info=True)
        else:
            pyautogui.write(text, interval=0.02)
            time.sleep(settle)
        return True

    # ── public API ──
    def open_whatsapp(self) -> str:
        if self._open_focused():
            return f"Opening WhatsApp{self._t()}."
        import webbrowser
        webbrowser.open("https://web.whatsapp.com")
        return f"WhatsApp Desktop isn't installed, so I opened WhatsApp Web{self._t()}."

    def read_messages(self) -> str:
        self.open_whatsapp()
        return f"WhatsApp is open so you can read your messages{self._t()}."

    def pending_draft(self) -> Optional[Draft]:
        d = self._draft
        if d and time.time() > d.expires_at:
            self._draft = None
            return None
        return d

    def send_message(self, contact_name: str = None, message: str = None) -> str:
        """Open the chat and type the message as a draft; confirm_send() sends it."""
        t = self._t()
        contact = (contact_name or "").strip()
        message = (message or "").strip()
        if not contact:
            return f"Who should I send the message to{t}?"
        if not message:
            return f"What should I say to {contact}{t}?"
        if not PYAUTOGUI_AVAILABLE or os.name != "nt":
            return f"I can't control WhatsApp on this computer{t}."

        # A new request replaces an unsent draft (it stays typed in WhatsApp)
        self._draft = None
        try:
            number = load_contacts(self.contacts_file).get(contact.lower())
            if number:
                hwnd = self._draft_by_number(number, message)
            else:
                hwnd = self._draft_by_search(contact, message)
        except Exception as e:
            _log.warning(f"[WHATSAPP] Draft failed: {e}")
            hwnd = 0
        if not hwnd:
            return (f"I couldn't get WhatsApp ready to message {contact}{t}. "
                    f"Make sure WhatsApp Desktop is installed and logged in.")

        self._draft = Draft(contact, message, time.time() + DRAFT_WINDOW_S, hwnd)
        _log.info(f"[WHATSAPP] Draft to {contact}: {message[:60]}")
        where = "" if number else " Check it's the right chat."
        return (f"I've typed \"{message}\" to {contact} in WhatsApp.{where} "
                f"Say 'send' to send it, or 'cancel'.")

    def _draft_by_number(self, number: str, message: str) -> int:
        # Opens exactly that chat, text already in the box
        if not self._launch(f"whatsapp://send?phone={number}&text={quote(message)}"):
            return 0
        hwnd = self._wait_for_window()
        if not hwnd:
            return 0
        time.sleep(1.0)
        return hwnd if self.win.focus(hwnd) else 0

    def _draft_by_search(self, contact: str, message: str) -> int:
        hwnd = self._open_focused()
        if not hwnd:
            return 0
        pyautogui.hotkey('ctrl', 'f')            # chat search
        time.sleep(0.6)
        pyautogui.hotkey('ctrl', 'a')
        if not self._paste(hwnd, contact, settle=1.8):  # results need a moment
            return 0
        if not self.win.is_foreground(hwnd):
            return 0
        pyautogui.press('down')                  # top result
        time.sleep(0.2)
        pyautogui.press('enter')                 # open the chat
        time.sleep(1.0)
        if not self._paste(hwnd, message, settle=0.4):  # into the message box; NOT sent
            return 0
        return hwnd

    def confirm_send(self) -> str:
        """Send the pending draft (after the user said 'send')."""
        t = self._t()
        d = self.pending_draft()
        if not d:
            return f"There's no message waiting to be sent{t}."
        self._draft = None
        hwnd = self.win.find_whatsapp() or d.hwnd
        # Saying "send" may have put the HUD in front: refocus, and never press
        # Enter unless WhatsApp itself is the foreground window
        if not hwnd or not self.win.focus(hwnd):
            return (f"I couldn't bring WhatsApp to the front, so I didn't send it{t}. "
                    f"The message to {d.contact} is still typed there.")
        pyautogui.press('enter')
        time.sleep(0.3)
        _log.info(f"[WHATSAPP] Sent to {d.contact}")
        return f"Sent to {d.contact}{t}."

    def cancel_draft(self) -> str:
        t = self._t()
        d = self.pending_draft()
        self._draft = None
        if not d:
            return f"Okay{t}."
        hwnd = self.win.find_whatsapp() or d.hwnd
        if hwnd and self.win.focus(hwnd):
            pyautogui.hotkey('ctrl', 'a')       # clear the message box
            pyautogui.press('backspace')
            return f"Cancelled. I cleared the message to {d.contact}{t}."
        return f"Cancelled. The message to {d.contact} is still typed in WhatsApp, unsent{t}."
