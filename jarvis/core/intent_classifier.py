"""
JARVIS Intent Classifier
Simple keyword-based intent classification
With multi-command support and context-aware disambiguation
"""

import logging
_log = logging.getLogger(__name__)

# Returned by an extracted step that didn't handle the request: the
# caller carries on with its next step.
_NEXT = object()

from typing import Tuple, Dict, Any, List, Optional
from dataclasses import dataclass, field
import re
from functools import lru_cache


# ═══════════════════════════════════════════════════════════════
# WHOLE-WORD MATCHING
# The classifier used plain substring checks ('story' in cmd), so "explain
# the history of Rome" became a children's story, "they said" a greeting
# ('hey'), "sometimes" the time, "update" the date, and "context " a WhatsApp
# message ('text '). has() matches whole words/phrases, allowing a plural
# ("reminders", "thanks", "headlines").
# ═══════════════════════════════════════════════════════════════

@lru_cache(maxsize=None)
def _phrase_re(phrase: str):
    return re.compile(r"(?<![a-z0-9])" + re.escape(phrase.strip()) + r"(?:s|es)?(?![a-z0-9])")


def has(cmd: str, *phrases: str) -> bool:
    """True if any phrase occurs in cmd as whole words (plural allowed)."""
    return any(_phrase_re(p).search(cmd) for p in phrases if p.strip())


_DURATION_RE = re.compile(r"(\d+)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?)\b")
_UNIT_NAMES = {"sec": "seconds", "min": "minutes", "hou": "hours", "hr": "hours"}


def parse_duration(text: str):
    """'set a timer for 90 seconds' -> (90, 'seconds'); None if no duration."""
    m = _DURATION_RE.search((text or "").lower())
    if not m:
        return None
    unit = next(v for k, v in _UNIT_NAMES.items() if m.group(2).startswith(k))
    return int(m.group(1)), unit


# "the latest on diabetes", "news about the election", "what's happening with nvidia"
_TOPIC_NEWS_RE = re.compile(
    r"^(?:"
    # "(tell me) (the) latest news about X", "any updates on X"
    r"(?:(?:can you\s+)?(?:please\s+)?(?:tell me|give me|show me|get me|find|search for|search)\s+)?"
    r"(?:any\s+)?(?:the\s+)?(?:latest\s+|recent\s+|current\s+)?"
    r"(?:news|headlines|updates?|developments)\s+(?:about|on|regarding|related to|for|around)\s+(?P<a>.+?)"
    # "search news (about) X"
    r"|(?:search|find)\s+(?:the\s+)?news\s+(?:about\s+|on\s+|for\s+)?(?P<b>.+?)"
    # "what's the latest on X", "what is happening with X"
    r"|what(?:'s|s| is)?\s+(?:the\s+)?(?:latest|new|happening)\s+(?:on|with|in|about)\s+(?P<c>.+?)"
    r")\s*(?:today|now|please|right now)?[?.!]*$"
)


_GREETING_RE = re.compile(
    r"^(?:(?:hello|hi|hey|hiya|yo|greetings|good\s+(?:morning|afternoon|evening|day))[\s,!.]*)+"
    r"(?:(?:there|jarvis|friday|buddy|mate|sir|again)[\s,!.]*)*$")

_MSG_SPLIT_RE = re.compile(
    r"^(?P<contact>.+?)\s+(?:saying|that says|and say|and tell (?:him|her|them)|telling (?:him|her|them)|"
    r"with (?:the )?message|message|that)\s+(?P<message>.+)$")


def parse_message_command(cmd: str):
    """'send whatsapp message to mom saying hi' -> ('mom', 'hi').

    The old pattern returned the contact 'message to mom'.
    Returns (contact or None, message or None).
    """
    c = (cmd or "").lower().strip()
    c = re.sub(r"^(?:please\s+)?(?:open\s+whatsapp\s+and\s+)?", "", c)
    c = re.sub(r"^(?:send\s+)?(?:an?\s+)?(?:whatsapp|text|message|msg)(?:\s+(?:message|msg|text))?\s*", "", c)
    c = re.sub(r"^(?:on\s+whatsapp\s+)?to\s+", "", c)
    m = _MSG_SPLIT_RE.match(c)
    contact, message = (m.group("contact"), m.group("message")) if m else (c, None)
    if contact and ":" in contact and not message:
        contact, message = (p.strip() for p in contact.split(":", 1))
    contact = re.sub(r"\s+(?:on|via|over)\s+whatsapp$", "", (contact or "").strip()).strip()
    contact = re.sub(r"^(?:to|my)\s+", "", contact).strip()
    return (contact or None), (message.strip() if message else None)


def news_topic(cmd: str):
    """The topic of a topical news request, or None ("news about diabetes" -> "diabetes")."""
    m = _TOPIC_NEWS_RE.match(cmd.strip())
    if not m:
        return None
    topic = next(g for g in m.groups() if g)
    topic = re.sub(r"^(?:the|a|an)\s+", "", topic.strip())
    return topic or None


@dataclass
class ClassificationContext:
    """
    Structured context for intent classification.
    Enables vague commands like "next" or "play it" to resolve correctly.
    
    Example: "next" with active_app="spotify" -> "next_track"
             "next" with active_app="pdf" -> "next_page"
    """
    active_app: Optional[str] = None        # Currently focused app
    last_intent: Optional[str] = None       # Previous intent
    last_entities: Dict[str, Any] = field(default_factory=dict)
    last_action: Optional[str] = None       # What was just done
    user_mood: str = "neutral"              # Current user emotion
    conversation_topic: Optional[str] = None # What we're discussing


# Context-aware vague command mappings
CONTEXT_COMMANDS = {
    # Music app context
    "spotify": {
        "next": "next_track",
        "previous": "previous_track", 
        "back": "previous_track",
        "stop": "pause_music",
        "pause": "pause_music",
        "resume": "play_music",
        "play": "play_music",
    },
    "music": {
        "next": "next_track",
        "previous": "previous_track",
        "back": "previous_track",
        "stop": "pause_music",
        "pause": "pause_music",
        "play": "play_music",
    },
    # PDF context
    "pdf": {
        "next": "next_page",
        "previous": "previous_page",
        "back": "previous_page",
        "close": "close_pdf",
    },
    # Browser context
    "browser": {
        "next": "browser_forward",
        "back": "browser_back",
        "close": "close_tab",
        "new": "new_tab",
    },
    # Video context
    "youtube": {
        "next": "next_video",
        "skip": "skip_ad",
        "pause": "pause_video",
        "play": "play_video",
    },
}


def split_commands(command: str) -> List[str]:
    """
    Split a multi-part command into individual commands.
    Handles: "open brave and search youtube" -> ["open brave", "search youtube"]
    
    Preserves search/query content by checking context.
    """
    cmd = command.strip()
    
    # Don't split if it's a search/query command (the 'and' is part of the query)
    search_indicators = ['search for', 'google', 'look up', 'find', 'what is', 'who is']
    if any(indicator in cmd.lower() for indicator in search_indicators):
        # Only split before the search term
        for indicator in search_indicators:
            if indicator in cmd.lower():
                idx = cmd.lower().find(indicator)
                if idx > 0:
                    # Check if there's an "and" before the search
                    before = cmd[:idx].strip()
                    if before.endswith(' and'):
                        before = before[:-4].strip()
                        after = cmd[idx:].strip()
                        return [before, after] if before else [after]
                break
        return [cmd]
    
    # Split on common conjunctions
    # Order matters - check longer patterns first
    split_patterns = [
        r'\s+and\s+then\s+',  # "and then"
        r'\s+then\s+',        # "then"
        r'\s+after\s+that\s+', # "after that"
    ]
    
    for pattern in split_patterns:
        parts = re.split(pattern, cmd, flags=re.IGNORECASE)
        if len(parts) > 1:
            return [p.strip() for p in parts if p.strip()]
    
    # Split on " and " but be careful with app names
    # Don't split "bread and butter" type phrases
    if ' and ' in cmd.lower():
        parts = cmd.split(' and ', 1)
        # Only split if first part looks like a command
        first_words = ['open', 'close', 'start', 'stop', 'play', 'pause', 'set', 'show', 'tell', 'get']
        if any(parts[0].lower().strip().startswith(w) for w in first_words):
            return [p.strip() for p in parts if p.strip()]
    
    return [cmd]


def classify_intent(command: str, context: ClassificationContext = None) -> Tuple[str, Dict[str, Any]]:
    """
    Classify a command into an intent + extracted entities.
    
    Args:
        command: The user's command text
        context: Optional ClassificationContext for resolving vague commands
    
    Returns:
        Tuple of (intent_name: str, entities: dict)
    """
    cmd = command.lower().strip()
    entities = {}

    first = _rule_calculation_or_screen(cmd)
    if first is not _NEXT:
        return first

    # ── Commands that had no rule and fell through to the AI chat (v2.7) ──
    # Translation: answered by the conversation/LLM handler. "translate hello
    # to spanish" used to be treated as a greeting because of "hello".
    if re.match(r"^(?:please\s+)?translate\b", cmd) or re.search(r"\bhow do (?:you|i) say\b", cmd):
        return 'conversation', {}
    # Clipboard: the router reads it directly (it used to be answered by the AI)
    if re.search(r"\b(?:read|show|what'?s|what is)\b.*\bclipboard\b", cmd) or cmd == 'clipboard':
        return 'read_clipboard', {}
    # Screen reading -> OCR handler ("screenshot" doesn't match: no word boundary)
    if re.search(r"\b(?:read|what(?:'s| does| is))\b.*\bscreen\b", cmd):
        return 'ocr', {}
    # Notes: saved with SmartNotes (they used to go to the AI chat and were lost)
    note = (re.match(r"^(?:please\s+)?(?:take|make|add|write)\s+(?:a\s+)?note"
                     r"(?:\s+(?:that|to|saying))?\s*:?\s*(.*)$", cmd)
            or re.match(r"^(?:note that|note down|write down)\s+(.*)$", cmd))
    if note:
        return 'take_note', {'content': note.group(1).strip()}
    if re.search(r"\b(?:show|list|read)\s+(?:me\s+)?(?:all\s+)?(?:my\s+)?notes\b|\bwhat are my notes\b", cmd):
        return 'list_notes', {}
    
    # ═══════════════════════════════════════════════════════════
    # CONTEXT-AWARE RESOLUTION (check first for vague commands)
    # ═══════════════════════════════════════════════════════════
    if context and context.active_app:
        app = context.active_app.lower()
        # Check if this is a vague command that needs context
        for ctx_app, mappings in CONTEXT_COMMANDS.items():
            if ctx_app in app:
                for vague_cmd, intent in mappings.items():
                    if cmd == vague_cmd or cmd.startswith(f"{vague_cmd} "):
                        # Found context-aware match!
                        return intent, entities
    
    # ═══════════════════════════════════════════════════════════
    # KEYWORD OVERRIDES (common commands that should always work)
    # ═══════════════════════════════════════════════════════════
    # These override even without context
    keyword_overrides = {
        "resume": "play_music",
        "continue playing": "play_music",
        "resume music": "play_music",
        "resume playback": "play_music",
    }
    
    for keyword, intent in keyword_overrides.items():
        if keyword in cmd:
            return intent, entities
    
    # Browser tabs, before "close X" / "switch to X" / "go to X", which sent
    # "switch to the next tab" to the app opener (app "the next tab") and
    # "close this tab" to close_app (process "this tab").
    from jarvis.core.screen_control import is_tab_command
    if is_tab_command(cmd):
        return 'screen_control', {'raw_text': command}

    # Timers: "set a timer for 10 minutes" (had no keyword rule at all)
    if has(cmd, 'timer') and not has(cmd, 'cancel', 'stop', 'delete', 'remove', 'how long', 'left'):
        d = parse_duration(cmd)
        return 'set_timer', ({'duration': d[0], 'unit': d[1]} if d else {})

    # Handle "close X" pattern explicitly
    if cmd.startswith("close ") or cmd == "close":
        app_name = cmd.replace("close ", "").strip() if cmd.startswith("close ") else None
        return "close_app", {"app": app_name} if app_name else {}
    
    _r = _rule_voice_switching(cmd)
    if _r is not _NEXT:
        return _r
    
    # ═══════════════════════════════════════════════════════════
    # IDENTITY
    # ═══════════════════════════════════════════════════════════
    if has(cmd, 'who are you') or has(cmd, 'your name'):
        return 'identity', {}
    
    if has(cmd, *['who made you', 'who created you', 'your creator', 'who built you']):
        return 'creator', {}
    
    # ═══════════════════════════════════════════════════════════
    # TIME & DATE
    # ═══════════════════════════════════════════════════════════
    if has(cmd, 'time') and not has(cmd, 'timer'):
        return 'time', {}
    
    if has(cmd, 'date') or (has(cmd, 'what') and has(cmd, 'day')):
        return 'date', {}
    
    _r = _rule_system_status(cmd, entities)
    if _r is not _NEXT:
        return _r
    
    # ═══════════════════════════════════════════════════════════
    # NEWS (Enhanced with Hacker News)
    # ═══════════════════════════════════════════════════════════
    # News about a topic: "news about diabetes", "what's the latest on nvidia".
    # (The old keyword strip also deleted every "for"/"about" inside the topic.)
    topic = news_topic(cmd)
    if topic:
        return 'search_news', {'keyword': topic}

    if has(cmd, 'news') or has(cmd, 'headline') or has(cmd, 'hacker news'):
        # Detect category
        categories = {
            'economics': 'economics',
            'economy': 'economics',
            'business': 'business',
            'politics': 'politics',
            'political': 'politics',
            'tech': 'tech',  # Now maps to Hacker News
            'technology': 'technology',
            'sports': 'sports',
            'sport': 'sports',
            'entertainment': 'entertainment',
            'world': 'world',
            'global': 'world',
            # Hacker News categories
            'hacker': 'hacker',
            'hackernews': 'hackernews',
            'startups': 'startups',
            # "show me the headlines" used to pick Hacker News "Show HN"
            'ask hn': 'ask',
            'show hn': 'show',
        }
        for keyword, category in categories.items():
            if has(cmd, keyword):
                entities['category'] = category
                break
        return 'news', entities
    
    _r = _rule_entertainment(_r, cmd, entities)
    if _r is not _NEXT:
        return _r
    
    _r = _rule_screenshots_ocr(cmd)
    if _r is not _NEXT:
        return _r
    
    _r = _rule_dictionary(cmd, entities)
    if _r is not _NEXT:
        return _r
    
    _r = _rule_face_gesture(cmd)
    if _r is not _NEXT:
        return _r
    
    _r = _rule_notes_alarms(_r, cmd, command, entities)
    if _r is not _NEXT:
        return _r
    
    _r = _rule_screen_control(_r, cmd, command, entities)
    if _r is not _NEXT:
        return _r
    
    _r = _rule_music_control(_r, cmd, entities)
    if _r is not _NEXT:
        return _r
    
    _r = _rule_ai_search(_r, cmd, entities)
    if _r is not _NEXT:
        return _r
    
    # ═══════════════════════════════════════════════════════════
    # EMOTION DETECTION
    # ═══════════════════════════════════════════════════════════
    if has(cmd, 'enable emotion') or has(cmd, 'mood detection'):
        return 'enable_emotion', {}
    
    if has(cmd, 'disable emotion'):
        return 'disable_emotion', {}
    
    _r = _rule_features_status(_r, cmd)
    if _r is not _NEXT:
        return _r
    
    # ═══════════════════════════════════════════════════════════
    # P2-02: HABIT TRACKING
    # ═══════════════════════════════════════════════════════════
    if has(cmd, *['my habits', 'list habits', 'show habits', 'track habit',
                                         'add habit', 'create habit', 'habit check', 'habit status']):
        return 'habit', {}
    
    # ═══════════════════════════════════════════════════════════
    # P2-02: EMAIL
    # ═══════════════════════════════════════════════════════════
    if has(cmd, *['send email', 'check email', 'read email', 'compose email',
                                         'write email', 'inbox', 'new email']):
        return 'email', {}
    
    # ═══════════════════════════════════════════════════════════
    # P2-02: CALENDAR
    # ═══════════════════════════════════════════════════════════
    if has(cmd, *['calendar', 'events today', 'my schedule', 'today\'s schedule',
                                         'upcoming events', 'what\'s on my calendar']):
        return 'calendar', {}
    
    # ═══════════════════════════════════════════════════════════
    # FALLBACK TO CONVERSATION (AI will handle it)
    # ═══════════════════════════════════════════════════════════
    return 'conversation', {}

def _rule_voice_switching(cmd):
    """Step of classify_intent(): voice switching."""
    # ═══════════════════════════════════════════════════════════
    # VOICE SWITCHING (highest priority)
    # ═══════════════════════════════════════════════════════════
    if has(cmd, 'switch to friday') or has(cmd, 'activate friday'):
        return 'switch_to_friday', {}
    if has(cmd, 'switch to jarvis') or has(cmd, 'activate jarvis'):
        return 'switch_to_jarvis', {}

    
    _r = _rule_greetings(cmd)
    if _r is not _NEXT:
        return _r
    return _NEXT

def _rule_features_status(_r, cmd):
    """Step of classify_intent(): FEATURES STATUS."""
    # ═══════════════════════════════════════════════════════════
    # FEATURES STATUS
    # ═══════════════════════════════════════════════════════════
    if has(cmd, 'features') or (has(cmd, 'status') and not has(cmd, 'system')):
        return 'features', {}
    
    _r = _rule_gesture_face_help(cmd)
    if _r is not _NEXT:
        return _r
    return _NEXT


def _rule_greetings(cmd):
    """Step of classify_intent(): greetings."""
    # ═══════════════════════════════════════════════════════════
    # GREETINGS & SOCIAL
    # ═══════════════════════════════════════════════════════════
    # Only when the whole command is a greeting. "text priya saying hello" and
    # "hello jarvis, what's the weather" contain one but aren't greetings.
    if _GREETING_RE.match(cmd):
        return 'greeting', {}
    
    if has(cmd, *['bye', 'goodbye', 'see you', 'goodnight']):
        return 'farewell', {}
    
    if has(cmd, 'thank'):
        return 'thanks', {}
    
    if has(cmd, 'how are you'):
        return 'how_are_you', {}
    return _NEXT

def _rule_system_status(cmd, entities):
    """Step of classify_intent(): SYSTEM & STATUS."""
    # ═══════════════════════════════════════════════════════════
    # SYSTEM & STATUS
    # ═══════════════════════════════════════════════════════════
    if has(cmd, 'system status') or has(cmd, 'system report'):
        return 'system_status', {}
    
    if cmd == 'help' or has(cmd, 'what can you do') or has(cmd, 'capabilities'):
        return 'help', {}
    
    _r = _rule_weather(cmd, entities)
    if _r is not _NEXT:
        return _r
    return _NEXT

def _rule_entertainment(_r, cmd, entities):
    """Step of classify_intent(): ENTERTAINMENT."""
    # ═══════════════════════════════════════════════════════════
    # ENTERTAINMENT
    # ═══════════════════════════════════════════════════════════
    if has(cmd, 'joke'):
        return 'joke', {}
    
    # IMPORTANT: Check 'chat history' BEFORE 'story' to avoid 'history' matching 'story'
    if has(cmd, 'chat history') or has(cmd, 'conversation history') or has(cmd, 'show history'):
        return 'chat_history', {}
    
    _r = _rule_story(cmd, entities)
    if _r is not _NEXT:
        return _r
    
    if has(cmd, 'poem') or has(cmd, 'recite'):
        return 'poem', {}
    
    if has(cmd, 'riddle'):
        return 'riddle', {}
    return _NEXT

def _rule_screenshots_ocr(cmd):
    """Step of classify_intent(): SCREENSHOTS & OCR."""
    # ═══════════════════════════════════════════════════════════
    # SCREENSHOTS & OCR
    # ═══════════════════════════════════════════════════════════
    if has(cmd, 'screenshot') or has(cmd, 'screen shot') or has(cmd, 'capture screen'):
        return 'screenshot', {}
    
    if has(cmd, *['read screen', 'read text', 'extract text', 'ocr',
                                         'what is on my screen', 'what\'s on my screen',
                                         'read my screen', 'screen text']):
        return 'ocr', {}
    
    if has(cmd, 'read clipboard'):
        return 'read_clipboard', {}
    return _NEXT

def _rule_dictionary(cmd, entities):
    """Step of classify_intent(): DICTIONARY."""
    # ═══════════════════════════════════════════════════════════
    # DICTIONARY
    # ═══════════════════════════════════════════════════════════
    if has(cmd, 'define ') or has(cmd, 'meaning of ') or has(cmd, 'definition of '):
        word = cmd.replace('define ', '').replace('meaning of ', '').replace('definition of ', '').strip()
        entities['word'] = word
        return 'dictionary', entities
    
    if has(cmd, 'synonym'):
        word = cmd.replace('synonym for ', '').replace('synonym of ', '').replace('synonyms of ', '').replace('synonym', '').strip()
        entities['word'] = word
        return 'synonym', entities
    return _NEXT

def _rule_face_gesture(cmd):
    """Step of classify_intent(): FACE & GESTURE."""
    # ═══════════════════════════════════════════════════════════
    # FACE & GESTURE
    # ═══════════════════════════════════════════════════════════
    if has(cmd, *['register my face', 'register face', 'register owner']):
        return 'register_face', {}
    
    if has(cmd, *['verify me', 'authenticate', 'who am i']):
        return 'verify_face', {}
    
    if has(cmd, *['enable gesture', 'start gesture', 'gesture on']):
        return 'enable_gesture', {}
    
    if has(cmd, *['disable gesture', 'stop gesture', 'gesture off']):
        return 'disable_gesture', {}
    return _NEXT

def _rule_notes_alarms(_r, cmd, command, entities):
    """Step of classify_intent(): NOTES & ALARMS."""
    # ═══════════════════════════════════════════════════════════
    # NOTES & ALARMS
    # ═══════════════════════════════════════════════════════════
    if has(cmd, *['create note', 'new note', 'add note']):
        content = cmd.replace('create note', '').replace('new note', '').replace('add note', '').strip()
        entities['content'] = content
        return 'create_note', entities
    
    if has(cmd, *['list notes', 'show notes', 'my notes']):
        return 'list_notes', {}
    
    _r = _rule_set_alarm(cmd, entities)
    if _r is not _NEXT:
        return _r
    
    if has(cmd, *['list alarm', 'show alarm', 'my alarm']):
        return 'list_alarms', {}
    
    _r = _rule_reminders(cmd, command, entities)
    if _r is not _NEXT:
        return _r
    
    
    _r = _rule_volume_brightness(cmd, entities)
    if _r is not _NEXT:
        return _r
    
    # Standalone "mute" without "volume" keyword
    if cmd in ('mute', 'unmute') or has(cmd, 'mute the') or has(cmd, 'mute audio') or has(cmd, 'mute sound'):
        return 'volume', {'action': 'mute'}
    
    _r = _rule_brightness(cmd, entities)
    if _r is not _NEXT:
        return _r
    return _NEXT

def _rule_screen_control(_r, cmd, command, entities):
    """Step of classify_intent(): SCREEN CONTROL."""
    # ═══════════════════════════════════════════════════════════
    # SCREEN CONTROL
    # ═══════════════════════════════════════════════════════════
    screen_control_triggers = [
        'click', 'double click', 'right click', 
        'scroll up', 'scroll down',
        'move mouse', 'move cursor',
        'type ', 'press enter', 'press escape', 'press tab',
        'copy', 'paste', 'undo', 'redo', 'select all',
        'switch window', 'alt tab', 'close window', 'close tab',
        'new tab', 'new window', 'create tab', 'create new tab',
    ]
    # Only as an instruction ("copy that", "please scroll down"), never as a
    # word inside a question: "how do I copy a file in linux" pressed Ctrl+C.
    lead = re.sub(r"^(?:(?:please|can you|could you|now|jarvis|hey jarvis|ok)\s*,?\s+)+", "", cmd)
    if any(lead == t.strip() or lead.startswith(t.strip() + " ") for t in screen_control_triggers):
        entities['raw_text'] = command  # Pass original for parsing
        return 'screen_control', entities
    
    _r = _rule_whatsapp(cmd, entities)
    if _r is not _NEXT:
        return _r

    _r = _rule_apps_search(cmd, entities)
    if _r is not _NEXT:
        return _r
    
    # "switch to X" / "go to X" (app switching)
    if cmd.startswith('switch to ') or cmd.startswith('go to '):
        app = cmd.replace('switch to ', '').replace('go to ', '').strip()
        if app and app not in ('friday', 'jarvis'):  # Don't override voice switching
            entities['app'] = app
            return 'open_app', entities
    return _NEXT

def _rule_music_control(_r, cmd, entities):
    """Step of classify_intent(): music control."""
    # ═══════════════════════════════════════════════════════════
    # MUSIC CONTROL - Direct responses
    # ═══════════════════════════════════════════════════════════
    # Pause/Stop
    if has(cmd, *['pause music', 'pause', 'stop music', 'stop playing']):
        return 'pause_music', {}
    
    # Next track
    if has(cmd, *['next song', 'next track', 'skip song', 'skip track', 'skip']):
        return 'next_track', {}
    
    # Previous track
    if has(cmd, *['previous song', 'previous track', 'go back', 'last song']):
        return 'previous_track', {}
    
    # Play (must be after pause/next/prev checks)
    if has(cmd, *['play music', 'play songs', 'play some music', 'spotify']):
        return 'play_music', {}
    
    _r = _rule_play_song(cmd, entities)
    if _r is not _NEXT:
        return _r
    return _NEXT

def _rule_ai_search(_r, cmd, entities):
    """Step of classify_intent(): ai search."""
    # ═══════════════════════════════════════════════════════════
    # AI SEARCH (Perplexica/Scira-inspired)
    # ═══════════════════════════════════════════════════════════
    # Deep research mode
    if has(cmd, *['research ', 'deep search', 'investigate']):
        query = cmd.replace('research ', '').replace('deep search', '').replace('investigate', '').strip()
        entities['query'] = query
        entities['mode'] = 'quality'
        return 'ai_search', entities
    
    _r = _rule_recall_memory(cmd, entities)
    if _r is not _NEXT:
        return _r
    
    if has(cmd, *['remember that', 'remember this', 'save this',
                                         'remember my', 'remember i', 'remember the']):
        fact = re.sub(r'(remember that|remember this|save this|remember my|remember i|remember the|remember)\s*', '', cmd).strip()
        entities['fact'] = fact
        return 'remember', entities
    
    # Reddit search
    if has(cmd, 'reddit') and has(cmd, 'search'):
        query = cmd.replace('reddit', '').replace('search', '').strip()
        entities['query'] = query
        entities['source'] = 'reddit'
        return 'ai_search', entities
    
    # Regular search (enhanced)
    if has(cmd, 'search') or has(cmd, 'google'):
        query = cmd.replace('search for', '').replace('search', '').replace('google', '').strip()
        entities['query'] = query
        return 'search', entities
    return _NEXT

def _rule_gesture_face_help(cmd):
    """Step of classify_intent(): gesture face help."""
    # ═══════════════════════════════════════════════════════════
    # GESTURE & FACE HELP (so JARVIS tells user how to use these)
    # ═══════════════════════════════════════════════════════════
    if has(cmd, *['hand gesture', 'use gestures', 'gesture control', 'can i use gesture']):
        return 'gesture_help', {}
    
    if has(cmd, *['recognize my face', 'face recognition', 'who am i', 'identify me']):
        return 'face_recognition', {}
    
    if has(cmd, *['improve you', 'where should i improve', 'what needs improvement', 'improve jarvis']):
        return 'improvement_suggestions', {}
    return _NEXT


def _rule_weather(cmd, entities):
    """Step of classify_intent(): WEATHER."""
    # ═══════════════════════════════════════════════════════════
    # WEATHER
    # ═══════════════════════════════════════════════════════════
    if has(cmd, 'weather'):
        # Try to extract city
        city_patterns = [
            r"weather (?:like )?(?:in|for|at) ([a-z][a-z .'-]*?)(?:\s+(?:today|now|tomorrow|right now|please))?[?.!]*$",
            r'(\w+) weather'
        ]
        for pattern in city_patterns:
            match = re.search(pattern, cmd)
            if match:
                city = match.group(1)
                if city not in ['the', 'today', 'now', 'current']:
                    entities['city'] = city
                    break
        return 'weather', entities
    return _NEXT

def _rule_story(cmd, entities):
    """Step of classify_intent(): Story."""
    if has(cmd, 'story'):
        # Extract genre
        if has(cmd, 'horror') or has(cmd, 'scary'):
            entities['genre'] = 'horror'
        elif has(cmd, 'funny') or has(cmd, 'comedy'):
            entities['genre'] = 'comedy'
        elif has(cmd, 'romance'):
            entities['genre'] = 'romance'
        elif has(cmd, 'bedtime'):
            entities['genre'] = 'bedtime'
        return 'story', entities
    return _NEXT

def _rule_set_alarm(cmd, entities):
    """Step of classify_intent(): set alarm."""
    if has(cmd, *['set alarm', 'alarm for', 'alarm in', 'set an alarm', 'wake me']):
        # Check for relative time first: "5 min from now", "in 10 minutes"
        relative_match = re.search(r'(\d+)\s*(min|minute|minutes|hour|hours|hr|hrs)', cmd)
        if relative_match:
            entities['relative_amount'] = int(relative_match.group(1))
            entities['relative_unit'] = relative_match.group(2)
            return 'set_alarm', entities
        
        # Absolute time: "7:30 am"
        time_match = re.search(r'(\d{1,2}):?(\d{2})?\s*(am|pm)?', cmd)
        if time_match:
            entities['hour'] = int(time_match.group(1))
            entities['minute'] = int(time_match.group(2) or 0)
            entities['period'] = time_match.group(3)
        return 'set_alarm', entities
    return _NEXT

def _rule_reminders(cmd, command, entities):
    """Step of classify_intent(): REMINDERS."""
    # ═══════════════════════════════════════════════════════════
    # REMINDERS
    # ═══════════════════════════════════════════════════════════
    if has(cmd, *['remind me', 'reminder', 'set reminder']):
        # Pass the full command, ReminderManager will parse the time + message
        entities['raw_command'] = command
        if has(cmd, *['list reminder', 'show reminder', 'my reminder']):
            return 'list_reminders', {}
        return 'set_reminder', entities
    return _NEXT

def _rule_volume_brightness(cmd, entities):
    """Step of classify_intent(): VOLUME & BRIGHTNESS."""
    # ═══════════════════════════════════════════════════════════
    # VOLUME & BRIGHTNESS
    # ═══════════════════════════════════════════════════════════
    if has(cmd, 'volume'):
        if has(cmd, 'up') or has(cmd, 'increase'):
            entities['action'] = 'up'
        elif has(cmd, 'down') or has(cmd, 'decrease'):
            entities['action'] = 'down'
        elif has(cmd, 'mute'):
            entities['action'] = 'mute'
        else:
            match = re.search(r'(\d+)\s*%?', cmd)
            if match:
                entities['level'] = int(match.group(1))
                entities['action'] = 'set'
        return 'volume', entities
    return _NEXT

def _rule_brightness(cmd, entities):
    """Step of classify_intent(): Brightness."""
    if has(cmd, 'brightness'):
        if has(cmd, 'up') or has(cmd, 'increase'):
            entities['action'] = 'up'
        elif has(cmd, 'down') or has(cmd, 'decrease'):
            entities['action'] = 'down'
        else:
            match = re.search(r'(\d+)\s*%?', cmd)
            if match:
                entities['level'] = int(match.group(1))
                entities['action'] = 'set'
        return 'brightness', entities
    return _NEXT

def _rule_whatsapp(cmd, entities):
    """Step of classify_intent(): whatsapp."""
    # ═══════════════════════════════════════════════════════════
    # WHATSAPP / COMMUNICATION
    # ═══════════════════════════════════════════════════════════
    # "open whatsapp and text hena saying hi"
    # "send whatsapp to john message what's up"
    if (has(cmd, 'whatsapp') or re.match(r"^(?:please\s+)?(?:send\s+(?:a\s+)?(?:message|msg|text)|message|text|msg)\s", cmd)):
        contact, message = parse_message_command(cmd)
        if contact:
            entities['contact'] = contact
        if message:
            entities['message'] = message
        return 'send_message', entities
    return _NEXT

def _rule_apps_search(cmd, entities):
    """Step of classify_intent(): APPS & SEARCH."""
    # ═══════════════════════════════════════════════════════════
    # APPS & SEARCH
    # ═══════════════════════════════════════════════════════════
    if cmd.startswith('open '):
        app = cmd.replace('open ', '').strip()
        
        # Special case: "open youtube search for X" → should search YouTube, not open app
        if 'youtube' in app and ('search' in app or 'find' in app or 'look' in app):
            # Extract the search query after youtube + search/find/look keywords
            query_match = re.sub(r'youtube\s*(and\s+)?(search|find|look)\s*(for|up)?\s*', '', app).strip()
            if query_match:
                # Don't open browser here — let the handler do it
                entities['query'] = query_match
                return 'youtube_search', entities
        
        entities['app'] = app
        return 'open_app', entities
    return _NEXT

def _rule_play_song(cmd, entities):
    """Step of classify_intent(): play song."""
    # Play specific song — but NOT if YouTube is the target
    if cmd.startswith('play '):
        song = cmd.replace('play ', '').strip()
        # "play X in youtube" / "play X on youtube" → YouTube search, NOT Spotify
        if has(cmd, *['in youtube', 'on youtube', 'youtube', 'in yt', 'on yt']):
            query = re.sub(r'\s*(in|on)\s*(youtube|yt)\s*$', '', song, flags=re.I).strip()
            entities['query'] = query
            return 'youtube_search', entities
        if len(song) > 2:
            entities['song'] = song
            return 'play_music', entities
    return _NEXT

def _rule_calculation_or_screen(cmd):
    """Step of classify_intent(): arithmetic and questions about the screen.

    "calculate 25 times 4" used to be the time ("times"). "What is this?",
    "explain this error" are answered from a screenshot (they used to reach the
    AI with no idea what "this" was)."""
    from jarvis.core.calculator import expression_from
    from jarvis.core.screen_vision import is_screen_question
    expr = expression_from(cmd)
    if expr:
        return 'calculate', {'expression': expr}
    if is_screen_question(cmd):
        return 'screen_question', {}
    m = re.search(r"\bsynonyms?\s+(?:for|of|to)\s+([\w-]+)", cmd)
    if m:   # "synonym for happy": the dictionary handler (it was a copy in the HUD fallback)
        return 'dictionary', {'word': m.group(1), 'mode': 'synonyms'}
    return _NEXT


def _rule_recall_memory(cmd, entities):
    """Step of classify_intent(): recall memory."""
    # Recall facts from memory — MUST be before 'remember' block
    # so "do you remember my X" goes to recall, not remember
    if has(cmd, *['recall ', 'what did i tell you about', 'do you remember',
                                         "what's my ", "whats my ", "what is my ", "do you know my"]):
        query = cmd
        for strip in ['recall ', 'what did i tell you about', 'do you remember',
                      "what's my ", "whats my ", "what is my ", "do you know my "]:
            query = query.replace(strip, '')
        entities['query'] = query.strip()
        return 'recall', entities
    return _NEXT



# Quick test
if __name__ == "__main__":
    test_commands = [
        "hello jarvis",
        "what's the time",
        "tell me a joke",
        "what's the weather in London",
        "tell me a horror story",
        "open chrome",
        "volume up",
        "set alarm for 7:30 am",
        "economics news",
        "who created you"
    ]
    
    for cmd in test_commands:
        intent, entities = classify_intent(cmd)
        _log.info(f"'{cmd}' -> {intent} {entities if entities else ''}")
