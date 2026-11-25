"""
Screen vision: JARVIS can look at the screen.

"what is this?", "explain this error", "what am I looking at?", "summarise this
page" used to reach the text model with no idea what "this" was, so it either
guessed or asked the user. Screen reading needed Tesseract OCR, which most
setups don't have. Both now send a screenshot to Gemini's vision model.

"This" is whatever the user is working in: if JARVIS's own HUD has focus (the
command was typed there), focus goes back to the previous window first, so the
screenshot shows the user's app rather than JARVIS.
"""

import logging
_log = logging.getLogger(__name__)

import io
import re
from typing import Optional

from jarvis.core.llm import ask_gemini, gemini_client
from jarvis.core.screen_control import focus_away_from_jarvis

MAX_WIDTH = 1600  # enough to read UI text; keeps the upload small and fast

# Questions about something on screen. "this week"/"this year"… are about time.
_SCREEN_QUESTION_RE = re.compile(
    r"\b(?:on|at|of)\s+(?:my|the|this)\s+screen\b"
    r"|\bwhat\s+am\s+i\s+(?:looking\s+at|seeing|reading)\b"
    r"|\blook\s+at\s+(?:this|my\s+screen|the\s+screen)\b"
    r"|\bcan\s+you\s+see\s+(?:this|my\s+screen|the\s+screen|what)\b"
    r"|^(?:hey\s+)?(?:jarvis,?\s+)?(?:what(?:'s|s|\s+is|\s+are|\s+does|\s+do)|explain|describe|summari[sz]e"
    r"|translate|fix|debug|check|analy[sz]e|tell\s+me\s+about|help\s+(?:me\s+)?with|how\s+do\s+i\s+fix)"
    r"\b[^?]*?\b(?:this|these)\b"
    r"(?!\s+(?:week|weekend|year|month|morning|evening|afternoon|night|time|season|song|music))"
)


def is_screen_question(text: str) -> bool:
    return bool(_SCREEN_QUESTION_RE.search((text or "").lower().strip()))


def capture_screen_png(max_width: int = MAX_WIDTH) -> bytes:
    """Screenshot of the primary screen as PNG bytes, scaled to max_width."""
    from PIL import ImageGrab
    img = ImageGrab.grab()
    if img.width > max_width:
        img = img.resize((max_width, round(img.height * max_width / img.width)))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


SCREEN_SYSTEM = (
    "You are JARVIS, a voice assistant that can see the user's screen (the attached screenshot). "
    "Answer the user's question about what is on it. 'This' means the main thing in focus: the "
    "active window, a selected item, an error dialog or the code in view. Quote error messages "
    "exactly and say what they mean and how to fix them. Be specific to what you actually see; "
    "if something is unreadable, say so. Reply in 2-4 spoken sentences: no markdown, no lists."
)

READ_SYSTEM = (
    "You are JARVIS, a voice assistant. Read out the main text on the attached screenshot "
    "(the active window's content, not menus, toolbars or taskbar), in reading order. "
    "If there is a lot, read the first few sentences and summarise the rest in one sentence. "
    "Plain spoken text: no markdown."
)


def vision_available() -> bool:
    return gemini_client() is not None


def ask_about_screen(question: str, system: str = SCREEN_SYSTEM) -> Optional[str]:
    """Answer a question about the screen, or None if vision isn't available."""
    if not vision_available():
        return None
    focused = focus_away_from_jarvis()
    if focused:
        _log.info(f"[VISION] Looking at '{focused[:50]}' (moved focus off the HUD)")
    png = capture_screen_png()
    return ask_gemini(question, system=system, images=[png])


def read_screen_text() -> Optional[str]:
    """Read the screen's main text with the vision model (no Tesseract needed)."""
    return ask_about_screen("Read the text on my screen.", system=READ_SYSTEM)
