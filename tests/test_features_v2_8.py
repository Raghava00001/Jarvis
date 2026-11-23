"""
v2.8 understanding and feature fixes. Each test pins a bug that existed before:

  * substring matching: "explain the history of Rome" -> a children's story
  * "news about diabetes" -> general headlines (topic lost)
  * "switch to the next tab" -> tried to open an app called "the next tab";
    tab keys went to the HUD when the command was typed there
  * "what is this" -> the AI was asked about the word "this"
  * timers: AlarmSystem.set_timer() didn't exist, yet JARVIS said "Timer set"
  * stories cut at 400 characters and the topic ignored
  * WhatsApp contact parsed as "message to mom"
  * rejected API keys retried on every question
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ─── Keyword classifier ────────────────────────────────────────────────────

@pytest.mark.parametrize("text,intent", [
    ("explain the history of the roman empire", "conversation"),   # not 'story'
    ("sometimes i forget things", "conversation"),                 # not 'time'
    ("they said hello", "conversation"),                           # not 'greeting'
    ("what is democracy", "conversation"),                         # not 'ocr'
    ("how do i copy a file in linux", "conversation"),             # not Ctrl+C
    ("hello jarvis whats the weather in london", "weather"),
    ("good morning jarvis", "greeting"),
    ("what is this", "screen_question"),
    ("what does this error mean", "screen_question"),
    ("whats on my screen", "screen_question"),
    ("translate this to hindi", "screen_question"),
    ("translate hello to spanish", "conversation"),
    ("what happened this week", "conversation"),
    ("read the screen", "ocr"),
    ("news about diabetes", "search_news"),
    ("what is the latest on diabetes", "search_news"),
    ("show me the headlines", "news"),
    ("switch to the next tab", "screen_control"),
    ("go to previous tab", "screen_control"),
    ("close this tab", "screen_control"),
    ("switch to chrome", "open_app"),
    ("set a timer for 90 seconds", "set_timer"),
    ("copy that", "screen_control"),
    ("tell me a long scary story about a lighthouse", "story"),
    ("list my reminders", "list_reminders"),
])
def test_classifier(text, intent):
    from jarvis.core.intent_classifier import classify_intent
    assert classify_intent(text)[0] == intent


def test_whole_word_matching():
    from jarvis.core.intent_classifier import has
    assert has("tell me a story", "story")
    assert not has("explain the history", "story")
    assert has("list my reminders", "reminder")      # plural allowed
    assert has("thanks a lot", "thank")
    assert not has("they left", "hey")


def test_news_topic_and_category():
    from jarvis.core.intent_classifier import classify_intent, news_topic
    assert classify_intent("news about diabetes")[1] == {"keyword": "diabetes"}
    assert news_topic("tell me the latest news about the indian economy") == "indian economy"
    assert news_topic("any updates on nvidia today") == "nvidia"
    assert news_topic("what's happening with the stock market") == "stock market"
    assert news_topic("tell me the news") is None
    assert classify_intent("show me the headlines")[1] == {}  # was Hacker News 'show'


@pytest.mark.parametrize("text,contact,message", [
    ("send whatsapp message to mom saying hi", "mom", "hi"),
    ("text dad that i will be late", "dad", "i will be late"),
    ("message hena on whatsapp saying good morning", "hena", "good morning"),
    ("open whatsapp and text priya saying hello there", "priya", "hello there"),
    ("send a message to rahul: meeting at 5", "rahul", "meeting at 5"),
    ("send whatsapp to my brother with message call me", "brother", "call me"),
])
def test_whatsapp_contact_and_message(text, contact, message):
    from jarvis.core.intent_classifier import classify_intent
    intent, entities = classify_intent(text)
    assert intent == "send_message"
    assert entities == {"contact": contact, "message": message}


# ─── Timers and alarms: never claim success that didn't happen ────────────

def test_parse_duration():
    from jarvis.core.intent_classifier import parse_duration
    assert parse_duration("set a timer for 90 seconds") == (90, "seconds")
    assert parse_duration("timer 10 min") == (10, "minutes")
    assert parse_duration("2 hours timer") == (2, "hours")
    assert parse_duration("set a timer") is None


def test_timer_is_really_set():
    from jarvis.core.intent_handlers import handle_set_timer
    alarms = MagicMock()
    alarms.set_alarm.return_value = True
    res = handle_set_timer("set a timer for 90 seconds", {}, {"alarm_system": alarms, "title": "sir"})
    assert res.success and "90 seconds" in res.response
    alarms.set_alarm.assert_called_once()
    assert alarms.set_alarm.call_args[0][0] == "in 90 seconds"


def test_timer_failures_are_reported():
    from jarvis.core.intent_handlers import handle_set_timer
    assert not handle_set_timer("set a timer for 5 minutes", {}, {"title": "sir"}).success  # no alarm system
    alarms = MagicMock()
    alarms.set_alarm.return_value = False
    assert not handle_set_timer("set a timer for 5 minutes", {}, {"alarm_system": alarms}).success
    res = handle_set_timer("set a timer", {}, {"alarm_system": alarms})
    assert not res.success and "how long" in res.response.lower()


def test_alarm_system_understands_timer_durations():
    from jarvis.core.alarm_system import AlarmSystem
    import datetime
    sys_ = object.__new__(AlarmSystem)
    for text, seconds in (("in 90 seconds", 90), ("in 5 minutes", 300), ("in 2 hours", 7200)):
        when = AlarmSystem._parse_time(sys_, text)
        delta = (when - datetime.datetime.now()).total_seconds()
        assert abs(delta - seconds) < 5, text


def test_alarm_handler_is_honest():
    from jarvis.core.intent_handlers import handle_set_alarm
    assert not handle_set_alarm("", {"hour": 7}, {"title": "sir"}).success
    alarms = MagicMock()
    alarms.set_alarm.return_value = False
    assert not handle_set_alarm("", {"hour": 7}, {"alarm_system": alarms}).success


# ─── Tabs and focus ────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,keys", [
    ("switch to the next tab", ("ctrl", "tab")),
    ("go to previous tab", ("ctrl", "shift", "tab")),
    ("tab 3", ("ctrl", "3")),
    ("go to the second tab", ("ctrl", "2")),
    ("close this tab", ("ctrl", "w")),
    ("reopen the closed tab", ("ctrl", "shift", "t")),
])
def test_tab_commands(text, keys):
    import pyautogui
    from jarvis.core import screen_control
    from jarvis.core.intent_handlers import handle_screen_control
    with patch.object(pyautogui, "hotkey") as hotkey, \
         patch.object(screen_control, "focus_away_from_jarvis", return_value=None):
        res = handle_screen_control(text, {}, {"title": "sir"})
    assert res.success
    hotkey.assert_called_once_with(*keys)


def test_keyboard_actions_first_move_focus_off_the_hud():
    import pyautogui
    from jarvis.core import screen_control
    order = []
    with patch.object(pyautogui, "hotkey", side_effect=lambda *k: order.append("keys")), \
         patch.object(screen_control, "focus_away_from_jarvis",
                      side_effect=lambda: order.append("focus") or "Chrome"):
        screen_control.ScreenControlHandler().handle("next tab")
    assert order == ["focus", "keys"]


def test_mouse_actions_leave_focus_alone():
    import pyautogui
    from jarvis.core import screen_control
    with patch.object(pyautogui, "scroll"), \
         patch.object(screen_control, "focus_away_from_jarvis") as focus:
        screen_control.ScreenControlHandler().handle("scroll down")
    focus.assert_not_called()


@pytest.mark.parametrize("title,is_jarvis", [
    ("J.A.R.V.I.S. HUD - Google Chrome", True),
    ("JARVIS HUD", True),
    ("FRIDAY HUD", True),
    ("Inbox - Gmail - Google Chrome", False),
    ("jarvis_ultimate.py - Visual Studio Code", False),
])
def test_jarvis_window_detection(title, is_jarvis):
    from jarvis.core.screen_control import is_jarvis_window
    assert is_jarvis_window(title) is is_jarvis


def test_copyright_is_not_copy():
    from jarvis.core.screen_control import ScreenControlHandler
    assert ScreenControlHandler()._keyboard_action("check the copyright", "check the copyright") is None


# ─── Screen questions ("what is this") ─────────────────────────────────────

def test_screen_question_looks_at_the_screen():
    from jarvis.core import screen_vision
    from jarvis.core.intent_handlers import handle_screen_question
    with patch.object(screen_vision, "vision_available", return_value=True), \
         patch.object(screen_vision, "focus_away_from_jarvis", return_value=None), \
         patch.object(screen_vision, "capture_screen_png", return_value=b"png"), \
         patch.object(screen_vision, "ask_gemini", return_value="That's a **TypeError**: x is None.") as ask:
        res = handle_screen_question("what does this error mean", {}, {"title": "sir"})
    assert res.success and res.response == "That's a TypeError: x is None."   # markdown stripped
    assert ask.call_args.kwargs["images"] == [b"png"]


def test_router_prefers_precise_rules():
    import jarvis.gui.websocket_server as ws
    assert ws._is_precise_rule("search_news", "news about diabetes")
    assert ws._is_precise_rule("screen_question", "what is this")
    assert ws._is_precise_rule("screen_control", "switch to the next tab")
    assert not ws._is_precise_rule("screen_control", "copy that")   # ambiguous words: ML decides
    assert not ws._is_precise_rule("conversation", "hello")


# ─── Topic briefings ───────────────────────────────────────────────────────

ARTICLES = [
    {"title": "New GLP-1 drug cuts diabetes risk", "source": "Reuters", "date": "20 Nov 2026", "age_days": 3},
    {"title": "WHO warns of rising diabetes in South Asia", "source": "BBC", "date": "14 Nov 2026", "age_days": 9},
]


def test_topic_briefing_uses_news_and_labels_background_figures():
    from jarvis.core.intent_handlers import handle_search_news
    news, knowledge = MagicMock(), MagicMock()
    news.search_items.return_value = ARTICLES
    knowledge.create.return_value = "In 2021 the IDF estimated... Reuters reports..."
    res = handle_search_news("news about diabetes", {"keyword": "diabetes"},
                             {"news_handler": news, "knowledge": knowledge, "title": "sir"})
    assert res.success and res.response.startswith("In 2021")
    prompt = knowledge.create.call_args[0][0]
    assert "Reuters" in prompt and "20 Nov 2026" in prompt
    assert "may be out of date" in prompt and "year it refers to" in prompt
    assert res.data["type"] == "news" and "Reuters" in res.data["items"][0]


def test_topic_briefing_without_ai_reads_headlines():
    from jarvis.core.intent_handlers import handle_search_news
    news = MagicMock()
    news.search_items.return_value = ARTICLES
    res = handle_search_news("", {"keyword": "diabetes"}, {"news_handler": news, "title": "sir"})
    assert res.success and "New GLP-1 drug cuts diabetes risk, from Reuters" in res.response


def test_news_search_items_parses_source_and_date():
    from jarvis.core.news_handler import NewsHandler
    rss = b"""<rss><channel>
      <item><title>Older story - BBC</title><source>BBC</source><pubDate>Mon, 02 Nov 2026 10:00:00 GMT</pubDate></item>
      <item><title>Newer story - Reuters</title><source>Reuters</source><pubDate>Sat, 21 Nov 2026 10:00:00 GMT</pubDate></item>
    </channel></rss>"""
    h = object.__new__(NewsHandler)
    with patch("jarvis.core.news_handler.requests.get",
               return_value=SimpleNamespace(status_code=200, content=rss)) as get:
        items = h.search_items("diabetes", count=5)
    assert "when%3A30d" in get.call_args[0][0]          # recent only
    assert [i["title"] for i in items] == ["Newer story", "Older story"]   # newest first, source stripped
    assert items[0]["source"] == "Reuters" and items[0]["date"] == "21 Nov 2026"


# ─── Stories, poems and the knowledge layer ────────────────────────────────

def test_story_request_parsing():
    from jarvis.core.intent_handlers import story_request
    assert story_request("tell me a long scary story about a lighthouse") == ("horror", "a lighthouse", "long")
    assert story_request("tell me a story") == ("bedtime", None, "medium")
    assert story_request("a quick funny story about my cat")[::2] == ("comedy", "short")


def test_story_uses_long_form_path_with_topic():
    from jarvis.core.intent_handlers import handle_story
    knowledge = MagicMock()
    knowledge.create.return_value = "Once, on a rocky cape, a lighthouse keeper... " * 20
    res = handle_story("tell me a story about a dragon", {}, {"knowledge": knowledge, "title": "sir"})
    assert res.success and len(res.response) > 400                     # not cut at 400 chars
    assert "about a dragon" in knowledge.create.call_args[0][0]
    knowledge.answer_question.assert_not_called()


def test_spoken_answers_trim_at_a_sentence_and_drop_markdown():
    from jarvis.core.knowledge import clean_for_speech, trim_spoken
    assert clean_for_speech("**Bold** and `code`\n- item\n## Head") == "Bold and code\nitem\nHead"
    long = "First sentence is here. " * 40
    out = trim_spoken(long, limit=600)
    assert len(out) <= 600 and out.endswith(".")


def _knowledge():
    from jarvis.core.knowledge import KnowledgeLayer
    k = object.__new__(KnowledgeLayer)
    k.enabled, k.groq_key, k.openrouter_key, k.gemini_key = True, "bad", "bad", None
    return k


def test_rejected_key_is_not_retried():
    k = _knowledge()
    rejected = SimpleNamespace(status_code=401, json=lambda: {})
    with patch("jarvis.core.knowledge.requests.post", return_value=rejected) as post:
        assert k._generate_response("sys", "q") is None
        assert post.call_count == 2          # Groq once, OpenRouter once
        k._generate_response("sys", "q again")
        assert post.call_count == 2          # neither is asked again
    assert k.groq_key is None and k.openrouter_key is None
