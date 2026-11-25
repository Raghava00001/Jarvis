"""
Fix typos in command words before routing: "wats the wether in paris",
"whats the tiem" used to go to the AI chat instead of weather and time.

Deliberately narrow, so real words are never "corrected":
  * long, distinctive command words (weather, reminder, volume ...) accept one
    edit (a missing, extra, wrong or swapped letter);
  * short words (time, news, alarm ...) accept only two swapped letters
    ("tiem" -> "time"), so "tide" or "mews" stay as they are;
  * a list of real words that are one edit from a command word ("feather",
    "leather", "whether") is never changed.
"""

import logging
import re

_log = logging.getLogger(__name__)

# One edit away is fine for these: long, and no common English word is that close
LONG_WORDS = (
    "weather", "reminder", "reminders", "volume", "brightness", "screenshot", "battery", "bluetooth",
    "calculator", "notepad", "youtube", "whatsapp", "spotify", "translate", "calendar", "schedule",
    "clipboard", "minimize", "maximize", "wellness", "temperature", "forecast", "headlines",
)
# Only a swap of two neighbouring letters for these
SHORT_WORDS = ("time", "news", "joke", "alarm", "timer", "music", "notes", "tasks", "story", "email",
               "today", "remind", "open", "close", "date")

REAL_WORDS = {"feather", "leather", "heather", "whether", "wither", "tether", "nether", "weathers",
              "volumes", "column", "scheduled", "notebook", "forecasts", "minimise", "maximise"}


def _one_edit(a: str, b: str) -> bool:
    """True if a and b differ by exactly one insert, delete, substitution or adjacent swap."""
    if a == b:
        return False
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        diff = [i for i in range(la) if a[i] != b[i]]
        if len(diff) == 1:
            return True
        return len(diff) == 2 and diff[1] == diff[0] + 1 and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]]
    if la > lb:
        a, b = b, a
    for i in range(len(b)):
        if b[:i] + b[i + 1:] == a:
            return True
    return False


def _swapped(a: str, b: str) -> bool:
    if len(a) != len(b) or a == b:
        return False
    diff = [i for i in range(len(a)) if a[i] != b[i]]
    return len(diff) == 2 and diff[1] == diff[0] + 1 and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]]


def correct_word(word: str) -> str:
    w = word.lower()
    if len(w) < 4 or w in REAL_WORDS or w in LONG_WORDS or w in SHORT_WORDS:
        return word
    if len(w) >= 5:
        for k in LONG_WORDS:
            if _one_edit(w, k):
                return k
    for k in SHORT_WORDS:
        if _swapped(w, k):
            return k
    return word


def fix_typos(text: str) -> str:
    """The command with typos in command words corrected (everything else unchanged)."""
    fixed = re.sub(r"[A-Za-z]+", lambda m: correct_word(m.group(0)), text or "")
    if fixed != text:
        _log.info(f"[TYPO] '{text}' -> '{fixed}'")
    return fixed
