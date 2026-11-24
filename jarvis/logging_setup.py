"""
Console logging for JARVIS.

Every module logs through `logging.getLogger(__name__)` instead of print().
That gives each message a level, so the console can be quieted or made more
verbose without touching code:

    JARVIS_LOG_LEVEL=WARNING   only problems
    JARVIS_LOG_LEVEL=INFO      the usual console output (default)
    JARVIS_LOG_LEVEL=DEBUG     also errors JARVIS recovered from on its own,
                               with where they happened and the traceback

Messages look exactly like the old print() output ("[ALARMS] System Ready");
debug lines are prefixed with their module and line.

Only the `jarvis` loggers (and `__main__`, for scripts) get this handler, and
they don't pass records on to the root logger: third-party libraries keep
their own logging setup, and nothing is printed twice when a library (e.g.
absl, loaded with MediaPipe) adds a root handler.

Standard library only: this runs when the `jarvis` package is imported.
"""

import logging
import os
import sys

_HANDLER_FLAG = "_jarvis_console_handler"


class _ConsoleHandler(logging.Handler):
    """Writes to whatever sys.stdout is at the time (so redirects and test
    capture work), and never fails on characters the console can't show."""

    def emit(self, record):
        try:
            text = self.format(record) + "\n"
            stream = sys.stdout
            if stream is None:  # pythonw: no console
                return
            try:
                stream.write(text)
            except UnicodeEncodeError:
                enc = getattr(stream, "encoding", None) or "ascii"
                stream.write(text.encode(enc, "replace").decode(enc, "replace"))
            stream.flush()
        except Exception:
            self.handleError(record)


class _ConsoleFormatter(logging.Formatter):
    def format(self, record):
        text = record.getMessage()
        if record.levelno <= logging.DEBUG:
            text = f"[debug] {record.name}:{record.lineno} {text}"
        if record.exc_info and record.levelno <= logging.DEBUG:
            text += "\n" + self.formatException(record.exc_info)
        elif record.exc_info:
            # Above debug: one line, not a traceback
            exc = record.exc_info[1]
            text += f" ({type(exc).__name__}: {exc})"
        return text


def level_from_env(default: int = logging.INFO) -> int:
    name = os.getenv("JARVIS_LOG_LEVEL", "").strip().upper()
    return getattr(logging, name, default) if name else default


def install(level: int = None) -> None:
    """Attach the console handler to the jarvis loggers (idempotent)."""
    level = level_from_env() if level is None else level
    for name in ("jarvis", "__main__"):
        logger = logging.getLogger(name)
        logger.setLevel(level)
        logger.propagate = False
        if not any(getattr(h, _HANDLER_FLAG, False) for h in logger.handlers):
            handler = _ConsoleHandler()
            handler.setFormatter(_ConsoleFormatter())
            setattr(handler, _HANDLER_FLAG, True)
            logger.addHandler(handler)
