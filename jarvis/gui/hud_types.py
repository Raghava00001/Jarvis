import time
import queue
import threading
import contextvars
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Dict, Any, List, Optional


# ═══════════════════════════════════════════════════════════════
# ONE VOICE OWNER
# A command's reply must be spoken exactly once. Handlers used to call
# perception.speak() (server Edge TTS) AND return the same text, which the
# browser then spoke again; a handler that only spoke returned "", so the
# router treated it as unanswered and asked the AI too. Now, while a command
# turn is running, speak() only records text. The server turns what was
# recorded into the reply and speaks that reply once.
#
# A ContextVar (not a thread-local) is used because a turn spans the asyncio
# task that handles the message and the worker thread the router runs in
# (the server copies the context into that thread, see _run_blocking).
# ═══════════════════════════════════════════════════════════════

_turn_lines: contextvars.ContextVar[Optional[List[str]]] = contextvars.ContextVar(
    "jarvis_turn_lines", default=None)


@contextmanager
def command_turn():
    """Record speech for one command instead of playing it. Yields the line list."""
    lines: List[str] = []
    token = _turn_lines.set(lines)
    try:
        yield lines
    finally:
        _turn_lines.reset(token)


def in_command_turn() -> bool:
    return _turn_lines.get() is not None


def turn_text() -> str:
    """What handlers have said so far in the current turn ('' outside a turn)."""
    lines = _turn_lines.get()
    return " ".join(lines) if lines else ""

@dataclass
class Action:
    """Single response type for all WebSocket responses - prevents loops"""
    type: str                  # SPEAK, UPDATE_UI, UPDATE_CONTEXT, SILENT
    payload: Dict[str, Any]
    
    @staticmethod
    def speak(text: str, speak_aloud: bool = True, mood: str = "neutral") -> 'Action':
        """Create a SPEAK action - the primary response type"""
        return Action("SPEAK", {"text": text, "speak": speak_aloud, "mood": mood})
    
    @staticmethod
    def silent() -> 'Action':
        """Create a SILENT action - no response needed"""
        return Action("SILENT", {})
    
    @staticmethod
    def update_ui(ui_type: str, data: Dict[str, Any]) -> 'Action':
        """Create an UPDATE_UI action for HUD updates"""
        return Action("UPDATE_UI", {"ui_type": ui_type, **data})


class HUDPerception:
    """Custom perception layer that captures speech for HUD display"""
    
    def __init__(self, original_perception=None):
        self.original = original_perception
        # Only used when no announcer is attached (standalone/tests). Bounded:
        # nothing drained it, so it used to grow for the whole session.
        self.speech_queue = queue.Queue(maxsize=100)
        self.assistant_name = "JARVIS"
        self.user_title = "sir"
        self.is_friday = False
        # Deduplication tracking
        self.last_speech = ""
        self.last_speech_time = 0
        # Set by the server: shows + voices speech that happens outside a
        # command (alarms, reminders, hotkeys). Signature: announcer(text).
        self.announcer: Optional[Callable[[str], None]] = None

        if original_perception:
            self.attach(original_perception)

    def attach(self, original_perception):
        """Connect the underlying PerceptionLayer to THIS object.

        The server used to replace hud_perception with a new HUDPerception twice
        during boot, so subsystems created earlier kept a stale copy (persona,
        mute and Gemini Live flags then disagreed). Attach instead of replacing.
        """
        self.original = original_perception
        self.assistant_name = getattr(original_perception, 'assistant_name', 'JARVIS')
        self.user_title = getattr(original_perception, 'user_title', 'sir')
        self.is_friday = self.assistant_name.upper() == 'FRIDAY'

    def speak(self, text):
        """Route speech to its single owner (see ONE VOICE OWNER above).

        Inside a command turn: record it; the server speaks the final reply once.
        Outside one (alarm, reminder, hotkey): hand it to the announcer, which
        shows it in the HUD and voices it through whichever output owns audio.
        """
        if not text:
            return
        safe = str(text).encode('ascii', errors='replace').decode()

        lines = _turn_lines.get()
        if lines is not None:
            if text not in lines:
                lines.append(text)
            print(f"[{self.assistant_name}] (reply) {safe}")
            return

        # Prevent duplicate announcements within 2 seconds
        now = time.time()
        if text == self.last_speech and (now - self.last_speech_time) < 2.0:
            print(f"[{self.assistant_name}] (duplicate skipped) {safe[:60]}")
            return
        self.last_speech = text
        self.last_speech_time = now
        print(f"[{self.assistant_name}] {safe}")

        if self.announcer is not None:
            try:
                self.announcer(text)
                return
            except Exception as e:
                print(f"[{self.assistant_name}] Announce error: {e}")

        # No server attached (standalone/tests): queue for display and, unless
        # Gemini Live owns the audio, speak through the single voice engine.
        try:
            self.speech_queue.put_nowait(text)
        except queue.Full:
            pass
        if not getattr(self, '_gemini_live_active', False):
            self.voice_out(text)

    def voice_out(self, text: str) -> bool:
        """Play text through the one local voice engine (queued, never overlapping)."""
        try:
            if not hasattr(HUDPerception, '_voice_engine_ref'):
                from jarvis.core.voice_engine import get_voice_engine
                HUDPerception._voice_engine_ref = get_voice_engine()
            engine = HUDPerception._voice_engine_ref
            engine.set_voice("friday" if self.is_friday else "jarvis")
            engine.say(text)
            return True
        except Exception as e:
            print(f"[{self.assistant_name}] TTS error: {e}")
            return False

    def stop_speaking(self):
        """Stop local playback and drop queued lines."""
        engine = getattr(HUDPerception, '_voice_engine_ref', None)
        if engine is not None:
            engine.stop()

    @property
    def is_speaking(self) -> bool:
        engine = getattr(HUDPerception, '_voice_engine_ref', None)
        return bool(engine is not None and engine.busy)
    
    def switch_to_friday(self):
        """Switch to FRIDAY voice"""
        self.assistant_name = "FRIDAY"
        self.is_friday = True
        if self.original and hasattr(self.original, 'switch_to_friday'):
            self.original.switch_to_friday()
        self.speak("FRIDAY online. Hello, boss.")
    
    def switch_to_jarvis(self):
        """Switch to JARVIS voice"""
        self.assistant_name = "JARVIS"
        self.is_friday = False
        if self.original and hasattr(self.original, 'switch_to_jarvis'):
            self.original.switch_to_jarvis()
        self.speak("JARVIS back online, sir.")
    
    def get_pending_speech(self):
        """Get all pending speech from queue"""
        messages = []
        while not self.speech_queue.empty():
            try:
                messages.append(self.speech_queue.get_nowait())
            except:
                break
        return messages
