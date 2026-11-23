"""
Every optional feature the server imports must actually import.

A failing optional import switches its feature off. That was silent: gestures
never ran because the server also imported a non-existent GestureType, and
sound effects never loaded because it imported SoundEffects, a class that
doesn't exist. A missing third-party package (no camera library in CI, say)
is fine; a broken import of JARVIS's own code is a bug.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_no_broken_jarvis_imports_in_the_server():
    import jarvis.gui.websocket_server as ws
    broken = [e for e in ws.MISSING_IMPORTS
              if "cannot import name" in e or "jarvis" in e.lower()]
    assert broken == []


def test_every_bare_except_is_gone():
    """A bare `except:` also catches Ctrl+C and SystemExit, so JARVIS could
    ignore being told to quit, and it hides real crashes."""
    import re
    bad = []
    for p in (ROOT / "jarvis").rglob("*.py"):
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if re.match(r"\s*except\s*:", line):
                bad.append(f"{p.relative_to(ROOT)}:{i}")
    assert bad == []
