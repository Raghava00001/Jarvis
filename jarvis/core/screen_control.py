"""
Screen Control Handler - Voice-driven mouse and keyboard control
Allows JARVIS to control screen via voice commands
"""

import logging
_log = logging.getLogger(__name__)

from typing import Dict, Any, Optional, Tuple
import os
import re
import time

# Optional imports
try:
    import pyautogui
    pyautogui.FAILSAFE = True  # Move mouse to corner to abort
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False

try:
    import keyboard
    KEYBOARD_AVAILABLE = True
except ImportError:
    KEYBOARD_AVAILABLE = False


# ═══════════════════════════════════════════════════════════════
# FOCUS: keys must reach the app the user means, not JARVIS itself.
# Keyboard actions go to the focused window. When the command was typed into
# the HUD, the HUD has focus, so "next tab" switched the HUD's own browser tab
# and "minimize" minimized JARVIS ("tab switching works sometimes": only when
# spoken while the target app had focus). Hand focus back to the window the
# user was in before (the next one down in z-order) first.
# ═══════════════════════════════════════════════════════════════

_JARVIS_TITLE_RE = re.compile(r"j\.a\.r\.v\.i\.s|\b(?:jarvis|friday) hud\b", re.I)


def is_jarvis_window(title: str) -> bool:
    return bool(title and _JARVIS_TITLE_RE.search(title))


def _window_title(user32, hwnd) -> str:
    import ctypes
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _is_switchable(user32, hwnd) -> bool:
    """A normal app window, as Alt+Tab would list it."""
    import ctypes
    GWL_EXSTYLE, WS_EX_TOOLWINDOW, GW_OWNER, DWMWA_CLOAKED = -20, 0x80, 4, 14
    if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
        return False
    if user32.GetWindow(hwnd, GW_OWNER) or user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
        return False
    cloaked = ctypes.c_int(0)
    try:
        ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
    except Exception:
        _log.debug("Ignored error", exc_info=True)
    title = _window_title(user32, hwnd)
    return not cloaked.value and bool(title) and title != "Program Manager"


def focus_away_from_jarvis() -> Optional[str]:
    """If a JARVIS window has focus, focus the window the user used before it.

    Returns the title of the newly focused window, or None if nothing changed.
    """
    if os.name != "nt":
        return None
    try:
        import ctypes
        user32 = ctypes.windll.user32
        fg = user32.GetForegroundWindow()
        if not is_jarvis_window(_window_title(user32, fg)):
            return None
        GW_HWNDNEXT, VK_MENU, KEYEVENTF_KEYUP = 2, 0x12, 0x2
        hwnd = user32.GetWindow(fg, GW_HWNDNEXT)
        while hwnd:
            if _is_switchable(user32, hwnd):
                title = _window_title(user32, hwnd)
                if not is_jarvis_window(title):
                    # Windows only lets the foreground process change focus; a
                    # synthetic Alt press lifts that lock for this call.
                    user32.keybd_event(VK_MENU, 0, 0, 0)
                    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
                    user32.SetForegroundWindow(hwnd)
                    time.sleep(0.15)  # let the target take focus before keys arrive
                    return title
            hwnd = user32.GetWindow(hwnd, GW_HWNDNEXT)
    except Exception as e:
        _log.warning(f"[SCREEN] Focus hand-off failed: {e}")
    return None


def user_window_title() -> str:
    """Title of the window the user is working in, without changing focus: the
    foreground window, or the one just below it if that's a JARVIS HUD."""
    if os.name != "nt":
        return ""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        title = _window_title(user32, hwnd)
        if not is_jarvis_window(title):
            return title
        GW_HWNDNEXT = 2
        hwnd = user32.GetWindow(hwnd, GW_HWNDNEXT)
        while hwnd:
            if _is_switchable(user32, hwnd):
                title = _window_title(user32, hwnd)
                if not is_jarvis_window(title):
                    return title
            hwnd = user32.GetWindow(hwnd, GW_HWNDNEXT)
    except Exception as e:
        _log.warning(f"[SCREEN] Window lookup failed: {e}")
    return ""


def _has(text: str, *phrases: str) -> bool:
    """Whole-word match ("copyright" is not "copy", "unsaved" is not "save")."""
    return any(re.search(r"(?<![a-z])" + re.escape(p) + r"(?![a-z])", text) for p in phrases)


# "next tab", "switch to the next tab", "go to previous tab", "tab 3"
_NEXT_TAB_RE = re.compile(r"\b(?:next|right)\s+tab\b|\btab\s+(?:to\s+the\s+)?right\b|\bforward\s+a\s+tab\b")
_PREV_TAB_RE = re.compile(r"\b(?:previous|prev|last|left|back)\s+tab\b|\btab\s+(?:to\s+the\s+)?left\b|\bback\s+a\s+tab\b")
_TAB_NUMBER_RE = re.compile(r"\btab\s+(?:number\s+)?([1-8])\b|\b(first|second|third|fourth|fifth)\s+tab\b")
_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}


def is_tab_command(text: str) -> bool:
    t = (text or "").lower()
    return bool(_NEXT_TAB_RE.search(t) or _PREV_TAB_RE.search(t) or _TAB_NUMBER_RE.search(t)
                or re.search(r"\b(?:new|open a new|close (?:this |the )?)\s*tab\b", t)
                or re.search(r"\b(?:reopen|restore)\s+(?:the\s+)?(?:last\s+|closed\s+)*tab\b", t))


class ScreenControlHandler:
    """
    Voice-controlled screen interaction.
    Commands: click, double click, right click, scroll, move mouse
    """
    
    def __init__(self):
        _log.info("[SCREEN] Initializing Screen Control...")
        
        self.pyautogui_available = PYAUTOGUI_AVAILABLE
        self.keyboard_available = KEYBOARD_AVAILABLE
        
        if PYAUTOGUI_AVAILABLE:
            _log.info("[SCREEN] pyautogui available")
            self.screen_width, self.screen_height = pyautogui.size()
        else:
            _log.warning("[SCREEN] pyautogui not available - screen control disabled")
            self.screen_width, self.screen_height = 1920, 1080
        
        # Named positions for quick navigation
        self.named_positions = {
            "center": (0.5, 0.5),
            "top left": (0.1, 0.1),
            "top right": (0.9, 0.1),
            "bottom left": (0.1, 0.9),
            "bottom right": (0.9, 0.9),
            "top": (0.5, 0.1),
            "bottom": (0.5, 0.9),
            "left": (0.1, 0.5),
            "right": (0.9, 0.5),
        }
        
        _log.info("[SCREEN] Screen Control Ready")
    
    def handle(self, command: str, entities: Dict[str, Any] = None) -> str:
        """Handle screen control commands"""
        if not self.pyautogui_available:
            return "Screen control is not available. Please install pyautogui."
        
        c = command.lower()

        # ── Mouse: acts where the cursor is, focus doesn't matter ──
        if _has(c, "double click", "double-click"):
            return self._double_click()
        if _has(c, "right click", "right-click"):
            return self._right_click()
        if _has(c, "click"):
            return self._click(self._extract_position(c))
        if _has(c, "scroll down"):
            return self._scroll(-self._extract_amount(c, default=3))
        if _has(c, "scroll up"):
            return self._scroll(self._extract_amount(c, default=3))
        if _has(c, "move mouse", "move cursor"):
            position = self._extract_position(c)
            return self._move_to(position) if position else "Please specify where to move the cursor."
        if _has(c, "switch window", "alt tab"):
            return self._hotkey("alt", "tab")

        # ── Keyboard: goes to the focused window, so make sure that's the
        #    user's app and not JARVIS's own HUD (see focus_away_from_jarvis) ──
        action = self._keyboard_action(c, command)
        if action is None:
            return "I didn't understand that screen control command."
        focused = focus_away_from_jarvis()
        result = action()
        if focused:
            _log.info(f"[SCREEN] Sent to '{focused[:50]}' (moved focus off the HUD)")
        return result

    def _keyboard_action(self, c: str, original: str):
        """Map a command to a zero-argument callable, or None if it isn't one."""
        if _NEXT_TAB_RE.search(c):
            return lambda: self._hotkey("ctrl", "tab", label="Next tab.")
        if _PREV_TAB_RE.search(c):
            return lambda: self._hotkey("ctrl", "shift", "tab", label="Previous tab.")
        m = _TAB_NUMBER_RE.search(c)
        if m:
            n = int(m.group(1)) if m.group(1) else _ORDINALS[m.group(2)]
            return lambda: self._hotkey("ctrl", str(n), label=f"Switched to tab {n}.")
        if re.search(r"\b(?:reopen|restore)\s+(?:the\s+)?(?:last\s+|closed\s+)*tab\b", c):
            return lambda: self._hotkey("ctrl", "shift", "t", label="Reopened the last closed tab.")
        if _has(c, "new tab"):
            return lambda: self._hotkey("ctrl", "t", label="Opened a new tab.")
        if _has(c, "close") and _has(c, "tab"):
            return lambda: self._hotkey("ctrl", "w", label="Closed the tab.")
        if _has(c, "close window", "close this window"):
            return lambda: self._hotkey("alt", "f4", label="Closed the window.")
        if _has(c, "zoom in"):
            return lambda: self._hotkey("ctrl", "+", label="Zoomed in.")
        if _has(c, "zoom out"):
            return lambda: self._hotkey("ctrl", "-", label="Zoomed out.")
        if _has(c, "press enter", "hit enter", "press escape", "press tab", "press backspace",
                "press delete", "press space"):
            return lambda: self._press_key(c)
        if re.match(r"^(?:please\s+)?type\b", c):
            text = self._extract_text_to_type(original)
            if not text:
                return lambda: "Please specify what to type."
            return lambda: self._type_text(text)
        if _has(c, "copy"):
            return lambda: self._hotkey("ctrl", "c", label="Copied.")
        if _has(c, "paste"):
            return lambda: self._hotkey("ctrl", "v", label="Pasted.")
        if _has(c, "undo"):
            return lambda: self._hotkey("ctrl", "z", label="Undone.")
        if _has(c, "redo"):
            return lambda: self._hotkey("ctrl", "y", label="Redone.")
        if _has(c, "select all"):
            return lambda: self._hotkey("ctrl", "a", label="Selected all.")
        if _has(c, "save"):
            return lambda: self._hotkey("ctrl", "s", label="Saved.")
        if _has(c, "minimize", "minimise"):
            return lambda: self._hotkey("win", "down", label="Minimized the window.")
        if _has(c, "maximize", "maximise"):
            return lambda: self._hotkey("win", "up", label="Maximized the window.")
        if _has(c, "restore"):
            return lambda: self._hotkey("win", "down", label="Restored the window.")
        return None
    
    def _click(self, position: Optional[Tuple[int, int]] = None) -> str:
        """Perform a click"""
        if position:
            pyautogui.click(position[0], position[1])
            return f"Clicked at position {position}."
        else:
            pyautogui.click()
            return "Clicked at current cursor position."
    
    def _double_click(self) -> str:
        """Perform a double click"""
        pyautogui.doubleClick()
        return "Double clicked."
    
    def _right_click(self) -> str:
        """Perform a right click"""
        pyautogui.rightClick()
        return "Right clicked."
    
    def _scroll(self, amount: int) -> str:
        """Scroll the mouse wheel"""
        pyautogui.scroll(amount)
        direction = "up" if amount > 0 else "down"
        return f"Scrolled {direction}."
    
    def _move_to(self, position: Tuple[int, int]) -> str:
        """Move cursor to position"""
        pyautogui.moveTo(position[0], position[1], duration=0.3)
        return f"Moved cursor to {position}."
    
    def _press_key(self, command: str) -> str:
        """Press a keyboard key"""
        if "enter" in command:
            pyautogui.press("enter")
            return "Pressed Enter."
        elif "escape" in command or "esc" in command:
            pyautogui.press("escape")
            return "Pressed Escape."
        elif "tab" in command:
            pyautogui.press("tab")
            return "Pressed Tab."
        elif "backspace" in command:
            pyautogui.press("backspace")
            return "Pressed Backspace."
        elif "delete" in command:
            pyautogui.press("delete")
            return "Pressed Delete."
        elif "space" in command:
            pyautogui.press("space")
            return "Pressed Space."
        return "Unknown key."
    
    def _type_text(self, text: str) -> str:
        """Type text"""
        pyautogui.typewrite(text, interval=0.02)
        return f"Typed: {text}"
    
    def _hotkey(self, *keys, label: Optional[str] = None) -> str:
        """Press a hotkey combination"""
        pyautogui.hotkey(*keys)
        return label or f"Pressed {' + '.join(keys)}."
    
    def _extract_position(self, command: str) -> Optional[Tuple[int, int]]:
        """Extract position from command"""
        # Check for named positions
        for name, (rx, ry) in self.named_positions.items():
            if name in command:
                x = int(self.screen_width * rx)
                y = int(self.screen_height * ry)
                return (x, y)
        
        # Try to extract coordinates (e.g., "at 500, 300")
        coord_match = re.search(r'(\d+)\s*,\s*(\d+)', command)
        if coord_match:
            x = int(coord_match.group(1))
            y = int(coord_match.group(2))
            return (x, y)
        
        return None
    
    def _extract_amount(self, command: str, default: int = 3) -> int:
        """Extract scroll amount from command"""
        match = re.search(r'(\d+)', command)
        if match:
            return int(match.group(1))
        
        # Word-based amounts
        if "a lot" in command or "much" in command:
            return 10
        elif "a little" in command or "slightly" in command:
            return 1
        
        return default
    
    def _extract_text_to_type(self, command: str) -> Optional[str]:
        """Extract text to type from command"""
        # Try to find quoted text
        quoted = re.search(r'["\'](.+?)["\']', command)
        if quoted:
            return quoted.group(1)
        
        # Try "type X" pattern
        match = re.search(r'type\s+(.+?)(?:\s*$|\s+and\s+)', command, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        
        return None
    
    def get_current_position(self) -> Tuple[int, int]:
        """Get current mouse position"""
        if self.pyautogui_available:
            return pyautogui.position()
        return (0, 0)
    
    def get_screen_size(self) -> Tuple[int, int]:
        """Get screen dimensions"""
        return (self.screen_width, self.screen_height)
