"""
Safe process helpers.

App names reach JARVIS from voice/text input, from the Web HUD, and from
LLM tool calls (which can be steered by text in web pages or news). They must
never be pasted into a shell command string: "close chrome & del ..." would run
the second command. These helpers validate the name and never use shell=True.
"""

import os
import re
import subprocess

# Letters, digits, space, dot, underscore, hyphen, plus. No shell metacharacters
# (& | < > ^ % " ' ` ; ( ) etc.) and no path separators.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._+-]{0,63}$")


def is_safe_app_name(name: str) -> bool:
    return bool(name) and bool(_SAFE_NAME.match(name.strip()))


def kill_process(name: str, timeout: float = 3) -> bool:
    """Force-close a process by image name (e.g. 'chrome' or 'chrome.exe').

    Returns True if taskkill reported success. Raises ValueError for names
    that are not plain process names.
    """
    name = (name or "").strip()
    if not is_safe_app_name(name):
        raise ValueError(f"Refusing unsafe process name: {name!r}")
    image = name if name.lower().endswith(".exe") else f"{name}.exe"
    result = subprocess.run(
        ["taskkill", "/IM", image, "/F"],
        capture_output=True, timeout=timeout,
    )
    return result.returncode == 0


def start_app(name: str) -> None:
    """Open an app by name via the Windows shell (PATH, App Paths, Start Menu).

    Raises ValueError for names that are not plain app names.
    """
    name = (name or "").strip()
    if not is_safe_app_name(name):
        raise ValueError(f"Refusing unsafe app name: {name!r}")
    try:
        os.startfile(name)
    except OSError:
        # `start` also resolves App Paths entries. The name is validated above,
        # and passed as its own argument (the empty "" is the window title).
        subprocess.Popen(["cmd", "/c", "start", "", name],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
