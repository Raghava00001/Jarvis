"""
Command tables and phrase lists used by the HUD server's command handling.
"""

import logging
import re

_log = logging.getLogger(__name__)

PRECISE_RULE_INTENTS = {
    'search_news',      # "news about X", "the latest on X" (topic)
    'screen_question',  # "what is this", "explain this error"
    'set_timer',        # "set a timer for 10 minutes"
    'take_note', 'list_notes', 'read_clipboard', 'ocr',
    'calculate',        # "25 times 4" (the brain guessed get_time from "times")
    'remember', 'recall',  # "remember that ...", "what is my ..." (falls through if nothing is stored)
}
def _is_precise_rule(kw_intent, command: str) -> bool:
    if kw_intent in PRECISE_RULE_INTENTS:
        return True
    # Tab commands only: other screen_control words ("copy", "type") also
    # appear in ordinary questions ("how do I copy a file in linux").
    if kw_intent == 'screen_control':
        from jarvis.core.screen_control import is_tab_command
        return is_tab_command(command)
    return False
FEATURE_TOGGLE_RE = re.compile(
    r"^(?:please\s+)?(?:enable|disable|turn\s+on|turn\s+off|start|stop|switch\s+on|switch\s+off)\s+"
    r"(?:the\s+)?(?:gestures?|gesture\s+control|face(?:\s+recognition)?|emotion(?:\s+detection)?|mood\s+detection)\b")
def _gesture_mp_available() -> bool:
    """Is MediaPipe installed? (checks the package, doesn't import it)"""
    try:
        from jarvis.core.gesture_controller import MP_AVAILABLE
        return MP_AVAILABLE
    except Exception:
        return False
RESUME_PHRASES = ('back online', 'come back', 'i need you', 'unmute', 'talk to me')
STORY_PHRASES = ('bedtime story', 'bed time story', 'tell me a story',
                 'tell a story', 'once upon', 'tell me a tale')
ROUTER_ERROR_PHRASES = ('trouble connecting', 'knowledge base', 'currently offline',
                        'encountered an issue', 'Set GROQ_API_KEY')
NEWS_CATEGORIES = ('economics', 'economy', 'business', 'politics', 'technology',
                   'tech', 'sports', 'entertainment', 'world', 'global')
DIRECT_APPS = {
    'calculator': 'calc', 'calc': 'calc',
    'notepad': 'notepad', 'paint': 'mspaint',
    'cmd': 'cmd', 'terminal': 'wt',
    'powershell': 'powershell',
    'file explorer': 'explorer', 'explorer': 'explorer',
    'file manager': 'explorer', 'files': 'explorer',
    'this pc': 'explorer', 'my computer': 'explorer',
    'settings': 'ms-settings:', 'task manager': 'taskmgr',
    'control panel': 'control',
    'device manager': 'devmgmt.msc',
    'snipping tool': 'SnippingTool',
    'wifi': 'ms-settings:network-wifi',
    'wifi settings': 'ms-settings:network-wifi',
    'bluetooth': 'ms-settings:bluetooth',
    'bluetooth settings': 'ms-settings:bluetooth',
    'display settings': 'ms-settings:display',
    'sound settings': 'ms-settings:sound',
    'apps': 'ms-settings:appsfeatures',
    'installed apps': 'ms-settings:appsfeatures',
    'photos': 'ms-photos:',
    'camera': 'microsoft.windows.camera:',
    'store': 'ms-windows-store:',
    'microsoft store': 'ms-windows-store:',
    'chrome': 'chrome', 'firefox': 'firefox',
    'edge': 'msedge', 'microsoft edge': 'msedge', 'brave': 'brave',
    'vscode': 'code', 'vs code': 'code',
    'spotify': 'spotify:', 'discord': 'discord:',
    'telegram': 'telegram:', 'whatsapp': 'whatsapp:',
    'whatsapp beta': 'whatsapp:',
}
WEB_APPS = {
    'chatgpt': 'https://chat.openai.com',
    'perplexity': 'https://perplexity.ai',
    'youtube': 'https://youtube.com',
    'gmail': 'https://mail.google.com',
    'google': 'https://google.com',
    'claude': 'https://claude.ai',
    'github': 'https://github.com',
}
HUD_COMMANDS = (
    'screenshot', 'capture screen',
    'read screen', 'read text', 'extract text', 'ocr',
    'read clipboard',
    'define ', 'meaning of ', 'definition of ',
    'synonym',
    'register my face', 'register face', 'register owner',
    'verify me', 'authenticate', 'who am i',
    'enable gesture', 'start gesture', 'gesture on',
    'disable gesture', 'stop gesture', 'gesture off',
    'enable emotion', 'mood detection', 'disable emotion',
    'tell me a story', 'tell a story',
    'recite a poem', 'poem',
    'riddle',
    'create note', 'new note', 'add note',
    'list notes', 'show notes', 'my notes',
    'set alarm',
    'list alarm', 'show alarm', 'my alarm',
    'switch to friday', 'activate friday',
    'switch to jarvis', 'activate jarvis',
)
