"""The HUD server's source, for tests that check what the code says.

The server is jarvis/gui/websocket_server.py plus its parts in jarvis/gui/server/.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def server_source() -> str:
    files = [ROOT / "jarvis/gui/websocket_server.py"] + sorted((ROOT / "jarvis/gui/server").glob("*.py"))
    return "\n".join(f.read_text(encoding="utf-8") for f in files)
