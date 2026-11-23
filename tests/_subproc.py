"""Run a Python script in a subprocess with a timeout that really works on Windows.

In a venv on Windows, sys.executable is a launcher that starts the real
interpreter as a child. subprocess.run(timeout=...) killed only the launcher;
the interpreter kept the pipes open and pytest waited forever. On timeout this
kills the whole process tree and fails the test instead.
"""

import os
import subprocess
import sys


def run_python(script: str, *args: str, cwd, timeout: float) -> subprocess.CompletedProcess:
    proc = subprocess.Popen([sys.executable, "-c", script, *args], cwd=cwd,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace")
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        else:
            proc.kill()
        out, err = proc.communicate(timeout=30)
        raise AssertionError(f"subprocess timed out after {timeout}s\n{out[-3000:]}\n{err[-3000:]}")
    return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)
