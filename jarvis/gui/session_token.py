"""
Per-session WebSocket token.

The JARVIS WebSocket can run commands on this PC, so every client must present
this token (as ``?token=...``). The HUD page gets it injected by the HUD HTTP
server; in-process Python clients (desktop_gui) read it from here.

Set ``JARVIS_WS_TOKEN`` in the environment to share a fixed token with a client
running in another process. Child processes inherit the generated token.
"""

import os
import secrets

_ENV_VAR = "JARVIS_WS_TOKEN"


def get_ws_token() -> str:
    token = os.environ.get(_ENV_VAR)
    if not token:
        token = secrets.token_urlsafe(32)
        os.environ[_ENV_VAR] = token
    return token
