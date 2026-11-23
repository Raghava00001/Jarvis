"""
JARVIS Mood Engine
==================
Extracted from websocket_server.py — emotion state machine, mood detection,
response adaptation, and text-processing utilities.

All functions are pure (no WebSocket state dependency).
"""

import re
import time
from typing import Dict, Any


# ═══════════════════════════════════════════════════════════════════════════════
# EMOTION STATE MACHINE - Proper state transitions for JARVIS mood
# ═══════════════════════════════════════════════════════════════════════════════

class EmotionState:
    """JARVIS emotion states - affects response style and HUD orb color"""
    NEUTRAL = "NEUTRAL"       # Cyan orb
    HAPPY = "HAPPY"           # Green orb
    FOCUSED = "FOCUSED"       # Bright blue orb
    CONCERNED = "CONCERNED"   # Orange orb
    FRUSTRATED = "FRUSTRATED" # Red orb
    TIRED = "TIRED"           # Dim blue orb
    ALERT = "ALERT"           # Flashing orange orb


class EmotionStateMachine:
    """Manages JARVIS emotion state transitions
    
    Inputs weighted: Face=40%, Voice=30%, Text=20%, Context=10%
    """
    
    # Transition triggers: (current_state, trigger) -> new_state
    TRANSITIONS = {
        # From NEUTRAL
        (EmotionState.NEUTRAL, "polite"): EmotionState.HAPPY,
        (EmotionState.NEUTRAL, "complex_task"): EmotionState.FOCUSED,
        (EmotionState.NEUTRAL, "repeat_command"): EmotionState.CONCERNED,
        (EmotionState.NEUTRAL, "angry_tone"): EmotionState.FRUSTRATED,
        (EmotionState.NEUTRAL, "late_night"): EmotionState.TIRED,
        (EmotionState.NEUTRAL, "urgent"): EmotionState.ALERT,
        # From HAPPY
        (EmotionState.HAPPY, "task_complete"): EmotionState.NEUTRAL,
        (EmotionState.HAPPY, "error"): EmotionState.CONCERNED,
        (EmotionState.HAPPY, "angry_tone"): EmotionState.CONCERNED,
        # From FOCUSED
        (EmotionState.FOCUSED, "task_complete"): EmotionState.NEUTRAL,
        (EmotionState.FOCUSED, "task_success"): EmotionState.HAPPY,
        (EmotionState.FOCUSED, "error"): EmotionState.CONCERNED,
        # From CONCERNED
        (EmotionState.CONCERNED, "resolved"): EmotionState.NEUTRAL,
        (EmotionState.CONCERNED, "angry_tone"): EmotionState.FRUSTRATED,
        (EmotionState.CONCERNED, "task_success"): EmotionState.HAPPY,
        # From FRUSTRATED
        (EmotionState.FRUSTRATED, "calm_down"): EmotionState.NEUTRAL,
        (EmotionState.FRUSTRATED, "repeat_angry"): EmotionState.ALERT,
        (EmotionState.FRUSTRATED, "resolved"): EmotionState.CONCERNED,
        # From TIRED
        (EmotionState.TIRED, "morning"): EmotionState.NEUTRAL,
        (EmotionState.TIRED, "urgent"): EmotionState.ALERT,
        # From ALERT
        (EmotionState.ALERT, "resolved"): EmotionState.NEUTRAL,
        (EmotionState.ALERT, "calm_down"): EmotionState.CONCERNED,
    }
    
    # Orb colors for HUD
    ORB_COLORS = {
        EmotionState.NEUTRAL: "cyan",
        EmotionState.HAPPY: "green",
        EmotionState.FOCUSED: "bright-blue",
        EmotionState.CONCERNED: "orange",
        EmotionState.FRUSTRATED: "red",
        EmotionState.TIRED: "dim-blue",
        EmotionState.ALERT: "flashing-orange",
    }
    
    def __init__(self):
        self.state = EmotionState.NEUTRAL
        self.state_history = []
        self.last_transition_time = time.time()
        
    def transition(self, trigger: str) -> str:
        """Attempt state transition based on trigger"""
        key = (self.state, trigger)
        if key in self.TRANSITIONS:
            old_state = self.state
            self.state = self.TRANSITIONS[key]
            self.state_history.append((old_state, trigger, self.state))
            self.last_transition_time = time.time()
        return self.state
    
    def compute_from_inputs(self, face_emotion: str = None, text_sentiment: str = None,
                            context: str = None) -> str:
        """Compute emotion state from multimodal inputs"""
        trigger = None
        
        # Face emotion (40% weight)
        if face_emotion:
            f = face_emotion.lower()
            if f in ("angry", "frustrated"): trigger = "angry_tone"
            elif f == "happy": trigger = "polite"
        
        # Text sentiment (20% weight)
        if text_sentiment:
            s = text_sentiment.lower()
            if "angry" in s or "frustrated" in s: trigger = "angry_tone"
            elif "thanks" in s or "great" in s: trigger = "polite"
            elif "urgent" in s: trigger = "urgent"
        
        # Context - time of day (10% weight)
        if context == "check_time":
            import datetime
            hour = datetime.datetime.now().hour
            if 23 <= hour or hour < 5: trigger = trigger or "late_night"
            elif 5 <= hour < 8: trigger = trigger or "morning"
        
        if trigger:
            self.transition(trigger)
        return self.state
    
    def get_orb_color(self) -> str:
        return self.ORB_COLORS.get(self.state, "cyan")
    
    def get_response_style(self) -> Dict[str, Any]:
        """JARVIS response style based on emotion"""
        return {
            EmotionState.NEUTRAL: {"tone": "professional", "sarcasm": 0.3, "speed": 1.0},
            EmotionState.HAPPY: {"tone": "witty", "sarcasm": 0.5, "speed": 1.1},
            EmotionState.FOCUSED: {"tone": "precise", "sarcasm": 0.0, "speed": 1.0},
            EmotionState.CONCERNED: {"tone": "gentle", "sarcasm": 0.0, "speed": 0.9},
            EmotionState.FRUSTRATED: {"tone": "calm", "sarcasm": 0.0, "speed": 0.8},
            EmotionState.TIRED: {"tone": "brief", "sarcasm": 0.1, "speed": 0.85},
            EmotionState.ALERT: {"tone": "urgent", "sarcasm": 0.0, "speed": 1.2},
        }.get(self.state, {"tone": "professional", "sarcasm": 0.3, "speed": 1.0})
    
    def trigger(self, trigger_name: str) -> str:
        """Alias for transition() - trigger a state change"""
        return self.transition(trigger_name)
    
    def reset(self):
        """Reset to neutral state"""
        self.state = EmotionState.NEUTRAL
        self.state_history = []
        self.last_transition_time = time.time()


# ═══════════════════════════════════════════════════════════════════════════════
# MOOD DETECTION — from what the user says (and their face, if a face model is
# installed and the emotion switch is on)
#
# The old detector matched words as substrings and ran on every message, so
# "know" or "now" meant rushed, "why", "again" and "class" ("ass") meant angry,
# and "what" meant confused. A "rushed" mood then cut the answer to its first
# sentence: "tell me the latest news" ("late") or "do you know..." got a
# one-sentence reply. The mood also never reached the AI, so replies never
# adapted. Now: whole-word phrases only, moods last a few minutes, the AI is
# told the mood, and answers are never cut.
# ═══════════════════════════════════════════════════════════════════════════════

_I = r"(?:i'?m|i am|im|i feel|i'?m feeling|feeling)"
_INTENS = r"(?:\s+(?:so|really|very|a bit|kind of|kinda|pretty|super|too))*"

MOOD_PATTERNS = {
    'angry': re.compile(
        r"\b(?:annoying|annoyed|frustrat\w*|irritat\w*|damn(?:it)?|ugh+|stupid|ridiculous|wtf|"
        r"what the (?:hell|heck|fuck)|f+u+c+k\w*|shit\w*|bullshit|crap|pissed(?: off)?|useless|"
        r"dumb|idiot\w*|i hate (?:this|it|you)|(?:still|again) not working|not working again|"
        r"(?:still|keeps?) (?:broken|crashing|failing)|for god'?s sake|are you (?:kidding|serious))\b", re.I),
    'sad': re.compile(
        rf"\b{_I}{_INTENS}\s+(?:sad|upset|depressed|down|unhappy|miserable|lonely|low|heartbroken)\b|"
        r"\b(?:bad|terrible|awful|rough) day\b|\bi miss (?:her|him|them|my|you|home)\b|\bi(?:'m| am) crying\b", re.I),
    'tired': re.compile(
        rf"\b{_I}{_INTENS}\s+(?:tired|exhausted|sleepy|drained|worn out|burnt out|burned out)\b|"
        r"\blong day\b|\bneed (?:some )?(?:rest|sleep)\b|\bcan'?t keep my eyes open\b", re.I),
    'rushed': re.compile(
        r"\b(?:hurry(?: up)?|asap|urgent(?:ly)?|be quick|quickly|right now|in a (?:hurry|rush)|"
        r"i(?:'m| am) (?:running )?late|(?:no|don'?t have) time)\b", re.I),
    'confused': re.compile(
        r"\b(?:i(?:'m| am) (?:so |really )?(?:confused|lost)|i don'?t (?:understand|get it)|"
        r"makes no sense|doesn'?t make sense|what do you mean)\b", re.I),
    'happy': re.compile(
        r"\b(?:awesome|amazing|fantastic|wonderful|brilliant|yay|woo+hoo+|"
        rf"{_I}{_INTENS}\s+(?:happy|excited|glad|great)|great job|well done|love it|"
        r"you'?re (?:the best|awesome|amazing)|thank you so much|i got the job|i passed)\b", re.I),
}
# On a tie, the mood that most needs care wins
MOOD_PRIORITY = ('angry', 'sad', 'tired', 'rushed', 'confused', 'happy')
# How long a mood lasts after the last sign of it (seconds)
MOOD_HOLD_S = {'sad': 900, 'tired': 900, 'angry': 240, 'rushed': 240, 'confused': 180, 'happy': 240}


def text_mood(text: str) -> str:
    """The mood the words show, or 'neutral'. Whole phrases, not substrings."""
    t = (text or "").lower().replace("’", "'")
    best, best_n = 'neutral', 0
    for mood in MOOD_PRIORITY:
        n = len(MOOD_PATTERNS[mood].findall(t))
        if n > best_n:
            best, best_n = mood, n
    return best


def _face_model_available(emotion_detector) -> bool:
    fa = getattr(emotion_detector, 'face_analyzer', None)
    return bool(fa and (getattr(fa, 'deepface_available', False) or getattr(fa, 'fer_available', False)))


def _face_mood(emotion_detector) -> str:
    """Mood from the face, only if a face model is installed (no camera otherwise)."""
    if not _face_model_available(emotion_detector):
        return 'neutral'
    try:
        from jarvis.core.shared_camera import get_shared_camera
        cam = get_shared_camera()
        cam.register("emotion")
        frame = cam.get_frame()
        if frame is None:
            return 'neutral'
        state = emotion_detector.face_analyzer.analyze(frame)
        mood = getattr(state, 'value', None) or 'neutral'
        return mood if mood in MOOD_HOLD_S else 'neutral'
    except Exception as e:
        print(f"[MoodEngine] Face mood error: {e}")
        return 'neutral'


def detect_mood_from_text(text: str, emotion_enabled: bool = False,
                          emotion_detector=None) -> str:
    """'neutral', 'angry', 'rushed', 'tired', 'happy', 'sad' or 'confused'.

    Words win; the face is only consulted when the words show nothing, the
    emotion switch is on and a face model (DeepFace/FER) is installed.
    """
    mood = text_mood(text)
    if mood == 'neutral' and emotion_enabled and emotion_detector is not None:
        mood = _face_mood(emotion_detector)
    return mood


class MoodTracker:
    """The user's current mood: set by a clear sign, fades back to neutral.

    One "ugh" shouldn't make JARVIS terse for the rest of the day, and one
    neutral command right after "I'm exhausted" shouldn't forget it either.
    """

    def __init__(self):
        self.mood = 'neutral'
        self.since = 0.0

    def observe(self, detected: str, now: float = None) -> str:
        now = time.time() if now is None else now
        if detected and detected != 'neutral':
            self.mood, self.since = detected, now
        elif self.mood != 'neutral' and now - self.since > MOOD_HOLD_S.get(self.mood, 180):
            self.mood = 'neutral'
        return self.mood


# ═══════════════════════════════════════════════════════════════════════════════
# RESPONSE ADAPTATION — the AI is told the mood (personality prompt); here only
# the voice changes. Text is never cut or padded.
# ═══════════════════════════════════════════════════════════════════════════════

MOOD_SPEECH = {
    'angry': (185, 0.85),     # calm, efficient
    'rushed': (200, 0.9),     # brisk
    'tired': (160, 0.75),     # soft
    'sad': (160, 0.75),       # gentle
    'happy': (180, 0.95),
    'confused': (165, 0.9),   # clear
}


def _apply_speech_style(target, mood: str):
    if target is None or not hasattr(target, 'speech_rate'):
        return
    if not hasattr(target, '_base_speech'):
        target._base_speech = (target.speech_rate, getattr(target, 'speech_volume', 0.9))
    rate, volume = MOOD_SPEECH.get(mood, target._base_speech)
    target.speech_rate, target.speech_volume = rate, volume


def adapt_response_to_mood(response: str, mood: str, title: str = "sir",
                           perception=None, hud_perception=None,
                           jarvis=None) -> str:
    """Set the voice for the user's mood; the response text is returned unchanged.

    The old version cut "rushed" answers to their first sentence and never
    restored the voice after a mood passed.
    """
    for target in (perception, hud_perception, getattr(jarvis, 'perception', None)):
        _apply_speech_style(target, mood)
    return response


# ═══════════════════════════════════════════════════════════════════════════════
# TEXT UTILITIES — sir reduction, action inference
# ═══════════════════════════════════════════════════════════════════════════════

# Counter for sir usage — shared across all responses
_sir_counter = 0


def reduce_sir_usage(response: str, title: str = "sir") -> str:
    """Remove excess 'sir'/'mam' from responses.
    
    JARVIS says sir/mam in almost every response — irritating.
    This keeps it to roughly every 3rd response for natural feel.
    """
    global _sir_counter
    
    # Count occurrences of title in this response
    pattern = re.compile(rf'\b{title}\b', re.IGNORECASE)
    matches = list(pattern.finditer(response))
    
    if not matches:
        return response
    
    # Increment global counter
    _sir_counter += 1
    
    # Keep title only every 3rd response
    if _sir_counter % 3 != 0:
        # Strip all occurrences of ", sir" / ", mam" / " sir." etc
        result = response
        # Remove patterns like ", sir." / ", sir," / ", sir!" / " sir."
        result = re.sub(rf',?\s*{title}\.', '.', result, flags=re.IGNORECASE)
        result = re.sub(rf',?\s*{title},', ',', result, flags=re.IGNORECASE)
        result = re.sub(rf',?\s*{title}!', '!', result, flags=re.IGNORECASE)
        result = re.sub(rf',?\s*{title}\s*$', '', result, flags=re.IGNORECASE)
        # Leading "Sir, " at start
        result = re.sub(rf'^{title},?\s+', '', result, flags=re.IGNORECASE)
        # Clean up double spaces/punctuation
        result = re.sub(r'\s{2,}', ' ', result).strip()
        result = re.sub(r'\.\s*\.', '.', result)
        if result:
            return result
    
    # On the 3rd response, keep exactly one sir (the last one)
    if len(matches) > 1:
        # Keep only the last match
        result = response
        for m in reversed(matches[:-1]):
            # Remove this occurrence
            before = result[:m.start()]
            after = result[m.end():]
            # Clean up surrounding punctuation
            before = before.rstrip(', ')
            after = after.lstrip(', ')
            result = before + ' ' + after
        result = re.sub(r'\s{2,}', ' ', result).strip()
        return result
    
    return response


def infer_action_from_text(text: str) -> str:
    """Infer action/intent from user input text - maps to result.action
    
    This provides a quick intent classification for the result type.
    More sophisticated intent recognition should be in JARVISUltimate.
    """
    t = text.lower()
    
    # Music actions
    if any(w in t for w in ['play music', 'play song', 'play my', 'next track', 'previous track']):
        return 'play_music'
    if any(w in t for w in ['shutdown', 'shut down', 'shut yourself', 'power off', 'go offline', 'exit jarvis', 'quit jarvis']):
        return 'shutdown'
    if any(w in t for w in ['story', 'bedtime', 'tell me a tale', 'once upon']):
        return 'general_ai'
    if any(w in t for w in ['next', 'skip']):
        return 'next_track'
    if any(w in t for w in ['previous', 'back', 'last']):
        return 'previous_track'
    if any(w in t for w in ['pause', 'stop music', 'stop playing']):
        return 'pause_music'
    if any(w in t for w in ['volume up', 'louder', 'increase volume']):
        return 'volume_up'
    if any(w in t for w in ['volume down', 'quieter', 'decrease volume']):
        return 'volume_down'
    
    # System actions
    if any(w in t for w in ['open', 'launch', 'start']):
        return 'open_app'
    if 'screenshot' in t or 'capture' in t:
        return 'screenshot'
    if 'time' in t and 'what' in t:
        return 'get_time'
    if 'weather' in t:
        return 'get_weather'
    if 'news' in t or 'headlines' in t:
        return 'get_news'
    
    # Communication
    if 'message' in t or 'whatsapp' in t or 'text' in t:
        return 'send_message'
    if 'email' in t or 'mail' in t:
        return 'check_email'
    if 'calendar' in t or 'schedule' in t or 'meeting' in t:
        return 'calendar'
    
    # Tasks/Reminders
    if any(w in t for w in ['remind', 'reminder', 'alarm']):
        return 'set_reminder'
    if any(w in t for w in ['task', 'todo', 'to do']):
        return 'manage_task'
    
    # General
    if any(w in t for w in ['hello', 'hi', 'hey', 'good morning', 'good evening', 'good night']):
        return 'greeting'
    if any(w in t for w in ['thank', 'thanks']):
        return 'gratitude'
    
    return 'general_query'
