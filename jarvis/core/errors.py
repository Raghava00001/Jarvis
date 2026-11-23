"""
Errors JARVIS recovers from.

Many places try one way, and if it fails, quietly try another (a second news
source, another way to open an app). They used to say `except: pass`, so a
feature that was broken looked merely slow, or silently fell back forever.
Call recovered() instead: the fallback still happens, and the reason is shown.
"""

import traceback

_seen = set()


def recovered(where: str, err: BaseException) -> None:
    """Report an error that was handled by falling back.

    One line every time; the file and line it came from the first time it is
    seen at that spot.
    """
    print(f"[{where}] recovered from {type(err).__name__}: {err}")
    frames = traceback.extract_tb(err.__traceback__) if err.__traceback__ else []
    if frames:
        last = frames[-1]
        key = (where, type(err).__name__, last.filename, last.lineno)
        if key not in _seen:
            _seen.add(key)
            print(f"[{where}]   at {last.filename}:{last.lineno} in {last.name}")
