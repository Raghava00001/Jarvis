"""
Command rules: how JARVIS recognises wake words, exit commands and PC power
commands, plus who may connect to the WebSocket.

Extracted from websocket_server.py (v2.6) so these safety-critical rules live
in one small, testable module instead of a 3,000-line file.
"""

import re

# Browser origins allowed to open the WebSocket (the Web HUD served on :8080).
# None = no Origin header (desktop_gui / Python clients); browsers always send one.
HUD_HTTP_PORT = 8080
ALLOWED_WS_ORIGINS = [
    f"http://localhost:{HUD_HTTP_PORT}",
    f"http://127.0.0.1:{HUD_HTTP_PORT}",
    None,
]

# ── Power / exit command matching ────────────────────────────────────────────
# Matched against the WHOLE command (after the wake word is stripped) so that
# sentences like "how do I shutdown linux?" or "my phone rebooted" don't quit
# JARVIS or restart the PC.
WAKE_WORD_RE = re.compile(r'^(?:hey\s+)?(?:jarvis|friday)[,!.\s]*', re.I)
JARVIS_EXIT_RE = re.compile(
    r'^(?:please\s+)?(?:'
    r'(?:shutdown|shut\s+down|power\s+off|go\s+offline)(?:\s+(?:jarvis|friday|yourself))?'
    r'|(?:exit|quit|close)\s+(?:jarvis|friday)'
    r'|(?:jarvis|friday)\s+(?:shutdown|shut\s+down)'
    r')(?:\s+please)?[\s.!]*$'
)
PC_SHUTDOWN_RE = re.compile(
    r'\b(?:shut\s*down|switch\s+off|turn\s+off|power\s+off)\s+(?:the\s+|my\s+)?'
    r'(?:laptop|computer|pc|system)\b'
)
PC_RESTART_RE = re.compile(
    r'\b(?:restart|reboot)\s+(?:the\s+|my\s+)?(?:laptop|computer|pc|system)\b'
    r'|^reboot[\s.!]*$'
)
CONFIRM_RE = re.compile(r'^(?:yes|yeah|yep|confirm(?:ed)?|do it|go ahead|proceed)\b')
CANCEL_RE = re.compile(r"^(?:no|nope|cancel|abort|don'?t|never ?mind|stop)\b")
POWER_CONFIRM_WINDOW_S = 30


def check_ws_token(connection, request):
    """websockets process_request hook: 403 unless ?token=<session token>."""
    from http import HTTPStatus
    from urllib.parse import urlsplit, parse_qs
    import hmac
    from jarvis.gui.session_token import get_ws_token
    supplied = parse_qs(urlsplit(request.path).query).get("token", [""])[0]
    if not hmac.compare_digest(supplied.encode(), get_ws_token().encode()):
        print("[WebSocket] Rejected connection without a valid token")
        return connection.respond(HTTPStatus.FORBIDDEN, "Missing or invalid token\n")
    return None


def normalize_command(text: str) -> str:
    """Lower-case, trim and strip a leading wake word."""
    return WAKE_WORD_RE.sub('', (text or '').lower().strip()).strip()


def is_jarvis_exit_command(cmd: str) -> bool:
    return bool(JARVIS_EXIT_RE.match(cmd))


# ── "Stop talking" ──────────────────────────────────────────────────────────
# Whole-command match. The old rule also accepted anything starting with
# "stop ", so "stop the music", "stop gesture control" or "stop the timer"
# silenced JARVIS and put it into quiet mode instead of doing the task.
STOP_SPEAKING_RE = re.compile(
    r"^(?:okay\s+|ok\s+|please\s+|jarvis\s+)?(?:"
    r"stop|enough|silence|quiet|hush|stfu|shush"
    r"|stop\s+(?:it|that|now|please|talking|speaking|there)"
    r"|shut\s+up|shut\s+the\s+fuck\s+up|be\s+quiet|keep\s+quiet|stay\s+(?:quiet|silent)|keep\s+silent"
    r"|that'?s\s+enough"
    r")(?:\s+please)?[\s.!]*$"
)


def is_stop_speaking_command(cmd: str) -> bool:
    """True for "stop", "shut up", "keep quiet"…, not for "stop the music"."""
    return bool(STOP_SPEAKING_RE.match(normalize_command(cmd)))


COMMAND_MESSAGE_TYPES = ('text_input', 'voice_input', 'command', 'chat')


def is_urgent_message(data: dict) -> bool:
    """Messages answered at once, never queued behind a slow command."""
    msg_type = data.get('type', '')
    if msg_type in ('stop_speaking', 'get_state', 'get_status'):
        return True
    if msg_type in COMMAND_MESSAGE_TYPES:
        text = data.get('text', '') or (data.get('payload') or {}).get('text', '')
        return is_stop_speaking_command(text)
    return False


def detect_pc_power_action(cmd: str):
    """Return 'shutdown', 'restart' or None for a normalized command."""
    if PC_RESTART_RE.search(cmd):
        return 'restart'
    if PC_SHUTDOWN_RE.search(cmd):
        return 'shutdown'
    return None
