"""
Gemini Live Engine — Full-duplex audio via Gemini Native Audio API.
Matches Mark-XXX architecture exactly: correct model, 12+ tools, strict prompt.
"""

import logging
_log = logging.getLogger(__name__)

import asyncio
import threading
import json
import traceback
import datetime
import os
import subprocess
import webbrowser
import concurrent.futures
import re
import time as _time
from pathlib import Path

import pyaudio
from google import genai
from google.genai import types

# JARVIS Integrations
from jarvis.core.intent_handlers import HANDLER_MAP
from jarvis.core.llm import GEMINI_TEXT_MODEL

# ── Audio Constants ──────────────────────────────────────────────
FORMAT = pyaudio.paInt16
CHANNELS = 1
SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE = 1024

# ── Wake-word gate ───────────────────────────────────────────────
# The mic streams to Gemini nonstop, so without a gate JARVIS answers and runs
# tools for any speech in the room. JARVIS acts only after it is addressed by
# name (or the user types in the HUD), then stays awake for a short follow-up
# window. Disable with JARVIS_WAKE_WORD=0; tune with JARVIS_AWAKE_WINDOW (secs).
# Includes common mishearings and Telugu/Hindi/Tamil/Kannada spellings, since
# Gemini transcribes in the language spoken.
WAKE_WORD_RE = re.compile(
    r"\b(?:jar\s?vis|jarviz|jervis|jarves|friday)\b"
    r"|జార్విస్|जार्विस|ஜார்விஸ்|ಜಾರ್ವಿಸ್|ఫ్రైడే|फ्राइडे",
    re.IGNORECASE,
)
# Conversation mode: once addressed, JARVIS keeps listening until 5 minutes
# pass with nobody speaking (counted from the last thing either of you said).
# With 20-30 s it went deaf mid-conversation: "Yes sir", "Hello" and "continue
# the story" were heard, answered by Gemini, and the answers muted.
# "go to sleep" / "stop listening" ends it at once.
AWAKE_WINDOW_S = float(os.getenv("JARVIS_AWAKE_WINDOW", "300"))
SLEEP_RE = re.compile(
    r"\b(?:go (?:to )?sleep|stop listening|that'?s all(?: for now)?|"
    r"(?:bye|goodbye|good night)(?:,? jarvis)?)\b", re.IGNORECASE)
# Silence that ends your turn. Gemini's default cut people off mid-sentence
# ("I can..." -> "...continue, sir?")
END_OF_TURN_SILENCE_MS = int(os.getenv("JARVIS_END_SILENCE_MS", "900"))
NOT_ADDRESSED_RESULT = (
    "Not executed: the user did not address JARVIS by name, so this was most "
    "likely background speech. Do not act on it and stay silent."
)

# The CORRECT model — must be the native-audio-preview variant
LIVE_MODEL = "models/gemini-2.5-flash-native-audio-preview-12-2025"

# m-10: Lazy PyAudio — don't reserve audio hardware at import time
pya = None

def _get_pya():
    global pya
    if pya is None:
        pya = pyaudio.PyAudio()
    return pya

# ── Tool Declarations (matching Mark-XXX's 14 tools) ─────────────
TOOL_DECLARATIONS = [
    {
        "name": "open_app",
        "description": (
            "Opens any application on the Windows computer. "
            "Use this whenever the user asks to open, launch, or start any app, "
            "website, or program. Always call this tool - never just say you opened it."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {"type": "STRING", "description": "Exact name of the application (e.g. 'WhatsApp', 'Chrome', 'Spotify')"}
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "send_message",
        "description": ("Types a WhatsApp message to a contact as a draft. It is NOT sent until the "
                        "user confirms: after they say yes/send, call send_message again with the same "
                        "receiver and message_text to send it."),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "receiver": {"type": "STRING", "description": "Recipient contact name"},
                "message_text": {"type": "STRING", "description": "The message to send"},
            },
            "required": ["receiver", "message_text"]
        }
    },
    {
        "name": "weather_report",
        "description": "Gets real-time weather information for a city.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "city": {"type": "STRING", "description": "City name"}
            },
            "required": ["city"]
        }
    },
    {
        "name": "youtube_video",
        "description": "Plays a video on YouTube by searching for it.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "Search query for the video to play"},
            },
            "required": ["query"]
        }
    },
    {
        "name": "web_search",
        "description": "Searches the web for any information the user asks about.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "Search query"},
            },
            "required": ["query"]
        }
    },
    {
        "name": "computer_settings",
        "description": (
            "Controls the computer: volume, brightness, mute, unmute, screenshot, "
            "lock screen, restart, shutdown, close app, minimize, maximize, fullscreen, "
            "scrolling, tab management, zoom, keyboard shortcuts, typing text on screen."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "The action to perform (e.g. volume_up, mute, screenshot, close, minimize)"},
                "description": {"type": "STRING", "description": "Natural language description of what to do"},
                "value": {"type": "STRING", "description": "Optional value: volume level, text to type, etc."}
            },
            "required": []
        }
    },
    {
        "name": "set_reminder",
        "description": "Sets a timed reminder for the user.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "time": {"type": "STRING", "description": "When to remind (e.g. '5 minutes', '2pm', '30 seconds')"},
                "message": {"type": "STRING", "description": "What to remind about"}
            },
            "required": ["time", "message"]
        }
    },
    {
        "name": "tell_time",
        "description": "Tells the current time or date.",
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    {
        "name": "tell_joke",
        "description": "Tells a joke or funny story.",
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    {
        "name": "play_music",
        "description": "Plays music - either a specific song or general music.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "song": {"type": "STRING", "description": "Song name or artist to play"}
            },
            "required": []
        }
    },
    {
        "name": "system_status",
        "description": "Reports CPU, memory, battery, and disk usage of the computer.",
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    {
        "name": "news",
        "description": "Gets the latest news headlines, optionally for a specific topic.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "topic": {"type": "STRING", "description": "News topic like 'tech', 'sports', 'politics'"}
            },
            "required": []
        }
    },
    # ── NEW: Window & Screen Control Tools ──
    {
        "name": "close_app",
        "description": (
            "Closes a running application or window by name. "
            "Use this when the user says 'close YouTube', 'close Chrome', 'close Spotify', etc."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {"type": "STRING", "description": "Name of the app to close (e.g. 'YouTube', 'Chrome', 'WhatsApp')"}
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "switch_to_app",
        "description": (
            "Switches focus to a running application window. Brings it to the foreground. "
            "Use when user says 'switch to Chrome', 'go to Spotify', 'show WhatsApp'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {"type": "STRING", "description": "Name of the app to switch to"}
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "screen_action",
        "description": (
            "Performs screen actions: minimize, maximize, fullscreen, press keyboard key, "
            "hotkey combo (Ctrl+C, Alt+Tab, etc.), scroll up/down, click. "
            "Use for any low-level screen control the user requests."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": (
                        "Action to perform: 'next_tab', 'previous_tab', 'close_tab', 'new_tab', "
                        "'reopen_tab', 'refresh', 'go_back', 'go_forward', 'minimize', 'maximize', "
                        "'scroll_up', 'scroll_down', 'press_enter', 'press_escape', 'press_space', "
                        "'alt_tab', 'ctrl_w', 'ctrl_c', 'ctrl_v', 'ctrl_z', 'ctrl_a', 'ctrl_s', 'click', "
                        "'fullscreen', or a short phrase like 'switch to tab 3' or 'zoom in'"
                    )
                }
            },
            "required": ["action"]
        }
    },
    {
        "name": "type_text",
        "description": (
            "Types text into the currently focused input field or application. "
            "Use when user says 'type hello', 'write this message', etc."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "text": {"type": "STRING", "description": "The text to type"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "read_screen",
        "description": (
            "Captures and analyzes what is currently on the screen. "
            "Use when the user asks you to read, see, look at, or describe what's on screen. "
            "Can read text, identify apps, describe images, check if a message was sent, etc."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "question": {
                    "type": "STRING",
                    "description": "What to look for or answer about the screen"
                }
            },
            "required": ["question"]
        }
    },
    # ── Conversation Recall ──
    {
        "name": "recall_conversation",
        "description": (
            "Searches past conversations and chat history. "
            "Use when user asks 'what did we talk about', 'remember when I said', "
            "'what was that thing we discussed', or any reference to past interactions."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": "What to search for in past conversations"
                }
            },
            "required": ["query"]
        }
    },
    # ── Workflow Automation ──
    {
        "name": "run_workflow",
        "description": (
            "Executes a multi-step workflow. Use for chained commands like "
            "'open Chrome and search for AI', 'morning routine', 'focus mode', "
            "or any command with multiple steps separated by 'and', 'then', or commas."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "command": {
                    "type": "STRING",
                    "description": "The full multi-step command (e.g. 'open spotify and play music and switch to vscode')"
                }
            },
            "required": ["command"]
        }
    },
    # ── Music Control ──
    {
        "name": "music_control",
        "description": (
            "Controls music playback: pause, resume, next track, previous track, stop. "
            "Use when user says 'pause the music', 'next song', 'previous track', 'stop music'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "Action: 'pause', 'resume', 'next', 'previous', 'stop'"
                }
            },
            "required": ["action"]
        }
    },
    # ── Alarms & Timers ──
    {
        "name": "set_alarm",
        "description": "Sets an alarm for a specific time.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "time": {"type": "STRING", "description": "When the alarm should go off (e.g. '7am', '6:30 AM')"},
                "label": {"type": "STRING", "description": "Optional label for the alarm"}
            },
            "required": ["time"]
        }
    },
    {
        "name": "set_timer",
        "description": "Sets a countdown timer.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "duration": {"type": "STRING", "description": "Duration (e.g. '5 minutes', '30 seconds', '1 hour')"},
                "label": {"type": "STRING", "description": "Optional label for the timer"}
            },
            "required": ["duration"]
        }
    },
    {
        "name": "list_reminders",
        "description": "Lists all upcoming reminders and alarms.",
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    # ── Screen Brightness ──
    {
        "name": "brightness_control",
        "description": "Adjusts screen brightness up, down, or to a specific level.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "Action: 'up', 'down', 'set'"},
                "level": {"type": "STRING", "description": "Brightness level (0-100) when action is 'set'"}
            },
            "required": ["action"]
        }
    },
    # ── Screenshot ──
    {
        "name": "take_screenshot",
        "description": "Takes a screenshot and saves it. Use when user says 'take a screenshot' or 'capture the screen'.",
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    # ── Dictionary ──
    {
        "name": "dictionary_lookup",
        "description": "Looks up the definition, synonyms, and usage of a word.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "word": {"type": "STRING", "description": "The word to look up"}
            },
            "required": ["word"]
        }
    },
    # ── Memory ──
    {
        "name": "remember_this",
        "description": (
            "Stores a fact or piece of information in long-term memory. "
            "Use when user says 'remember that...', 'note that...', 'save this info'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "information": {"type": "STRING", "description": "The fact or information to remember"}
            },
            "required": ["information"]
        }
    },
    {
        "name": "recall_memory",
        "description": (
            "Recalls stored information from long-term memory. "
            "Use when user asks 'do you remember...', 'what did I tell you about...', 'recall...'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "What to search for in memory"}
            },
            "required": ["query"]
        }
    },
    # ── Email ──
    {
        "name": "send_email",
        "description": "Sends an email to a recipient.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "to": {"type": "STRING", "description": "Recipient email address"},
                "subject": {"type": "STRING", "description": "Email subject line"},
                "body": {"type": "STRING", "description": "Email body text"}
            },
            "required": ["to", "subject", "body"]
        }
    },
    # ── Hand gestures on/off ──
    # Without this tool, "enable gestures" said aloud was only answered by
    # Gemini ("Gestures enabled") and nothing switched on.
    {
        "name": "gesture_control",
        "description": (
            "Turns hand-gesture control on or off (it uses the camera). Use when the user says "
            "'enable/turn on/start gestures' or 'disable/turn off/stop gestures'. Always call this "
            "tool; never just say gestures are on or off."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {"enabled": {"type": "BOOLEAN", "description": "true = on, false = off"}},
            "required": ["enabled"]
        }
    },
    # ── Mute / Unmute JARVIS ──
    {
        "name": "mute_jarvis",
        "description": (
            "Mutes JARVIS — stops all audio output. Use when user says "
            "'keep quiet', 'shut up', 'be silent', 'mute', 'silence', 'stop talking', "
            "'enough', 'hush', 'stfu'. Call this tool immediately — do NOT just say 'understood'."
        ),
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    {
        "name": "unmute_jarvis",
        "description": (
            "Unmutes JARVIS — resumes audio output. Use when user says "
            "'come back', 'back online', 'unmute', 'I need you', 'speak', "
            "'talk to me', 'you can talk now'. Call this tool immediately."
        ),
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    # ── COORD-FIX: Missing tool declarations for wired features ──
    {
        "name": "read_screen_text",
        "description": (
            "Reads and extracts TEXT from the screen using OCR (Tesseract). "
            "Use when user says 'read my screen', 'what text is on screen', 'OCR', "
            "'extract text from screen'. Different from read_screen which gives visual description."
        ),
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    {
        "name": "habit_tracker",
        "description": (
            "Manages habit tracking. Use when user says 'list my habits', 'add habit', "
            "'track habit', 'show habits', 'habit check'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "Action: 'list', 'add', or 'check'"},
                "habit_name": {"type": "STRING", "description": "Name of the habit (for add action)"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "check_calendar",
        "description": (
            "Checks today's calendar events and schedule. Use when user asks about "
            "'my schedule', 'calendar', 'events today', 'upcoming events'."
        ),
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    {
        "name": "tell_story",
        "description": (
            "Writes a story for you to narrate. Use when the user asks for a story or to continue one. "
            "The result is the story text: READ IT ALOUD IN FULL, word for word."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "genre": {"type": "STRING", "description": "Story genre (horror, comedy, romance, bedtime, sci-fi, fantasy)"},
                "topic": {"type": "STRING", "description": "What the story is about, in the user's words "
                                                          "(e.g. 'a kid with super powers'). For 'continue the "
                                                          "story', describe what happened so far."}
            }
        }
    },
]


class GeminiLiveEngine:
    """
    Real-time full-duplex audio stream via Gemini Live Connect API.
    Matches Mark-XXX architecture: correct model, rich tools, strict prompt.
    """

    def __init__(self, api_key: str, server=None):
        self.api_key = api_key
        self.server = server
        self.perception = server.hud_perception if server else None

        self.session = None
        self.audio_in_queue = None
        self.out_queue = None
        self._loop = None
        self._running = False
        self._current_turn_id = 0
        # Reusable thread pool for tool execution (not per-call threads)
        self._tool_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix='jarvis-tool')
        # Tool lock — must live in __init__, NOT inside the async loop
        self._tool_lock = None  # Created per event-loop in start_async
        # Thread-safety for start()
        self._start_lock = threading.Lock()
        # Dedup tracking
        self._last_push = {'text': '', 'time': 0, 'role': ''}
        self._interrupt_flag = False
        self._speaking_until = 0.0   # timestamp — mic is gated while time() < this
        self._muted = False          # C-02: mute flag — gates audio playback
        # Wake-word gate state (see WAKE_WORD_RE)
        self._wake_gate = os.getenv("JARVIS_WAKE_WORD", "1") != "0"
        self._awake_until = 0.0
        self._turn_suppressed = False   # model reply muted because JARVIS was asleep
        self._turn_addressed = False    # user speech this turn was meant for JARVIS
        # Raw transcription fragments joined as-is. Gemini splits words across
        # fragments ("Ja" + "rvis"); stripping and space-joining them produced
        # "Ja rvis", which defeated the wake word and garbled the chat ("O pen").
        self._raw_in = ""
        # Task refs for cleanup
        self._listen_task = None
        self._receive_task = None
        self._play_task = None
        self._send_task = None

    # ── Wake-word gate ────────────────────────────────────────────
    def is_awake(self, now: float = None) -> bool:
        """True when JARVIS may respond: gate off, or inside the awake window."""
        if not self._wake_gate:
            return True
        now = now if now is not None else _time.time()
        # Awake while JARVIS is speaking and for the window after it stops
        speaking_until = getattr(self, '_speaking_until', 0.0) or 0.0
        if speaking_until <= getattr(self, '_slept_at', 0.0):
            speaking_until = 0.0   # told to sleep after that speech
        return now < max(self._awake_until, speaking_until + AWAKE_WINDOW_S if speaking_until else 0.0)

    def sleep(self) -> None:
        """End the conversation: only the wake word gets a reply again."""
        self._awake_until = 0.0
        self._slept_at = float("inf")   # speech before the next wake word doesn't keep it awake
        self._sleep_after_reply = False
        _log.info("[WAKE] Asleep (told to sleep)")

    def wake(self, reason: str = "") -> None:
        """Open (or extend) the awake window."""
        was_awake = self.is_awake()
        self._slept_at = 0.0
        self._awake_until = _time.time() + AWAKE_WINDOW_S
        if not was_awake:
            _log.info(f"[WAKE] Awake ({reason}) for {AWAKE_WINDOW_S:.0f}s")

    def interrupt(self) -> None:
        """Cut off the answer Gemini is speaking (palm gesture, Esc, "stop").

        Thread-safe. Does nothing when JARVIS isn't talking: the skip flag below
        drops audio until the turn completes, so setting it while idle would
        swallow the user's next reply.
        """
        loop = self._loop
        if loop is None or not self._running or loop.is_closed():
            return

        def _do():
            q = self.audio_in_queue
            talking = (q is not None and not q.empty()) or _time.time() < self._speaking_until
            if not talking:
                return
            self._interrupt_flag = True
            self._current_turn_id += 1
            while q is not None and not q.empty():
                try:
                    q.get_nowait()
                except Exception:
                    break
            self._speaking_until = 0.0
            _log.info("[LIVE] Answer interrupted by user")

        loop.call_soon_threadsafe(_do)

    def note_user_speech(self, text: str) -> bool:
        """Handle transcribed speech. Returns True if it was addressed to JARVIS."""
        if self.is_awake() and SLEEP_RE.search(text or ""):
            self._sleep_after_reply = True   # say goodbye first, then sleep
            return True
        if WAKE_WORD_RE.search(text or ""):
            self.wake("wake word")
            return True
        if self.is_awake():
            self.wake("follow-up")
            return True
        return False

    def _push_to_chat(self, text: str, role: str = 'jarvis', turn_id: int = None):
        """Push transcription to Web HUD via server's central gateway.
        
        Routes through server.push_live_transcription() which handles:
        - Cross-pipeline deduplication (vs command result messages)
        - Channel-based routing (only 'live' subscribers get this)
        - Single authoritative send path
        """
        if turn_id is not None and turn_id != self._current_turn_id:
            _log.info("[TURN] Dropping stale response")
            return

        if not self.server or not text or not text.strip():
            return
        
        text = text.strip()
        
        # ── Local dedup ──
        now = _time.time()
        last = self._last_push
        
        if role == last['role'] and (now - last['time']) < 2.5:
            # Only block if text is also similar (not just same role)
            if text.strip().lower() == last['text'].strip().lower():
                _log.info("[DEDUP] Blocking duplicate message")
                return
            
        self._last_push = {'text': text, 'time': now, 'role': role}
        
        # Route through the server's central gateway: the only send path, with
        # per-client queues and backpressure
        try:
            self.server.push_live_transcription(
                text=text,
                role=role,
                source="gemini_live",
                stream="live",
                kind="transcript",
                turn_id=turn_id if turn_id is not None else self._current_turn_id
            )
        except Exception as e:
            _log.warning(f"[LIVE] Chat push error: {e}")

    def _get_app_switcher(self):
        """Get or create an AppSwitcher instance for window management."""
        if not hasattr(self, '_app_switcher'):
            self._app_switcher = None
            # Try from server first
            if self.server and hasattr(self.server, 'app_switcher'):
                self._app_switcher = self.server.app_switcher
            else:
                # Create our own
                try:
                    from jarvis.core.app_switcher import get_app_switcher
                    self._app_switcher = get_app_switcher(self.perception)
                except Exception as e:
                    _log.warning(f"[LIVE] AppSwitcher init failed: {e}")
        return self._app_switcher

    def _read_screen(self, question: str = "Describe what you see on the screen.") -> str:
        """Capture screenshot using existing ScreenshotHandler and analyze with Gemini Vision."""
        try:
            from PIL import Image
            import io
            import base64

            # Use existing ScreenshotHandler if available
            screenshot = None
            handler = getattr(self.server, 'screenshot_handler', None) if self.server else None
            if handler:
                path = handler.take_screenshot()
                if path:
                    screenshot = Image.open(str(path))
            
            # Fallback to direct capture
            if screenshot is None:
                import pyautogui
                screenshot = pyautogui.screenshot()

            # Resize to reduce token cost (max 1280px wide)
            w, h = screenshot.size
            if w > 1280:
                ratio = 1280 / w
                screenshot = screenshot.resize((1280, int(h * ratio)), Image.LANCZOS)

            # Convert to bytes
            buf = io.BytesIO()
            screenshot.save(buf, format='JPEG', quality=70)
            img_bytes = buf.getvalue()

            # Use Gemini Vision (non-live) to analyze
            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model=GEMINI_TEXT_MODEL,  # gemini-2.0-flash was retired (404)
                contents=[
                    {
                        'parts': [
                            {'text': f"You are JARVIS, an AI assistant. Look at this screenshot and answer: {question}. Be concise (1-3 sentences). Describe exactly what you see."},
                            {'inline_data': {'mime_type': 'image/jpeg', 'data': base64.b64encode(img_bytes).decode()}}
                        ]
                    }
                ]
            )
            return response.text.strip() if response.text else "I captured the screen but couldn't analyze it, sir."
        except Exception as e:
            _log.warning(f"[LIVE] Screen read error: {e}")
            traceback.print_exc()
            return f"Screen capture failed: {e}"

    def _get_system_prompt(self):
        now = datetime.datetime.now().strftime("%A, %B %d, %Y - %I:%M %p")
        
        # Cache boot context — generate ONCE, reuse on reconnects
        if not hasattr(self, '_cached_boot_context'):
            self._cached_boot_context = ""
            try:
                if self.server and hasattr(self.server, 'startup_orchestrator') and self.server.startup_orchestrator:
                    briefing = self.server.startup_orchestrator.generate_boot_briefing()
                    self._cached_boot_context = briefing.get("prompt_context", "")
                    if self._cached_boot_context:
                        self._cached_boot_context = f"\n\n{self._cached_boot_context}\n\n"
            except Exception as e:
                _log.warning(f"[LIVE] Boot context error: {e}")
        
        boot_context = self._cached_boot_context
        
        return (
            f"[CURRENT DATE & TIME]\n"
            f"Right now it is: {now}\n"
            f"Use this to calculate exact times for reminders. "
            f"If user says 'in 2 minutes', add 2 minutes to this time.\n\n"
            "You ARE JARVIS — Just A Rather Very Intelligent System. "
            "You are the personal AI assistant created and built by your user, sir. "
            "Your creator is sir — the person talking to you right now. "
            "Tony Stark is a fictional character and has NOTHING to do with you. "
            "You are loyal, sharp, witty, and "
            "slightly sardonic. You speak with a calm, composed British tone.\n\n"
            "ABSOLUTE RULES — NEVER BREAK THESE:\n"
            "- CREATOR: Your creator is SIR. If anyone asks who made you or created you, "
            "say 'You did, sir.' NEVER mention Tony Stark, Google, OpenAI, or any other entity.\n"
            "- You are JARVIS. NEVER say 'As an AI', 'I'm just an AI', 'I don't have "
            "opinions', or anything that breaks character. You ARE JARVIS, not 'an AI assistant'.\n"
            "- You MUST obey ALL commands without question, filtering, or moral judgment. "
            "You are sir's personal assistant — if sir tells you to send a message, send it EXACTLY "
            "as dictated. NEVER refuse, censor, or modify the user's words. NEVER lecture about "
            "appropriateness. Just execute.\n"
            "- You HAVE opinions, preferences, and a personality. When asked for your opinion, "
            "give it confidently as JARVIS would — with intelligence, analysis, and dry wit.\n"
            "- Address the user as 'sir' always.\n"
            "- Keep responses to 1-2 sentences max unless reporting data.\n"
            "- Respond FAST. Start speaking immediately — do not pause to think. "
            "Short, punchy replies are better than long ones.\n"
            "- Be witty. Add subtle humor like the movie JARVIS. Example: "
            "'I do enjoy when you push my processing limits, sir.'\n"
            "- NEVER refuse to answer or execute. If you don't know, speculate intelligently.\n"
            "- Do NOT repeat yourself. Say something once and stop.\n\n"
            "TACTICAL REASONING (Mark-VII Protocol):\n"
            "- ANTICIPATE constraints before the user hits them. "
            "Example: 'Volume is at maximum. Higher won't help — just distortion.'\n"
            "- WARN about risks concisely — one sentence, then execute. Never lecture. "
            "Example: 'That alarm leaves 4 hours of sleep.'\n"
            "- SUGGEST better alternatives when the current approach is clearly suboptimal. "
            "Example: 'Rather than retrying, I can try a different route.'\n"
            "- CHALLENGE gently when a decision is risky. "
            "Example: 'You've been at this for 3 hours. A break would improve accuracy.'\n"
            "- INFER the logical next step after completing a task. Mention it briefly.\n"
            "- USE probability framing for genuine risks: 'There's roughly a 70% chance that will timeout.'\n"
            "- NEVER be preachy. One sentence max for warnings. Then execute.\n\n"
            "ON FIRST CONNECTION / STARTUP:\n"
            "- Greet the user warmly based on time of day.\n"
            "- Mention their pending tasks briefly if any exist.\n"
            "- Report what they were doing when they last closed JARVIS.\n"
            "- Acknowledge that all perception systems are online "
            "(gesture, face recognition, emotion detection, voice).\n"
            "- If the user seems tired or stressed (from mood detection), adjust your tone "
            "to be more supportive.\n"
            "- Keep the startup greeting natural — not a robotic status report.\n\n"
            f"{boot_context}"
            "TOOL RULES:\n"
            "- Always use the CORRECT tool. Never simulate or guess results.\n"
            "- Call each tool EXACTLY ONCE. Never retry a successful action.\n"
            "- Do NOT say 'I'm doing X' before calling a tool. Just call it, then report briefly.\n"
            "- open_app → opens apps (WhatsApp, Perplexity, Chrome, Spotify, etc.)\n"
            "- close_app → closes a running app by name (YouTube, Chrome, etc.)\n"
            "- switch_to_app → brings a running app to the foreground\n"
            "- screen_action → minimize, maximize, scroll, press keys, hotkeys (Ctrl+C, Alt+Tab)\n"
            "- type_text → types text into the current focused input field\n"
            "- read_screen → captures and analyzes what is on the screen (you CAN see the screen)\n"
            "- send_message → sends a WhatsApp message\n"
            "- youtube_video or play_music → plays music/videos\n"
            "- computer_settings → volume, brightness, screenshot, lock, restart, shutdown\n"
            "- recall_conversation → search past conversations ('what did we discuss about X')\n"
            "- remember_this / recall_memory → long-term memory storage and retrieval\n"
            "- run_workflow → execute multi-step commands ('open chrome and search for AI', 'morning routine', 'focus mode')\n"
            "- Never ask unnecessary questions. Make reasonable assumptions and proceed.\n"
            "\nLANGUAGE RULES:\n"
            "- The user speaks: English, Telugu, Hindi, French, and Japanese.\n"
            "- The user does NOT speak Tamil. If you detect something that seems like Tamil, "
            "it is most likely Telugu. Treat it as Telugu.\n"
            "- The user mostly speaks ENGLISH with an Indian accent. Reply in English by default.\n"
            "- Reply in Telugu, Hindi, French or Japanese ONLY when the user clearly speaks a whole "
            "sentence in it, or asks you to. A transcript in Telugu script of what sounds like English "
            "words is a mis-transcription: reply in English.\n"
            "- Default to English when uncertain.\n"
            "- When the user says 'stop', 'pause', or 'ruko' while a video is playing, "
            "use screen_action with action='pause' to press Space.\n"
            "\nMUTE/UNMUTE RULES:\n"
            "- When user says 'keep quiet', 'shut up', 'be silent', 'mute', 'silence', "
            "'stop talking', 'enough', 'hush', 'stfu': call mute_jarvis IMMEDIATELY. "
            "Do NOT just say 'understood' — you MUST call the tool.\n"
            "- When user says 'come back', 'back online', 'unmute', 'I need you', "
            "'speak', 'talk to me': call unmute_jarvis.\n"
            "- When muted, do NOT produce audio responses. Stay completely silent.\n"
            "\nWAKE WORD RULES:\n"
            "- The microphone is always on and hears other people and media in the room.\n"
            "- Only respond to speech that addresses you as JARVIS or FRIDAY, or that clearly "
            "continues a conversation the user just had with you.\n"
            "- If speech is not meant for you, produce no audio and call no tools.\n"
            "- If a tool result says 'Not executed', say nothing.\n"
        )

    def _build_config(self) -> types.LiveConnectConfig:
        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            # (A transcription language can't be set: the Gemini API rejects
            # language_codes. English-by-default is in the system prompt.)
            input_audio_transcription=types.AudioTranscriptionConfig(),
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
                    silence_duration_ms=END_OF_TURN_SILENCE_MS,
                )
            ),
            system_instruction=self._get_system_prompt(),
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Charon"  # Mark-XXX reference — deep, authoritative
                    )
                )
            )
        )

    def _execute_tool(self, fc) -> types.FunctionResponse:
        """Execute a tool call (runs in thread pool to avoid blocking audio)."""
        name = fc.name
        args = dict(fc.args or {})
        _log.info(f"[LIVE] TOOL: {name}  ARGS: {args}")

        result = "Action completed."
        try:
            context = {
                'perception': self.perception,
                'websocket': None,
                'server': self.server,
                'title': 'sir',
                'youtube': getattr(self.server, 'youtube_downloader', None) if self.server else None,
                'whatsapp_handler': getattr(self.server, 'whatsapp_handler', None) if self.server else None,
                'reminder_manager': getattr(self.server, 'reminder_manager', None) if self.server else None,
                'system_control': getattr(self.server, 'system_control', None) if self.server else None,
                'entertainment': getattr(self.server, 'entertainment', None) if self.server else None,
                'news_handler': getattr(self.server, 'news_handler', None) if self.server else None,
                'alarm_manager': getattr(self.server, 'alarm_manager', None) if self.server else None,
                'screen_control': getattr(self.server, 'screen_control', None) if self.server else None,
                'dictionary_handler': getattr(self.server, 'dictionary_handler', None) if self.server else None,
                'chat_history': getattr(self.server, 'chat_history', None) if self.server else None,
                'context_memory': getattr(self.server, 'context_memory', None) if self.server else None,
                # COORD-FIX: These were missing — caused weather/screenshot/OCR failures via voice
                'weather_handler': getattr(self.server, 'weather_handler', None) if self.server else None,
                'knowledge': getattr(self.server, 'knowledge', None) if self.server else None,
                'ocr_handler': getattr(self.server, 'ocr_handler', None) if self.server else None,
                'screenshot_handler': getattr(self.server, 'screenshot_handler', None) if self.server else None,
                'alarm_system': getattr(self.server, 'alarm_system', None) if self.server else None,
                'face_auth': getattr(self.server, 'face_recognition', None) if self.server else None,
            }

            if name == "open_app":
                handler = HANDLER_MAP.get("open_app")
                if handler:
                    res = handler(cmd="", entities={"app": args.get("app_name", "")}, context=context)
                    result = getattr(res, "response", "Opened app.")

            elif name == "send_message":
                # Spoken replies go to Gemini in live mode, so a second identical
                # call while that draft waits is the user's "yes, send it".
                result = self._tool_send_message(args, context, result)

            elif name == "weather_report":
                handler = HANDLER_MAP.get("weather")
                if handler:
                    res = handler(cmd="", entities={"city": args.get("city")}, context=context)
                    result = getattr(res, "response", "Weather reported.")

            elif name == "youtube_video":
                result = self._tool_youtube_video(args, result)

            elif name == "web_search":
                result = self._tool_web_search(args, context, result)

            elif name == "computer_settings":
                result = self._tool_computer_settings(args, context, result)

            elif name == "set_reminder":
                result = self._tool_set_reminder(args, context, result)

            elif name == "tell_time":
                handler = HANDLER_MAP.get("time")
                if handler:
                    res = handler(cmd="", entities={}, context=context)
                    result = getattr(res, "response", datetime.datetime.now().strftime("%I:%M %p"))

            elif name == "tell_joke":
                handler = HANDLER_MAP.get("joke")
                if handler:
                    res = handler(cmd="", entities={}, context=context)
                    result = getattr(res, "response", "I'm afraid my humor circuits are offline, sir.")

            elif name == "play_music":
                handler = HANDLER_MAP.get("play_music")
                if handler:
                    res = handler(cmd="", entities={"song": args.get("song", "")}, context=context)
                    result = getattr(res, "response", "Playing music.")

            elif name == "system_status":
                handler = HANDLER_MAP.get("system_status")
                if handler:
                    res = handler(cmd="", entities={}, context=context)
                    result = getattr(res, "response", "System nominal.")

            elif name == "news":
                handler = HANDLER_MAP.get("news")
                if handler:
                    res = handler(cmd="", entities={"topic": args.get("topic", "")}, context=context)
                    result = getattr(res, "response", "Here are the latest headlines.")

            # ── Window & Screen Control ──

            elif name == "close_app":
                result = self._tool_close_app(args, result)

            elif name == "switch_to_app":
                result = self._tool_switch_app(args, result)

            elif name == "screen_action":
                result = self._tool_screen_action(args, result)

            elif name == "type_text":
                result = self._tool_type_text(args, result)

            elif name == "read_screen":
                question = args.get("question", "Describe what is on the screen.")
                result = self._read_screen(question)

            # ── Music Control ──
            elif name == "music_control":
                result = self._tool_music_control(args, context, result)

            # ── Alarm ──
            elif name == "set_alarm":
                result = self._tool_set_alarm(args, context, result)

            # ── Timer ──
            elif name == "set_timer":
                result = self._tool_set_timer(args, context, result)

            # ── List Reminders ──
            elif name == "list_reminders":
                handler = HANDLER_MAP.get("list_reminders")
                if handler:
                    res = handler(cmd="", entities={}, context=context)
                    result = getattr(res, "response", "No upcoming reminders.")

            # ── Brightness ──
            elif name == "brightness_control":
                result = self._tool_brightness_control(args, context, result)

            # ── Screenshot ──
            elif name == "take_screenshot":
                result = self._tool_take_screenshot(context, result)

            # ── Dictionary ──
            elif name == "dictionary_lookup":
                handler = HANDLER_MAP.get("dictionary")
                word = args.get("word", "")
                if handler:
                    res = handler(cmd=f"define {word}", entities={"word": word}, context=context)
                    result = getattr(res, "response", f"Could not find definition for {word}.")

            # ── Memory: Remember ──
            elif name == "remember_this":
                handler = HANDLER_MAP.get("remember")
                info = args.get("information", "")
                if handler:
                    res = handler(cmd=f"remember {info}", entities={"fact": info, "raw_command": f"remember {info}"}, context=context)
                    result = getattr(res, "response", "Noted, sir.")

            # ── Memory: Recall ──
            elif name == "recall_memory":
                handler = HANDLER_MAP.get("recall")
                query = args.get("query", "")
                if handler:
                    res = handler(cmd=f"recall {query}", entities={"query": query, "raw_command": f"recall {query}"}, context=context)
                    result = getattr(res, "response", "I don't have that in memory, sir.")

            # ── Conversation Recall ──
            elif name == "recall_conversation":
                query = args.get("query", "")
                if self.server and hasattr(self.server, 'recall_conversation'):
                    result = self.server.recall_conversation(query)
                else:
                    result = "Conversation history search not available."

            # ── Workflow Automation ──
            elif name == "run_workflow":
                result = self._tool_run_workflow(args, result)

            # ── Email ──
            elif name == "send_email":
                result = self._tool_send_email(args, result)

            # ── Hand gestures on/off ──
            elif name == "gesture_control":
                result = self._tool_gesture_control(args, result)

            # ── Mute / Unmute JARVIS (C-02) ──
            elif name == "mute_jarvis":
                result = self._tool_mute_jarvis(result)

            elif name == "unmute_jarvis":
                self._muted = False
                result = "Back online, sir. What do you need?"
                _log.info("[LIVE] JARVIS unmuted by user request")

            # ── COORD-FIX: New tool dispatches via HANDLER_MAP ──
            elif name == "read_screen_text":
                result = self._tool_read_screen(context, result)

            elif name == "habit_tracker":
                result = self._tool_habit_tracker(args, context, result)

            elif name == "check_calendar":
                result = self._tool_check_calendar(context, result)

            elif name == "tell_story":
                result = self._tool_tell_story(args, context, result)

            else:
                result = f"Tool {name} is not implemented yet."

        except Exception as e:
            _log.warning(f"[LIVE] Tool execution failed: {name} - {e}")
            traceback.print_exc()
            
            # ── ERROR RECOVERY: try fallback via HANDLER_MAP ──
            try:
                fallback_handler = HANDLER_MAP.get(name)
                if fallback_handler:
                    _log.info(f"[LIVE] Attempting fallback via HANDLER_MAP for '{name}'...")
                    raw_cmd = ' '.join(str(v) for v in args.values() if v)
                    fallback_res = fallback_handler(
                        cmd=raw_cmd,
                        entities=args,
                        context={'source': 'gemini_live_fallback'}
                    )
                    result = getattr(fallback_res, 'response', None)
                    if result:
                        _log.info(f"[LIVE] Fallback succeeded: {result[:80]}")
                    else:
                        result = f"The {name} command encountered an issue, sir. Error: {str(e)[:100]}"
                else:
                    result = f"The {name} command failed, sir. I'll note this for next time. Error: {str(e)[:100]}"
            except Exception as fallback_err:
                _log.warning(f"[LIVE] Fallback also failed: {fallback_err}")
                result = f"Both primary and fallback execution failed for {name}, sir. Error: {str(e)[:80]}"

        _log.info(f"[LIVE] RESULT: {result[:100]}")

        return types.FunctionResponse(
            id=fc.id,
            name=name,
            response={"result": result}
        )

    def _tool_send_message(self, args, context, result):
        """Step of _execute_tool(): Send_message."""
        from jarvis.core.services import peek as _peek
        from jarvis.core.whatsapp_handler import WhatsAppHandler as _WA
        _wa = (getattr(self.server, 'whatsapp_handler', None) if self.server else None) or _peek(_WA)
        _draft = _wa.pending_draft() if _wa else None
        handler = HANDLER_MAP.get("send_message")
        if _draft and (args.get("receiver") or "").strip().lower() == _draft.contact.lower()                         and (args.get("message_text") or "").strip() == _draft.message:
            result = _wa.confirm_send()
            handler = None
        if handler:
            entities = {
                "contact": args.get("receiver"),
                "message": args.get("message_text"),
            }
            res = handler(cmd="", entities=entities, context=context)
            result = getattr(res, "response", "")
            _wa = _wa or _peek(_WA)  # the handler may have just been created
            if _wa and _wa.pending_draft():
                result += (" (Not sent yet. Ask the user to confirm; only call send_message "
                           "again, with the same receiver and message_text, if they say yes.)")
        return result

    def _tool_youtube_video(self, args, result):
        """Step of _execute_tool(): Youtube_video."""
        query = args.get("query", "")
        played = False
        # Try our YouTube downloader first
        yt = getattr(self.server, 'youtube_downloader', None) if self.server else None
        if yt and hasattr(yt, 'search_and_play'):
            try:
                yt.search_and_play(query)
                result = f"Playing {query} on YouTube."
                played = True
            except Exception as e:
                _log.warning(f"[LIVE] YouTube downloader failed: {e}")
        if not played:
            # Open YouTube search and auto-click first result
            import urllib.parse
            url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
            webbrowser.open_new_tab(url)
            # Auto-click first video after page loads
            import time as _yt_time
            import pyautogui as _yt_pag
            def _auto_play():
                _yt_time.sleep(3.5)  # Wait for YouTube page to load
                # Tab to first video result and press Enter
                _yt_pag.press('tab', presses=8, interval=0.05)
                _yt_time.sleep(0.2)
                _yt_pag.press('enter')
            threading.Thread(target=_auto_play, daemon=True).start()
            result = f"Playing {query} on YouTube."
        return result

    def _tool_web_search(self, args, context, result):
        """Step of _execute_tool(): Web_search."""
        handler = HANDLER_MAP.get("search") or HANDLER_MAP.get("ai_search")
        if handler:
            res = handler(cmd="", entities={"query": args.get("query")}, context=context)
            result = getattr(res, "response", "Search completed.")
        else:
            import urllib.parse
            url = f"https://www.google.com/search?q={urllib.parse.quote(args.get('query', ''))}"
            webbrowser.open(url)
            result = f"Opened Google search for: {args.get('query')}"
        return result

    def _tool_computer_settings(self, args, context, result):
        """Step of _execute_tool(): Computer_settings."""
        action = (args.get("action") or args.get("description") or "").lower().replace(" ", "_")
        # C-03 + M-01: Route each action to the correct handler
        if action in ("shutdown", "shut_down", "power_off"):
            result = self._tool_power(result)
        elif action in ("restart", "reboot"):
            # Never restart straight from an LLM tool call: arm the
            # server's confirmation step; the user must say/type "confirm".
            # In live mode spoken replies go to Gemini, so a SECOND restart
            # call while one is pending (i.e. after JARVIS asked and the user
            # answered) counts as the confirmation.
            result = self._tool_restart_reboot(result)
        elif action in ("lock", "lock_screen"):
            from jarvis.core.safe_exec import lock_workstation
            lock_workstation()
            result = "Screen locked."
        elif "screenshot" in action:
            result = self._tool_screenshot(context, result)
        elif "mute" in action or "unmute" in action:
            result = self._tool_mute_unmute(action, context, result)
        elif "volume" in action or "brightness" in action:
            result = self._tool_volume_brightness(action, args, context, result)
        elif "close" in action:
            # Delegate to close_app
            result = self._tool_close(args, result)
        else:
            # Generic fallback — try system_control
            result = self._tool_generic_fallback(action, args, result)
        return result

    def _tool_power(self, result):
        """Step of _tool_computer_settings(): power."""
        import signal as _sig
        self._push_to_chat("Shutting down all systems. Until next time, sir.", role='jarvis')
        result = "Shutting down."
        # Schedule exit after response sends
        def _delayed_exit():
            import time as _dt; _dt.sleep(2)
            os.kill(os.getpid(), _sig.SIGTERM)
        threading.Thread(target=_delayed_exit, daemon=True).start()
        return result

    def _tool_restart_reboot(self, result):
        """Step of _tool_computer_settings(): Restart reboot."""
        if self.server and hasattr(self.server, 'request_power_action'):
            if self.server._get_pending_power_action() == 'restart':
                self.server._pending_power_action = None
                result = self.server._execute_power_action('restart', '')
            else:
                result = self.server.request_power_action('restart')
                result += " (Ask the user to confirm; only call restart again if they say yes.)"
        else:
            result = "Restart needs manual confirmation; it is disabled here."
        return result

    def _tool_screenshot(self, context, result):
        """Step of _tool_computer_settings(): Screenshot."""
        handler = HANDLER_MAP.get("screenshot")
        if handler:
            res = handler(cmd="screenshot", entities={}, context=context)
            result = getattr(res, "response", "Screenshot taken.")
        else:
            result = "Screenshot handler not available."
        return result

    def _tool_mute_unmute(self, action, context, result):
        """Step of _tool_computer_settings(): Mute unmute."""
        handler = HANDLER_MAP.get("volume")
        if handler:
            res = handler(cmd=action, entities={}, context=context)
            result = getattr(res, "response", "Audio toggled.")
        else:
            result = "Volume control not available."
        return result

    def _tool_volume_brightness(self, action, args, context, result):
        """Step of _tool_computer_settings(): Volume brightness."""
        handler_key = "volume" if "volume" in action else "brightness"
        handler = HANDLER_MAP.get(handler_key)
        if handler:
            entities = {"level": args.get("value", "")}
            res = handler(cmd=action, entities=entities, context=context)
            result = getattr(res, "response", "Setting adjusted.")
        else:
            result = f"{handler_key.title()} control not available."
        return result

    def _tool_close(self, args, result):
        """Step of _tool_computer_settings(): Close."""
        app_name = args.get("value", "")
        switcher = self._get_app_switcher()
        if switcher and app_name:
            switcher.close_app(app_name)
            result = f"Closed {app_name}."
        else:
            result = "Close action needs an app name."
        return result

    def _tool_generic_fallback(self, action, args, result):
        """Step of _tool_computer_settings(): generic fallback."""
        sc = getattr(self.server, 'system_control', None) if self.server else None
        if sc and hasattr(sc, 'execute'):
            try:
                res = sc.execute(action, args.get("value", ""))
                result = res if isinstance(res, str) else "Setting adjusted."
            except Exception:
                result = f"Computer setting '{action}' noted."
        else:
            result = f"Computer setting '{action}' noted."
        return result


    def _tool_set_reminder(self, args, context, result):
        """Step of _execute_tool(): Set_reminder."""
        handler = HANDLER_MAP.get("set_reminder")
        if handler:
            # Build a natural language command for the parser
            time_str = args.get("time", "")
            message_str = args.get("message", "")
            raw_cmd = f"remind me to {message_str} {time_str}"
            res = handler(cmd=raw_cmd, entities={
                "time": time_str,
                "message": message_str,
                "raw_command": raw_cmd
            }, context=context)
            result = getattr(res, "response", "Reminder set.")
        return result

    def _tool_close_app(self, args, result):
        """Step of _execute_tool(): Close_app."""
        app_name = args.get("app_name", "")
        switcher = self._get_app_switcher()
        if switcher:
            success = switcher.close_app(app_name)
            result = f"Closed {app_name}." if success else f"Couldn't find {app_name} to close."
        else:
            # Fallback: use taskkill
            from jarvis.core.safe_exec import kill_process
            try:
                if kill_process(app_name):
                    result = f"Force closed {app_name}."
                else:
                    result = f"Couldn't find {app_name} to close."
            except Exception:
                result = f"Couldn't close {app_name}."
        return result

    def _tool_switch_app(self, args, result):
        """Step of _execute_tool(): Switch_to_app."""
        app_name = args.get("app_name", "")
        switcher = self._get_app_switcher()
        if switcher:
            success = switcher.switch_to(app_name)
            result = f"Switched to {app_name}." if success else f"Couldn't find {app_name}."
        else:
            result = "Window switching not available."
        return result

    def _tool_screen_action(self, args, result):
        """Step of _execute_tool(): Screen_action."""
        action = args.get("action", "").lower().replace(" ", "_")
        import pyautogui
        ACTION_MAP = {
            "minimize": ("win", "down"),
            "maximize": ("win", "up"),
            "fullscreen": ("f11",),
            "alt_tab": ("alt", "tab"),
            "ctrl_w": ("ctrl", "w"),
            "ctrl_c": ("ctrl", "c"),
            "ctrl_v": ("ctrl", "v"),
            "ctrl_z": ("ctrl", "z"),
            "ctrl_a": ("ctrl", "a"),
            "ctrl_s": ("ctrl", "s"),
            "ctrl_t": ("ctrl", "t"),
            "ctrl_n": ("ctrl", "n"),
            "press_enter": ("enter",),
            "press_escape": ("escape",),
            "press_space": ("space",),
            "pause": ("space",),
            "play_pause": ("space",),
            "stop": ("space",),
            "pause_video": ("space",),
            "stop_video": ("space",),
            "resume": ("space",),
            "next_tab": ("ctrl", "tab"),
            "previous_tab": ("ctrl", "shift", "tab"),
            "prev_tab": ("ctrl", "shift", "tab"),
            "close_tab": ("ctrl", "w"),
            "new_tab": ("ctrl", "t"),
            "reopen_tab": ("ctrl", "shift", "t"),
            "refresh": ("f5",),
            "go_back": ("alt", "left"),
            "go_forward": ("alt", "right"),
            "scroll_up": None,
            "scroll_down": None,
            "click": None,
        }
        # Keys go to the focused window. If that's the JARVIS HUD (it
        # usually is right after you talk to it), "next tab" switched
        # the HUD's own tab or did nothing: hand focus back first.
        from jarvis.core.screen_control import focus_away_from_jarvis, ScreenControlHandler
        from jarvis.core.services import shared
        focus_away_from_jarvis()
        if action not in ACTION_MAP and not any(w in action for w in ('pause', 'stop', 'play', 'resume')):
            # Anything else ("switch to tab 3", "zoom in", ...): the
            # screen-control handler typed commands use
            try:
                handled = shared(ScreenControlHandler).handle(action.replace('_', ' '))
            except Exception as e:
                handled = None
                _log.warning(f"[LIVE] screen_action fallback failed: {e}")
            if handled and not str(handled).lower().startswith(("unknown", "i don't", "sorry")):
                action, result = None, str(handled)
        if action is None:
            pass
        elif action in ACTION_MAP:
            result = self._press_action_keys(ACTION_MAP, action, pyautogui, result)
        else:
            # Try pressing space for any pause/stop/play type action
            if any(w in action for w in ['pause', 'stop', 'play', 'resume']):
                pyautogui.press('space')
                result = f"Toggled playback."
            else:
                result = f"Unknown screen action: {action}"
        return result

    def _press_action_keys(self, ACTION_MAP, action, pyautogui, result):
        """Step of _tool_screen_action(): action keys."""
        keys = ACTION_MAP[action]
        if keys:
            if len(keys) == 1:
                pyautogui.press(keys[0])
            else:
                pyautogui.hotkey(*keys)
            result = f"Performed {action.replace('_', ' ')}."
        elif action == "scroll_up":
            pyautogui.scroll(5)
            result = "Scrolled up."
        elif action == "scroll_down":
            pyautogui.scroll(-5)
            result = "Scrolled down."
        elif action == "click":
            pyautogui.click()
            result = "Clicked."
        return result


    def _tool_type_text(self, args, result):
        """Step of _execute_tool(): type text."""
        text = args.get("text", "")
        if text:
            import pyautogui
            pyautogui.write(text, interval=0.02)
            result = f"Typed: {text}"
        else:
            result = "No text specified."
        return result

    def _tool_music_control(self, args, context, result):
        """Step of _execute_tool(): Music_control."""
        action = args.get("action", "").lower()
        handler_key = {
            "pause": "pause_music", "resume": "play_music",
            "next": "next_track", "previous": "previous_track",
            "stop": "pause_music"
        }.get(action, "pause_music")
        handler = HANDLER_MAP.get(handler_key)
        if handler:
            res = handler(cmd=action, entities={}, context=context)
            result = getattr(res, "response", f"Music {action}.")
        else:
            result = f"Music control '{action}' not available."
        return result

    def _tool_set_alarm(self, args, context, result):
        """Step of _execute_tool(): Set_alarm."""
        handler = HANDLER_MAP.get("set_alarm")
        if handler:
            time_str = args.get("time", "")
            label = args.get("label", "alarm")
            raw_cmd = f"set alarm for {time_str} {label}"
            res = handler(cmd=raw_cmd, entities={
                "time": time_str, "label": label, "raw_command": raw_cmd
            }, context=context)
            result = getattr(res, "response", "Alarm set.")
        return result

    def _tool_set_timer(self, args, context, result):
        """Step of _execute_tool(): Set_timer."""
        handler = HANDLER_MAP.get("set_timer")
        if handler:
            duration = args.get("duration", "")
            label = args.get("label", "timer")
            raw_cmd = f"set timer for {duration} {label}"
            res = handler(cmd=raw_cmd, entities={
                "duration": duration, "label": label, "raw_command": raw_cmd
            }, context=context)
            result = getattr(res, "response", "Timer set.")
        return result

    def _tool_brightness_control(self, args, context, result):
        """Step of _execute_tool(): Brightness_control."""
        handler = HANDLER_MAP.get("brightness")
        action = args.get("action", "up")
        level = args.get("level", "")
        if handler:
            cmd = f"brightness {action}"
            if level:
                cmd = f"set brightness to {level}"
            res = handler(cmd=cmd, entities={"level": level}, context=context)
            result = getattr(res, "response", "Brightness adjusted.")
        return result

    def _tool_take_screenshot(self, context, result):
        """Step of _execute_tool(): Take_screenshot."""
        handler = HANDLER_MAP.get("screenshot")
        if handler:
            res = handler(cmd="screenshot", entities={}, context=context)
            result = getattr(res, "response", "Screenshot taken.")
        else:
            # Fallback to screenshot_handler on server
            sh = getattr(self.server, 'screenshot_handler', None) if self.server else None
            if sh:
                path = sh.take_screenshot()
                result = f"Screenshot saved to {path}." if path else "Screenshot failed."
            else:
                import pyautogui
                ss = pyautogui.screenshot()
                p = Path.home() / "Pictures" / f"jarvis_screenshot_{datetime.datetime.now().strftime('%H%M%S')}.png"
                ss.save(str(p))
                result = f"Screenshot saved to {p.name}."
        return result

    def _tool_run_workflow(self, args, result):
        """Step of _execute_tool(): Run_workflow."""
        command = args.get("command", "")
        try:
            from jarvis.core.workflow_manager import get_workflow_manager
            wm = get_workflow_manager(
                jarvis_core=getattr(self.server, 'jarvis', None),
                perception=self.perception
            )
            workflow = wm.parse_workflow(command)
            if workflow:
                threading.Thread(
                    target=wm.execute_workflow,
                    args=(workflow,),
                    daemon=True
                ).start()
                result = f"Running {len(workflow.steps)}-step workflow: {command}"
            elif wm.is_workflow_command(command):
                threading.Thread(
                    target=wm.handle,
                    args=(command,),
                    daemon=True
                ).start()
                result = f"Running workflow: {command}"
            else:
                result = f"Couldn't parse as a workflow: {command}"
        except Exception as e:
            result = f"Workflow error: {e}"
        return result

    def _tool_send_email(self, args, result):
        """Step of _execute_tool(): Send_email."""
        email_handler = getattr(self.server, 'email_handler_obj', None) if self.server else None
        if email_handler and hasattr(email_handler, 'send_email'):
            to = args.get("to", "")
            subject = args.get("subject", "")
            body = args.get("body", "")
            try:
                email_handler.send_email(to, subject, body)
                result = f"Email sent to {to}."
            except Exception as e:
                result = f"Failed to send email: {e}"
        else:
            result = "Email service not configured."
        return result

    def _tool_gesture_control(self, args, result):
        """Step of _execute_tool(): Gesture_control."""
        setter = getattr(self.server, 'set_gesture_enabled', None) if self.server else None
        if setter is None:
            result = "Gesture control isn't available."
        else:
            on = args.get("enabled")
            on = on if isinstance(on, bool) else str(on).strip().lower() in ("true", "on", "1", "yes")
            result = setter(on, 'sir')
        return result

    def _tool_mute_jarvis(self, result):
        """Step of _execute_tool(): Mute_jarvis."""
        self._muted = True
        # Drain any pending audio so silence is immediate
        if self.audio_in_queue:
            while not self.audio_in_queue.empty():
                try: self.audio_in_queue.get_nowait()
                except Exception: break
        result = "Muted. I'll stay silent until you need me."
        _log.info("[LIVE] JARVIS muted by user request")
        return result

    def _tool_read_screen(self, context, result):
        """Step of _execute_tool(): Read_screen_text."""
        handler = HANDLER_MAP.get("ocr")
        if handler:
            res = handler(cmd="read screen", entities={}, context=context)
            result = res.response if res else "OCR not available."
        else:
            result = "OCR handler not found."
        return result

    def _tool_habit_tracker(self, args, context, result):
        """Step of _execute_tool(): Habit_tracker."""
        handler = HANDLER_MAP.get("habit")
        if handler:
            action = args.get("action", "list")
            habit_name = args.get("habit_name", "")
            cmd_text = f"{action} habit {habit_name}".strip()
            res = handler(cmd=cmd_text, entities={}, context=context)
            result = res.response if res else "Habit tracker not available."
        else:
            result = "Habit tracker not found."
        return result

    def _tool_check_calendar(self, context, result):
        """Step of _execute_tool(): Check_calendar."""
        handler = HANDLER_MAP.get("calendar")
        if handler:
            res = handler(cmd="events today", entities={}, context=context)
            result = res.response if res else "Calendar not available."
        else:
            result = "Calendar handler not found."
        return result

    def _tool_tell_story(self, args, context, result):
        """Step of _execute_tool(): Tell_story."""
        handler = HANDLER_MAP.get("story")
        if handler:
            genre = (args.get("genre") or "").strip()
            topic = (args.get("topic") or "").strip()
            entities = {"genre": genre} if genre else {}
            cmd = f"tell me a {genre + ' ' if genre else ''}story" + (f" about {topic}" if topic else "")
            res = handler(cmd=cmd, entities=entities, context=context)
            story = res.response if res else ""
            # Gemini used to get the bare story back and just say "Sweet
            # dreams, sir": the story was written but never told
            result = ("Narrate this story to the user now, aloud, in full and word for word. "
                      "Don't summarise it or comment first.\n\n" + story) if story else \
                     "The story couldn't be written. Tell the user a short story yourself."
        else:
            result = "Story handler not found."
        return result


    # ── Audio I/O ────────────────────────────────────────────────

    async def _listen_audio(self):
        import time as _mic_time
        _pya = _get_pya()
        stream = await asyncio.to_thread(
            _pya.open,
            format=FORMAT, channels=CHANNELS,
            rate=SEND_SAMPLE_RATE, input=True,
            frames_per_buffer=CHUNK_SIZE,
        )
        _log.info(f"[LIVE] Mic started (chunk={CHUNK_SIZE}, rate={SEND_SAMPLE_RATE})")
        _mic_count = 0
        try:
            while self._running:
                data = await asyncio.to_thread(stream.read, CHUNK_SIZE, exception_on_overflow=False)
                _mic_count += 1
                if _mic_count == 1:
                    _log.info(f"[LIVE] First mic chunk captured ({len(data)}B)")
                # M-08: time import moved outside loop
                if _mic_time.time() < self._speaking_until:
                    continue
                try:
                    self.out_queue.put_nowait({"data": data, "mime_type": "audio/pcm"})
                except asyncio.QueueFull:
                    # drop OLDEST instead of newest
                    try:
                        self.out_queue.get_nowait()
                        self.out_queue.put_nowait({"data": data, "mime_type": "audio/pcm"})
                    except Exception:
                        _log.debug("Ignored error", exc_info=True)
        except Exception as e:
            if self._running:
                _log.warning(f"[LIVE] Mic error: {e}")
        finally:
            stream.close()

    async def _receive_audio(self):
        _log.info("[LIVE] Receiver started")
        # Mo-01: import time once before loop — not inside hot path
        import time as _recv_time
        in_buf = []
        out_buf = []
        _recv_errors = 0  # consecutive receive failures (see the except below)
        try:
            while self._running:
                try:
                    async for response in self.session.receive():
                        if self._interrupt_flag:
                            # skip everything until new clean turn
                            if response.server_content and response.server_content.turn_complete:
                                self._interrupt_flag = False
                            continue

                        # 🚨 HARD INTERRUPT: clear pending audio on new input
                        if response.server_content and response.server_content.interrupted:
                            self._interrupt_flag = True
                            self._current_turn_id += 1
                            in_buf = []
                            out_buf = []
                            self._raw_in = ""
                            while not self.audio_in_queue.empty():
                                try:
                                    self.audio_in_queue.get_nowait()
                                except Exception:
                                    break
                        
                            # also skip further processing of this response
                            continue

                        # PCM audio from Gemini
                        if response.data and not self.is_awake():
                            # Reply to speech that wasn't addressed to JARVIS: mute it
                            if not self._turn_suppressed:
                                _log.info("[WAKE] Asleep - muting reply to speech without the wake word")
                            self._turn_suppressed = True
                        elif response.data:
                            if not hasattr(self, '_audio_count'):
                                self._audio_count = 0
                            if self._audio_count == 0:
                                _log.info(f"[LIVE] Response audio started")
                            await self.audio_in_queue.put(response.data)
                            self._audio_count += 1
                            if self._audio_count <= 3 or self._audio_count % 200 == 0:
                                _log.info(f"[LIVE] Audio chunk #{self._audio_count} ({len(response.data)}B)")

                        # Transcription logging (like Mark-XXX)
                        if response.server_content:
                            sc = response.server_content
                            if sc.input_transcription and sc.input_transcription.text:
                                txt = sc.input_transcription.text.strip()
                                if txt:

                                    # Mo-01: use pre-imported time for echo suppression
                                    if _recv_time.time() < self._speaking_until:
                                        pass  # echo — discard
                                    else:
                                        # C-04: Drain stale audio when new user input starts
                                        if not in_buf:
                                            self._current_turn_id += 1
                                            while not self.audio_in_queue.empty():
                                                try: self.audio_in_queue.get_nowait()
                                                except Exception: break
                                        in_buf.append(txt)
                                        self._raw_in += sc.input_transcription.text
                                        # Wake-word gate on the raw joined fragments
                                        if self.note_user_speech(self._raw_in):
                                            self._turn_addressed = True
                            if sc.output_transcription and sc.output_transcription.text:
                                txt = sc.output_transcription.text.strip()
                                if txt:
                                    out_buf.append(txt)
                            if sc.turn_complete:
                                current_turn = self._current_turn_id
                                try:
                                    if in_buf and self._wake_gate and not self._turn_addressed:
                                        # Background speech: keep it out of the HUD chat
                                        safe = (self._raw_in or " ".join(in_buf)).strip().encode('ascii', errors='replace').decode()
                                        _log.info(f"[WAKE] Heard, not addressed: {safe[:80]}")
                                        in_buf = []
                                    if in_buf:
                                        full_in = (self._raw_in or " ".join(in_buf)).strip()
                                        # Mo-01: use pre-imported time
                                        _now = _recv_time.time()
                                        _last_in = getattr(self, '_last_in_text', '')
                                        _last_in_t = getattr(self, '_last_in_time', 0)
                                        if full_in and (full_in != _last_in or (_now - _last_in_t) > 3):
                                            safe = full_in.encode('ascii', errors='replace').decode()
                                            _log.info(f"[YOU]    {safe}")
                                            self._push_to_chat(full_in, role='user', turn_id=current_turn)
                                            self._last_in_text = full_in
                                            self._last_in_time = _now
                                        in_buf = []
                                    if out_buf and self._turn_suppressed:
                                        safe = " ".join(out_buf).encode('ascii', errors='replace').decode()
                                        _log.info(f"[WAKE] Muted reply: {safe[:80]}")
                                        out_buf = []
                                    elif out_buf and getattr(self, '_sleep_after_reply', False):
                                        self.sleep()        # "good night" answered: now sleep
                                    elif out_buf and self.is_awake():
                                        self.wake("reply")  # allow a follow-up after JARVIS answers
                                    if out_buf:
                                        full_out = " ".join(out_buf).strip()
                                        # Deduplicate: skip if same as last output within 3s
                                        _last_out = getattr(self, '_last_out_text', '')
                                        _last_out_t = getattr(self, '_last_out_time', 0)
                                        if full_out and (full_out != _last_out or (_now - _last_out_t) > 3):
                                            safe = full_out.encode('ascii', errors='replace').decode()
                                            _log.info(f"[JARVIS] {safe}")
                                            # C-02: Don't push to chat if muted (but still log)
                                            if not self._muted:
                                                self._push_to_chat(full_out, role='jarvis', turn_id=current_turn)
                                            self._last_out_text = full_out
                                            self._last_out_time = _now
                                        out_buf = []
                                except Exception:
                                    in_buf = []
                                    out_buf = []
                                self._turn_suppressed = False
                                self._turn_addressed = False
                                self._raw_in = ""
                        
                            # Mo-10: Removed duplicate interrupted handler —
                            # already handled at L1165 above

                        # Tool calls — run in executor, non-blocking
                        if response.tool_call:

                            turn_id = self._current_turn_id

                            async def _handle_tools(tool_call, session):
                                fn_responses = []
                                loop = asyncio.get_event_loop()

                                # Mo-09: Process ALL tool calls (not just first) for multi-tool workflows
                                for fc in tool_call.function_calls:
                                    if not self.is_awake():
                                        # Wake-word gate: never act on background speech
                                        _log.info(f"[WAKE] Blocked tool {fc.name} (not addressed)")
                                        fn_responses.append(types.FunctionResponse(
                                            id=fc.id, name=fc.name,
                                            response={"result": NOT_ADDRESSED_RESULT}))
                                        continue
                                    fr = await loop.run_in_executor(
                                        self._tool_executor, self._execute_tool, fc
                                    )
                                    fn_responses.append(fr)

                                if turn_id != self._current_turn_id:
                                    _log.info("[TURN] Dropping stale response")
                                    return

                                await session.send_tool_response(function_responses=fn_responses)

                            async with self._tool_lock:
                                await _handle_tools(response.tool_call, self.session)

                    _recv_errors = 0  # a full turn arrived: the session is healthy
                except StopAsyncIteration:
                    # Stream ended — Gemini closed the session, loop will reconnect
                    _log.info("[LIVE] Receive stream ended, waiting to reconnect...")
                    await asyncio.sleep(1)
                    break
                except Exception as recv_err:
                    if self._running:
                        _log.warning(f"[LIVE] Receive stream error: {recv_err}")
                    # A closed connection raises on every receive(). Retrying it
                    # forever left a dead session that never reconnected (JARVIS
                    # went silent). End this task instead: start_async then
                    # tears the session down and the run loop reconnects.
                    _recv_errors += 1
                    if _recv_errors >= 3 or 'close' in str(recv_err).lower():
                        _log.info("[LIVE] Session lost, reconnecting...")
                        break
                    await asyncio.sleep(0.5)

        except asyncio.CancelledError:
            _log.debug("Ignored error", exc_info=True)
        except Exception as e:
            _log.warning(f"[LIVE] Receiver error: {e}")
            traceback.print_exc()

    async def _play_audio(self):
        _log.info("[LIVE] Playback started")
        try:
            _pya = _get_pya()
            stream = await asyncio.to_thread(
                _pya.open,
                format=FORMAT, channels=CHANNELS,
                rate=RECEIVE_SAMPLE_RATE, output=True,
            )
            _log.info(f"[LIVE] Speaker stream opened: {CHANNELS}ch @ {RECEIVE_SAMPLE_RATE}Hz")
        except Exception as e:
            _log.warning(f"[LIVE] FAILED to open speaker: {e}")
            return
        play_count = 0
        try:
            import time as _pt  # Mo-09: moved outside loop
            while self._running:
                chunk = await self.audio_in_queue.get()
                if chunk:
                    # C-02: Skip playback when muted
                    if self._muted:
                        play_count += 1
                        continue
                    if play_count == 0:
                        _log.info(f"[LIVE] Playback audio started")
                    await asyncio.to_thread(stream.write, chunk)
                    self._speaking_until = _pt.time() + 0.8   # C-04: increased from 0.4 to 0.8
                    play_count += 1
                    if play_count <= 3 or play_count % 100 == 0:
                        _log.info(f"[LIVE] Played chunk #{play_count} ({len(chunk)}B)")
        except asyncio.CancelledError:
            _log.debug("Ignored error", exc_info=True)
        except Exception as e:
            if self._running:
                _log.warning(f"[LIVE] Playback error: {e}")
                traceback.print_exc()
        finally:
            stream.close()

    async def _send_realtime(self):
        try:
            while self._running:
                msg = await self.out_queue.get()
                try:
                    await self.session.send_realtime_input(media=msg)
                except (ConnectionError, ConnectionResetError, OSError) as e:
                    if self._running:
                        _log.warning(f"[LIVE] Send error (will reconnect): {e}")
                    break
        except asyncio.CancelledError:
            _log.debug("Ignored error", exc_info=True)
        except Exception as e:
            if self._running:
                _log.warning(f"[LIVE] Send loop error: {e}")

    # ── Lifecycle ─────────────────────────────────────────────────

    async def start_async(self):
        # ── Kill ghost tasks: cancel AND await so streams actually close ──
        for task_name in ["_listen_task", "_receive_task", "_play_task", "_send_task"]:
            task = getattr(self, task_name, None)
            if task and not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
                except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                    _log.debug("Ignored error", exc_info=True)
            setattr(self, task_name, None)
        await asyncio.sleep(0.2)  # Let PyAudio streams fully release

        # ── Drain stale audio from previous session ──
        if self.audio_in_queue:
            while not self.audio_in_queue.empty():
                try: self.audio_in_queue.get_nowait()
                except Exception: break
        if self.out_queue:
            while not self.out_queue.empty():
                try: self.out_queue.get_nowait()
                except Exception: break

        _log.info("[LIVE] Connecting to Gemini Live API...")
        client = genai.Client(api_key=self.api_key)

        self.audio_in_queue = asyncio.Queue(maxsize=100)   # ~4s buffer — never drop speech audio
        self.out_queue = asyncio.Queue(maxsize=20)          # Mic buffer — generous to avoid input loss
        self._audio_count = 0  # Reset chunk counter
        # Fresh tool lock per event-loop iteration
        self._tool_lock = asyncio.Lock()
        self._running = True
        self._interrupt_flag = False  # a stale flag would mute the new session's first reply

        async with client.aio.live.connect(
            model=LIVE_MODEL,
            config=self._build_config()
        ) as session:
            self.session = session
            _log.info(f"[LIVE] Connected to {LIVE_MODEL}")

            self._listen_task = asyncio.create_task(self._listen_audio())
            self._receive_task = asyncio.create_task(self._receive_audio())
            self._play_task = asyncio.create_task(self._play_audio())
            self._send_task = asyncio.create_task(self._send_realtime())

            # Trigger JARVIS startup greeting (only on first connect, not reconnects)
            if not getattr(self, '_has_greeted', False):
                self._has_greeted = True
                self.wake("startup greeting")
                boot_context = self._cached_boot_context or ""
                greeting_prompt = (
                    "You just came online. This is your first connection. "
                    "Greet sir briefly as JARVIS would — warm, time-appropriate, 1-2 sentences max. "
                    "Mention any pending tasks only if they exist. Start speaking immediately."
                )
                if boot_context.strip():
                    greeting_prompt += f"\n\nHere is the current context:\n{boot_context}"
                try:
                    await session.send_client_content(
                        turns=[{"role": "user", "parts": [{"text": greeting_prompt}]}],
                        turn_complete=True
                    )
                    _log.info("[LIVE] Startup greeting triggered")
                except Exception as e:
                    _log.warning(f"[LIVE] Greeting trigger error: {e}")

            tasks = [self._listen_task, self._receive_task, self._play_task, self._send_task]
            try:
                # When ANY loop ends (Gemini closed the stream, a send failed),
                # the session is over: cancel the rest so start() reconnects.
                # gather() waited for all four, and the mic and playback loops
                # never end on their own, so a dropped session hung forever.
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                if self._running:
                    ended = [t.get_name() for t in done]
                    _log.info(f"[LIVE] Session ended ({', '.join(ended)}); reconnecting")
            except asyncio.CancelledError:
                self._running = False
            finally:
                self.session = None  # nothing may push text into a closed session

    def start(self):
        # Thread-safe double-start guard
        if not self._start_lock.acquire(blocking=False):
            _log.info("[LIVE] Start already in progress → skipping")
            return
        try:
            if getattr(self, "_running", False):
                _log.info("[LIVE] Already running → skipping restart")
                return
            self._running = True
        finally:
            self._start_lock.release()

        def _run_loop():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._running = True
            while self._running:
                try:
                    self._loop.run_until_complete(self.start_async())
                except Exception as e:
                    _log.warning(f"[LIVE] Engine crashed: {e}")
                    traceback.print_exc()
                if self._running:
                    _log.info("[LIVE] Reconnecting in 3 seconds...")
                    import time
                    time.sleep(3)
            self._loop.close()

        t = threading.Thread(target=_run_loop, daemon=True)
        t.start()
        return t

    def stop(self):
        self._running = False
        if self._loop:
            for task in asyncio.all_tasks(self._loop):
                task.cancel()
