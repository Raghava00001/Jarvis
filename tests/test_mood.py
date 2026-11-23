"""
Emotion-aware replies.

The old mood detector matched words as substrings on every message: "know" and
"now" meant rushed, "why", "again" and "class" meant angry, "what" meant
confused. A rushed mood then cut the answer to its first sentence, so "tell me
the latest news" got one sentence. The detected mood never reached the AI
either: nothing set perception.current_mood, which the knowledge layer reads.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.mark.parametrize("text", [
    "tell me the latest news", "do you know who won the match", "what is this",
    "why is the sky blue", "play it again", "open my class notes", "translate this",
    "what's for breakfast", "shut down the pc", "download the file", "quick question about python",
    "calculate 5 times 7", "assistant open chrome", "yes", "is it cool outside", "what's the mission",
    "turn the volume down", "how fast is light",
])
def test_ordinary_requests_have_no_mood(text):
    from jarvis.gui.mood_engine import text_mood
    assert text_mood(text) == "neutral"


@pytest.mark.parametrize("text,mood", [
    ("ugh this is so annoying", "angry"),
    ("it's still not working, this is useless", "angry"),
    ("i'm really tired today", "tired"),
    ("long day at work", "tired"),
    ("i'm feeling a bit down", "sad"),
    ("i had a terrible day", "sad"),
    ("hurry up, I'm running late", "rushed"),
    ("i don't understand what that means", "confused"),
    ("i got the job!", "happy"),
    ("that's awesome, thank you so much", "happy"),
    ("I’m exhausted", "tired"),      # curly apostrophe from the speech engine
])
def test_clear_signs_of_mood(text, mood):
    from jarvis.gui.mood_engine import text_mood
    assert text_mood(text) == mood


def test_care_wins_a_tie():
    from jarvis.gui.mood_engine import text_mood
    assert text_mood("awesome, but i'm so tired") == "tired"


def test_mood_lasts_then_fades():
    from jarvis.gui.mood_engine import MoodTracker, MOOD_HOLD_S
    tr = MoodTracker()
    assert tr.observe("tired", now=0) == "tired"
    assert tr.observe("neutral", now=60) == "tired"        # one neutral command doesn't forget it
    assert tr.observe("neutral", now=MOOD_HOLD_S["tired"] + 1) == "neutral"
    assert tr.observe("angry", now=2000) == "angry"
    assert tr.observe("happy", now=2001) == "happy"        # a new clear sign replaces it


def test_answers_are_never_cut():
    from jarvis.gui.mood_engine import adapt_response_to_mood
    long = "Here is the news. Story one. Story two. Story three."
    assert adapt_response_to_mood(long, "rushed") == long


def test_voice_returns_to_normal_after_the_mood():
    from jarvis.gui.mood_engine import adapt_response_to_mood
    hud = SimpleNamespace(speech_rate=175, speech_volume=0.9)
    adapt_response_to_mood("ok", "tired", hud_perception=hud)
    assert hud.speech_rate < 175
    adapt_response_to_mood("ok", "neutral", hud_perception=hud)
    assert (hud.speech_rate, hud.speech_volume) == (175, 0.9)


def test_no_camera_without_a_face_model():
    """The old code opened the camera for every message, though no face model is installed."""
    from jarvis.gui import mood_engine
    detector = SimpleNamespace(face_analyzer=SimpleNamespace(deepface_available=False, fer_available=False))
    with pytest.MonkeyPatch.context() as mp:
        cam = MagicMock()
        mp.setattr("jarvis.core.shared_camera.get_shared_camera", lambda: cam)
        assert mood_engine.detect_mood_from_text("open chrome", True, detector) == "neutral"
    cam.register.assert_not_called()


# ─── the AI is told the mood ───────────────────────────────────────────────

def _server():
    import jarvis.gui.websocket_server as ws
    srv = object.__new__(ws.JARVISWebSocketServer)
    srv.hud_perception = SimpleNamespace(user_title="sir", current_mood=None)
    srv.state_manager = MagicMock()
    srv.emotion_enabled = True
    srv._emotion_detector = None
    srv.jarvis = None
    type(srv).emotion_detector = property(lambda self: None)
    return srv


@pytest.fixture
def server():
    srv = _server()
    yield srv
    del type(srv).emotion_detector


def test_mood_reaches_the_ai_prompt(server):
    assert server._update_mood("i'm so tired") == "tired"
    assert server.hud_perception.current_mood == "tired"
    server.state_manager.update_mood.assert_called_once_with("tired", 0.7)
    server._update_mood("open chrome")
    assert server.hud_perception.current_mood == "tired"   # still within the hold time


def test_emotion_switch_off_means_no_mood(server):
    server._update_mood("i'm so tired")
    server.emotion_enabled = False
    assert server._update_mood("ugh this is annoying") == "neutral"
    assert server.hud_perception.current_mood is None


@pytest.mark.parametrize("mood,phrase", [
    ("tired", "fatigued"), ("sad", "feeling down"), ("angry", "frustrated"),
    ("rushed", "in a hurry"), ("confused", "User is confused"),
])
def test_personality_prompt_mentions_the_mood(mood, phrase):
    from jarvis.core.personality import get_personality
    core = get_personality()
    assert phrase in core.get_personality_prompt(mood)
    assert "CURRENT MOOD" not in core.get_personality_prompt(None)


def test_the_ai_receives_the_mood():
    """knowledge built the personality with the wrong argument, crashed silently
    and fell back to a prompt with no mood in it."""
    from jarvis.core.knowledge import KnowledgeLayer
    kl = object.__new__(KnowledgeLayer)
    kl.perception = SimpleNamespace(user_title="sir", current_mood="tired")
    kl.enabled = True
    kl.creator_info = {"nickname": "Raghava", "full_name": ""}
    seen = {}

    def fake_generate(system_prompt, user_prompt):
        seen["system"] = system_prompt
        return "Rest well."

    kl._generate_response = fake_generate
    kl.answer_question("should I keep working tonight")
    assert "User is fatigued" in seen["system"]
