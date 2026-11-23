"""
JARVIS Intent Handlers
Dedicated handlers for each command type - extracted from _fallback_process
"""

from jarvis.core.services import shared
from jarvis.core.errors import recovered
from datetime import datetime
from typing import Any, Dict
import random
import re

try:
    from jarvis.core.intent_router import HandlerResult, Intent
except ImportError:
    from jarvis.core.intent_router import HandlerResult, Intent


# ═══════════════════════════════════════════════════════════════
# CORE HANDLERS
# ═══════════════════════════════════════════════════════════════

def handle_greeting(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle hello, hi, hey, good morning/afternoon/evening — Iron Man JARVIS style"""
    hour = datetime.now().hour
    title = context.get('title', 'sir') if context else 'sir'
    cmd_lower = cmd.lower() if cmd else ''
    
    # Time-based greeting
    if hour < 6:
        time_greeting = "Burning the midnight oil"
    elif hour < 12:
        time_greeting = "Good morning"
    elif hour < 17:
        time_greeting = "Good afternoon"
    elif hour < 21:
        time_greeting = "Good evening"
    else:
        time_greeting = "Rather late"
    
    # ━━━ CONTEXT-AWARE RESPONSES (Iron Man JARVIS style) ━━━
    
    # "daddy's home" / "I'm back" / "I'm here" — returning user
    if any(phrase in cmd_lower for phrase in ["daddy", "i'm back", "im back", "back online", "i'm here", "home"]):
        responses = [
            f"Welcome back, {title}. All systems were on standby, awaiting your return.",
            f"Ah, {title}. The house just wasn't the same without you. All systems online.",
            f"{time_greeting}, {title}. I've kept everything running in your absence. As usual.",
            f"Welcome home, {title}. Shall I run a status report, or is this a social visit?",
        ]
        return HandlerResult(success=True, response=random.choice(responses))
    
    # "can you hear me" — checking if JARVIS works
    if any(phrase in cmd_lower for phrase in ["hear me", "can you hear", "you there", "are you there", "awake", "alive"]):
        responses = [
            f"Loud and clear, {title}. All systems operational.",
            f"I can hear you perfectly, {title}. Voice recognition at full capacity.",
            f"For you, {title}, always. What do you need?",
            f"Present and accounted for. How may I assist?",
        ]
        return HandlerResult(success=True, response=random.choice(responses))
    
    # Late night greeting
    if hour >= 23 or hour < 5:
        responses = [
            f"Working late again, {title}? I won't lecture. Much.",
            f"{time_greeting}, {title}. I calculate you should have been asleep two hours ago.",
            f"All systems online, {title}. Though I'd recommend sleep over my company.",
        ]
        return HandlerResult(success=True, response=random.choice(responses))
    
    # Standard greetings with personality
    responses = [
        f"{time_greeting}, {title}. All systems nominal. What can I do for you?",
        f"{time_greeting}. JARVIS at your service.",
        f"At your disposal, {title}. What's on the agenda?",
        f"{time_greeting}, {title}. Ready when you are.",
        f"Online and operational. How may I assist you, {title}?",
    ]
    return HandlerResult(success=True, response=random.choice(responses))


def handle_farewell(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle goodbye, bye, see you"""
    title = context.get('title', 'sir') if context else 'sir'
    responses = [
        f"Goodbye, {title}. I'll be here when you need me.",
        f"Until next time, {title}.",
        "Take care. Systems on standby."
    ]
    return HandlerResult(success=True, response=random.choice(responses))


def handle_time(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle time queries"""
    title = context.get('title', 'sir') if context else 'sir'
    now = datetime.now()
    return HandlerResult(
        success=True,
        response=f"The current time is {now.strftime('%I:%M %p')}, {title}."
    )


def handle_date(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle date queries"""
    title = context.get('title', 'sir') if context else 'sir'
    now = datetime.now()
    return HandlerResult(
        success=True,
        response=f"Today is {now.strftime('%A, %B %d, %Y')}, {title}."
    )


def handle_identity(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle 'who are you' / 'your name'"""
    name = context.get('assistant_name', 'JARVIS') if context else 'JARVIS'
    is_friday = context.get('is_friday', False) if context else False
    
    if is_friday:
        return HandlerResult(
            success=True,
            response="I'm FRIDAY - Female Replacement Intelligent Digital Assistant Youth. Your AI assistant, boss."
        )
    return HandlerResult(
        success=True,
        response=f"I am {name} - Just A Rather Very Intelligent System. Your personal AI assistant, created by Raghava."
    )


def handle_creator(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle 'who made you' / 'who created you'"""
    title = context.get('title', 'sir') if context else 'sir'
    return HandlerResult(
        success=True,
        response=f"I was created by Raghava, {title}. A brilliant engineer who envisioned the ultimate digital assistant."
    )


def handle_help(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle 'help' / 'what can you do'"""
    title = context.get('title', 'sir') if context else 'sir'
    return HandlerResult(
        success=True,
        response=f"I can assist with many things, {title}: System monitoring, weather updates, news by category, "
                 "reminders, smart notes, alarms, opening applications, web searches, volume control, "
                 "and intelligent conversation. Voice to voice mode is active."
    )


def handle_thanks(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle 'thank you' - reduced 'sir' usage"""
    responses = [
        "You're welcome!",
        "Anytime.",
        "Happy to help.",
        "My pleasure."
    ]
    return HandlerResult(success=True, response=random.choice(responses))


def handle_how_are_you(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle 'how are you'"""
    title = context.get('title', 'sir') if context else 'sir'
    system_stats = context.get('system_stats', {}) if context else {}
    
    cpu = system_stats.get('cpu', 30)
    if cpu < 50:
        return HandlerResult(
            success=True,
            response=f"Operating at peak efficiency, {title}. All systems nominal."
        )
    return HandlerResult(
        success=True,
        response=f"Functioning well, {title}. System load is moderate but manageable."
    )


# ═══════════════════════════════════════════════════════════════
# INFORMATION HANDLERS
# ═══════════════════════════════════════════════════════════════

def handle_weather(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle weather queries - requires weather_handler in context"""
    title = context.get('title', 'sir') if context else 'sir'
    weather_handler = context.get('weather_handler') if context else None
    
    if not weather_handler:
        return HandlerResult(
            success=False,
            response=f"Weather service unavailable, {title}."
        )
    
    try:
        # Get city from entities if specified
        city = entities.get('city')
        weather = weather_handler.get_weather(city) if city else weather_handler.get_weather()
        
        if isinstance(weather, dict):
            return HandlerResult(
                success=True,
                # WeatherHandler returns city/temp_c/description/wind_speed_kmh;
                # the old keys (location/temp/condition/wind) always read N/A.
                response=f"Current conditions in {weather.get('city') or weather.get('location') or 'your area'}: "
                         f"{weather.get('temp_c', weather.get('temp', 'N/A'))}°C, "
                         f"{(weather.get('description') or weather.get('condition') or 'unknown').strip()}. "
                         f"Humidity at {weather.get('humidity', 'N/A')}%, "
                         f"wind {weather.get('wind_speed_kmh', weather.get('wind', 'N/A'))} kilometers per hour."
            )
    except Exception as e:
        print(f"[HANDLERS] Weather error: {e}")
    
    return HandlerResult(
        success=False,
        response=f"Couldn't fetch weather data, {title}."
    )


def handle_system_status(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle system status queries"""
    title = context.get('title', 'sir') if context else 'sir'
    stats = context.get('system_stats', {}) if context else {}
    
    charge = " and charging" if stats.get('charging') else ""
    return HandlerResult(
        success=True,
        response=f"All systems operational, {title}. CPU at {stats.get('cpu', 0)}%, "
                 f"memory at {stats.get('memory', 0)}%, disk at {stats.get('disk', 0)}%, "
                 f"battery at {stats.get('battery', 100)}%{charge}."
    )


# ═══════════════════════════════════════════════════════════════
# ENTERTAINMENT HANDLERS - Use Gemini AI
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
# BATCH 2 HANDLERS - News, Screenshot, Notes, Apps
# ═══════════════════════════════════════════════════════════════

def handle_news(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle news requests with category support + JARVIS opinion"""
    title = context.get('title', 'sir') if context else 'sir'
    news_handler = context.get('news_handler') if context else None
    knowledge = context.get('knowledge') if context else None
    category = entities.get('category', 'general')
    
    if not news_handler:
        return HandlerResult(success=False, response=f"News service unavailable, {title}.")
    
    try:
        news_data = news_handler.get_news(category=category, count=5)
        if isinstance(news_data, dict) and 'items' in news_data:
            items = news_data['items'][:3]
            items_text = ". ".join(items)
            
            # Generate JARVIS opinion on the headlines
            opinion = ""
            if knowledge and items:
                try:
                    opinion_prompt = f"""You are JARVIS from Iron Man. Dry wit, deadpan, sharp.
Here are today's {category} headlines: {items_text}

Give a 1-2 sentence take with signature JARVIS dry humor. Use probability framing if applicable ("There's a 73% chance this escalates"). Be bold and specific."""
                    opinion_response = knowledge.answer_question(opinion_prompt)
                    if opinion_response and len(opinion_response) > 10:
                        opinion = f" My take: {opinion_response}"
                except Exception:
                    pass  # Opinion is optional, don't fail on it
            
            return HandlerResult(
                success=True,
                response=f"Here are the top {category} headlines, {title}: {items_text}{opinion}",
                data={'type': 'news', 'items': news_data['items']}
            )
    except Exception as e:
        print(f"[HANDLERS] News error: {e}")
    
    return HandlerResult(success=False, response=f"Couldn't fetch {category} news, {title}.")


def handle_search_news(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle news search by keyword"""
    """A briefing on a topic: background and past figures, the current picture
    from recent headlines, and what to watch. ("diabetes" used to return the
    general headlines: the topic was dropped on the way to the handler.)"""
    title = context.get('title', 'sir') if context else 'sir'
    news_handler = context.get('news_handler') if context else None
    knowledge = context.get('knowledge') if context else None
    keyword = (entities.get('keyword') or '').strip()

    if not keyword:
        return HandlerResult(success=False, response=f"What topic should I look into, {title}?")
    if not news_handler:
        return HandlerResult(success=False, response=f"News service unavailable, {title}.")

    try:
        articles = news_handler.search_items(keyword, count=8)
    except Exception as e:
        print(f"[HANDLERS] News search error: {e}")
        articles = []

    panel = [f"{a['title']} ({a['source']}, {a['date']})" if a.get('source') else a['title'] for a in articles]
    data = {'type': 'news', 'items': panel, 'category': keyword} if panel else None

    briefing = None
    if knowledge and hasattr(knowledge, 'create'):
        briefing = knowledge.create(topic_briefing_prompt(keyword, articles), max_tokens=700)

    if briefing:
        return HandlerResult(success=True, response=briefing, data=data)
    if articles:
        top = ". ".join(f"{a['title']}, from {a['source']}" if a.get('source') else a['title'] for a in articles[:3])
        return HandlerResult(success=True, response=f"Latest on {keyword}: {top}.", data=data)
    return HandlerResult(success=True, response=f"I couldn't find recent news about {keyword}, {title}.")


def topic_briefing_prompt(topic: str, articles: list) -> str:
    """Prompt for a spoken briefing that keeps known facts, dated figures and
    today's news clearly apart, so nothing invented is presented as current."""
    today = datetime.now().strftime("%d %B %Y")
    if articles:
        lines = "\n".join(f"- {a['title']} | {a.get('source') or 'unknown source'} | {a.get('date') or 'date unknown'}"
                          for a in articles)
        news = f"Recent headlines (last 30 days, newest first):\n{lines}"
    else:
        news = "No recent headlines were found."
    return (
        f"Today is {today}. The user asked for the latest on: {topic}.\n\n{news}\n\n"
        "Write a spoken briefing of about 170 words in three short parts, without headings:\n"
        "1. Background and past figures: the most important statistics you know about this topic, "
        "each with the year it refers to and who published it (for example 'the IDF estimated in 2021 that...'). "
        "Say these come from your background knowledge and may be out of date. Only give figures you are "
        "confident about; if you have none, say so instead of guessing.\n"
        "2. The current picture: what the recent headlines above show, naming their sources. "
        "Use only the headlines for anything described as recent or new.\n"
        "3. One line on what to watch next.\n"
        "Plain spoken sentences: no lists, no markdown."
    )


def handle_open_app(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle opening applications"""
    import os
    import subprocess
    
    app = entities.get('app', '').lower()
    if not app:
        return HandlerResult(success=False, response="Please specify an app to open.")
    
    APP_PATHS = {
        'whatsapp': 'whatsapp:',
        'chrome': 'chrome',
        'firefox': 'firefox',
        'notepad': 'notepad',
        'calculator': 'calc',
        'paint': 'mspaint',
        'spotify': 'spotify:',
        'telegram': 'telegram:',
        'discord': 'discord:',
        'vscode': 'code',
        'vs code': 'code',
        'file explorer': 'explorer',
        'explorer': 'explorer',
        'settings': 'ms-settings:',
        'cmd': 'cmd',
        'terminal': 'wt',
        # Desktop apps - use Start Menu shortcuts for reliability
        'perplexity': rf'C:\Users\{os.getenv("USERNAME")}\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Perplexity.lnk',
        'chatgpt': 'https://chat.openai.com'
    }
    
    try:
        if app in APP_PATHS:
            target = APP_PATHS[app]
            if target.startswith('http') or target.endswith(':') or target.endswith('.lnk'):
                os.startfile(target)
            else:
                subprocess.Popen(target, shell=True)
        else:
            # Try to open directly — Windows will find it if it's in PATH or Start Menu
            from jarvis.core.safe_exec import start_app, is_safe_app_name
            if not is_safe_app_name(app):
                return HandlerResult(success=False, response=f"Couldn't open {app}.")
            start_app(app)
        return HandlerResult(success=True, response=f"Opening {app}.")
    except Exception as e:
        print(f"[HANDLERS] Open app error: {e}")
        return HandlerResult(success=False, response=f"Couldn't open {app}.")


def handle_volume(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle volume control"""
    title = context.get('title', 'sir') if context else 'sir'
    system_control = context.get('system_control') if context else None
    action = entities.get('action', '')
    level = entities.get('level')
    
    if system_control:
        try:
            if action == 'up':
                system_control.volume_up()
                return HandlerResult(success=True, response=f"Volume increased, {title}.")
            elif action == 'down':
                system_control.volume_down()
                return HandlerResult(success=True, response=f"Volume decreased, {title}.")
            elif action == 'mute':
                system_control.mute_volume()
                return HandlerResult(success=True, response=f"Audio muted, {title}.")
            elif action == 'set' and level is not None:
                system_control.set_volume(level)
                return HandlerResult(success=True, response=f"Volume set to {level}%, {title}.")
        except Exception as e:
            print(f"[HANDLERS] Volume error: {e}")
    
    # Fallback response
    return HandlerResult(success=True, response=f"Adjusting volume, {title}.")


def handle_brightness(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle brightness control"""
    title = context.get('title', 'sir') if context else 'sir'
    system_control = context.get('system_control') if context else None
    action = entities.get('action', '')
    level = entities.get('level')
    
    if system_control:
        try:
            if action == 'up':
                system_control.brightness_up()
                return HandlerResult(success=True, response=f"Brightness increased, {title}.")
            elif action == 'down':
                system_control.brightness_down()
                return HandlerResult(success=True, response=f"Brightness decreased, {title}.")
            elif action == 'set' and level is not None:
                system_control.set_brightness(level)
                return HandlerResult(success=True, response=f"Brightness set to {level}%, {title}.")
        except Exception as e:
            print(f"[HANDLERS] Brightness error: {e}")
    
    return HandlerResult(success=True, response=f"Adjusting brightness, {title}.")


# ═══════════════════════════════════════════════════════════════
# AI SEARCH HANDLERS (Perplexica/Scira-inspired)
# ═══════════════════════════════════════════════════════════════

def handle_ai_search(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle AI-powered deep search"""
    title = context.get('title', 'sir') if context else 'sir'
    ai_search = context.get('ai_search') if context else None
    query = entities.get('query', '')
    mode = entities.get('mode', 'balanced')
    source = entities.get('source', 'web')
    
    if not query:
        return HandlerResult(success=False, response=f"What would you like me to research, {title}?")
    
    try:
        if ai_search:
            if mode == 'quality':
                result = ai_search.deep_research(query)
            else:
                result = ai_search.search(query)
            
            if result.get('summary'):
                return HandlerResult(success=True, response=result['summary'])
            elif result.get('results'):
                first = result['results'][0]
                return HandlerResult(success=True, response=f"Found: {first.snippet if hasattr(first, 'snippet') else str(first)}")
        
        # Fallback to web browser
        import webbrowser
        webbrowser.open(f"https://www.google.com/search?q={query}")
        return HandlerResult(success=True, response=f"Researching {query}, {title}.")
    except Exception as e:
        print(f"[HANDLERS] AI search error: {e}")
        return HandlerResult(success=False, response=f"Search failed, {title}.")


def handle_remember(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle remembering facts (Qdrant-style memory)"""
    title = context.get('title', 'sir') if context else 'sir'
    ai_search = context.get('ai_search') if context else None
    fact = entities.get('fact', '')
    
    if not fact:
        return HandlerResult(success=False, response=f"What should I remember, {title}?")
    
    try:
        if ai_search:
            ai_search.remember(fact)
            return HandlerResult(success=True, response=f"I'll remember that, {title}.")
        
        # Fallback to file-based memory
        from pathlib import Path
        import json
        data_dir = Path(__file__).parent.parent.parent / "jarvis_data"
        data_dir.mkdir(exist_ok=True)
        memory_file = data_dir / "memory.json"
        
        memories = []
        if memory_file.exists():
            memories = json.loads(memory_file.read_text())
        memories.append({"fact": fact, "timestamp": str(__import__('datetime').datetime.now())})
        memory_file.write_text(json.dumps(memories, indent=2))
        
        return HandlerResult(success=True, response=f"Noted, {title}.")
    except Exception as e:
        print(f"[HANDLERS] Remember error: {e}")
        return HandlerResult(success=False, response=f"Couldn't save that, {title}.")


def handle_recall(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle recalling facts from memory"""
    title = context.get('title', 'sir') if context else 'sir'
    ai_search = context.get('ai_search') if context else None
    query = entities.get('query', '')
    
    try:
        if ai_search:
            facts = ai_search.recall(query)
            if facts:
                response = f"I remember: {facts[0]}"
                if len(facts) > 1:
                    response += f" And {len(facts)-1} more related facts."
                return HandlerResult(success=True, response=response)
            return HandlerResult(success=True, response=f"I don't recall anything about that, {title}.")
        
        # Fallback to file-based memory
        from pathlib import Path
        import json
        data_dir = Path(__file__).parent.parent.parent / "jarvis_data"
        memory_file = data_dir / "memory.json"
        
        if memory_file.exists():
            memories = json.loads(memory_file.read_text())
            for mem in reversed(memories):
                if query.lower() in mem['fact'].lower():
                    return HandlerResult(success=True, response=f"I remember: {mem['fact']}")
        
        return HandlerResult(success=True, response=f"I don't recall that, {title}.")
    except Exception as e:
        print(f"[HANDLERS] Recall error: {e}")
        return HandlerResult(success=True, response=f"Let me think... No, I don't remember that.")


def handle_search(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle web search"""
    import webbrowser
    title = context.get('title', 'sir') if context else 'sir'
    import re as _re
    from urllib.parse import quote_plus
    # "search for X" used to search for "for X"
    query = _re.sub(r"^(?:for|about|up|on)\s+", "", (entities.get('query') or '').strip(), flags=_re.I)

    if query:
        try:
            webbrowser.open(f"https://www.google.com/search?q={quote_plus(query)}")
            return HandlerResult(success=True, response=f"Searching for '{query}', {title}.")
        except Exception as e:
            print(f"[HANDLERS] Search error: {e}")
    
    return HandlerResult(success=False, response=f"Please specify what to search for, {title}.")


def handle_play_music(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle music playback - DIRECT, no verbose responses"""
    import os
    import time
    
    song = entities.get('song', '')
    cmd_lower = cmd.lower()
    
    # Extract song name from various patterns
    if not song:
        for pattern in ['play ', 'play song ', 'play music ']:
            if pattern in cmd_lower:
                song = cmd_lower.split(pattern)[-1].strip()
                break
    
    try:
        # Open Spotify
        os.startfile('spotify:')
        time.sleep(1)
        
        if song and len(song) > 2:
            # Search and play specific song
            import webbrowser
            search_query = song.replace(" ", "%20")
            webbrowser.open(f"spotify:search:{search_query}")
            return HandlerResult(success=True, response=f"Playing {song}")
        else:
            # Just resume/play
            try:
                import pyautogui
                time.sleep(0.5)
                pyautogui.press('space')  # Toggle play in Spotify
            except Exception as _err:
                recovered("Handlers", _err)
            return HandlerResult(success=True, response="Playing music")
    except Exception:
        return HandlerResult(success=False, response="Can't open Spotify")


def handle_pause_music(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle music pause - DIRECT"""
    try:
        import pyautogui
        pyautogui.press('space')  # Toggle play/pause
        return HandlerResult(success=True, response="Paused")
    except Exception:
        return HandlerResult(success=True, response="Paused")


def handle_next_track(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Skip to next track - DIRECT"""
    try:
        import pyautogui
        pyautogui.hotkey('ctrl', 'right')
        return HandlerResult(success=True, response="Next track")
    except Exception:
        return HandlerResult(success=True, response="Done")


def handle_previous_track(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Go to previous track - DIRECT"""
    try:
        import pyautogui
        pyautogui.hotkey('ctrl', 'left')
        return HandlerResult(success=True, response="Previous track")
    except Exception:
        return HandlerResult(success=True, response="Done")


# ═══════════════════════════════════════════════════════════════
# REMINDER HANDLERS
# ═══════════════════════════════════════════════════════════════

def handle_set_reminder(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle reminder creation - uses ReminderManager"""
    title = context.get('title', 'sir') if context else 'sir'
    reminder_manager = context.get('reminder_manager') if context else None
    
    raw_command = entities.get('raw_command', cmd)
    
    if reminder_manager:
        try:
            result = reminder_manager.parse_reminder(raw_command)
            if result:
                message, remind_at, reminder_type = result
                # Use silent=True since handler returns response (prevents double-speak)
                reminder_id = reminder_manager.add_reminder(message, remind_at, reminder_type, silent=True)
                
                # Format time for response
                time_str = remind_at.strftime("%I:%M %p")
                from datetime import timedelta
                if remind_at.date() == datetime.now().date():
                    when = f"today at {time_str}"
                elif remind_at.date() == (datetime.now() + timedelta(days=1)).date():
                    when = f"tomorrow at {time_str}"
                else:
                    when = remind_at.strftime("%B %d at %I:%M %p")
                
                return HandlerResult(
                    success=True,
                    response=f"I'll remind you to {message} {when}, {title}."
                )
            else:
                return HandlerResult(
                    success=False,
                    response=f"I couldn't understand the reminder, {title}. Try 'remind me to [task] in [time]' or 'remind me to [task] at [time]'."
                )
        except Exception as e:
            print(f"[HANDLERS] Reminder error: {e}")
    
    return HandlerResult(
        success=False,
        response=f"Reminder service unavailable, {title}."
    )


def handle_list_reminders(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle listing upcoming reminders"""
    title = context.get('title', 'sir') if context else 'sir'
    reminder_manager = context.get('reminder_manager') if context else None
    
    if reminder_manager:
        try:
            reminders = reminder_manager.get_upcoming_reminders()
            if not reminders:
                return HandlerResult(success=True, response=f"You have no upcoming reminders, {title}.")
            
            response = f"You have {len(reminders)} upcoming reminders, {title}. "
            for i, r in enumerate(reminders[:5], 1):
                time_str = r.remind_at.strftime("%I:%M %p on %B %d")
                response += f"{i}. {r.message} at {time_str}. "
            
            return HandlerResult(success=True, response=response)
        except Exception as e:
            print(f"[HANDLERS] List reminders error: {e}")
    
    return HandlerResult(success=False, response=f"Reminder service unavailable, {title}.")


# ═══════════════════════════════════════════════════════════════
# HELP HANDLERS - Explain JARVIS features to user
# ═══════════════════════════════════════════════════════════════

def handle_gesture_help(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Tell user how to use hand gestures"""
    title = context.get('title', 'sir') if context else 'sir'
    return HandlerResult(
        success=True,
        response=f"Yes {title}, I support hand gesture control. Say 'enable gestures' to start. "
                 f"Gestures: open palm for play/pause, point up for volume up, point down for volume down, "
                 f"fist to mute, swipe left/right for previous/next track."
    )


def handle_face_recognition_cmd(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle face recognition requests"""
    title = context.get('title', 'sir') if context else 'sir'
    face_auth = context.get('face_auth') if context else None
    
    if face_auth:
        try:
            # P1-09: verify_user() returns Tuple[UserProfile, float], not a dict
            profile, confidence = face_auth.verify_user()
            if confidence > 0.6 and profile.name != "Unknown":
                return HandlerResult(success=True, response=f"Face recognized. Welcome back, {profile.name}.")
            else:
                return HandlerResult(success=True, response=f"I don't recognize this face, {title}. Would you like to register?")
        except Exception as e:
            print(f"[HANDLERS] Face recognition error: {e}")
    
    return HandlerResult(
        success=True,
        response=f"Face recognition is available, {title}. Say 'enable camera' to start, then I can identify you."
    )


def handle_improvement_suggestions(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Give specific, actionable improvement suggestions"""
    title = context.get('title', 'sir') if context else 'sir'
    return HandlerResult(
        success=True,
        response=f"Here are concrete improvements you could make, {title}: "
                 f"1. Add more voice commands for specific apps. "
                 f"2. Train face recognition with your photos. "
                 f"3. Set up smart home integrations. "
                 f"4. Customize my personality in the settings panel."
    )


# ═══════════════════════════════════════════════════════════════
# ENTERTAINMENT HANDLERS - Jokes, Stories, Poems
# ═══════════════════════════════════════════════════════════════

# Singleton entertainment instance
_entertainment = None

def _get_entertainment(context):
    """Get or create entertainment instance"""
    global _entertainment
    if _entertainment is None:
        try:
            try:
                from jarvis.core.entertainment import JARVISEntertainment
            except ImportError:
                from jarvis.core.entertainment import JARVISEntertainment
            perception = context.get('perception') if context else None
            knowledge = context.get('knowledge') if context else None
            _entertainment = shared(JARVISEntertainment, lambda: JARVISEntertainment(perception, knowledge))
        except Exception as e:
            print(f"[HANDLERS] Entertainment init error: {e}")
            return None
    return _entertainment


def handle_joke(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle joke requests - uses JARVISEntertainment"""
    title = context.get('title', 'sir') if context else 'sir'
    
    entertainment = _get_entertainment(context)
    if entertainment:
        try:
            # Get a joke from entertainment module
            joke = random.choice(entertainment.jokes) if entertainment.jokes else None
            if joke:
                return HandlerResult(success=True, response=f"{joke}, {title}.")
        except Exception as _err:
            recovered("Handlers", _err)
    
    # Fallback jokes
    jokes = [
        "Why do programmers prefer dark mode? Because light attracts bugs.",
        "Why did the developer go broke? Because he used up all his cache.",
        "A SQL query walks into a bar, walks up to two tables and asks: Can I join you?"
    ]
    return HandlerResult(success=True, response=f"{random.choice(jokes)}, {title}.")


STORY_TONE = {
    "horror": "Build slow, creeping suspense; keep it eerie rather than gory.",
    "comedy": "Make it genuinely funny, with a comic twist at the end.",
    "bedtime": "Keep it gentle, calm and soothing, ending peacefully.",
    "adventure": "Keep it exciting, with vivid action and a brave choice.",
    "sci-fi": "Ground it in a fresh scientific idea with a sense of wonder.",
    "fantasy": "Make the world magical and vivid.",
    "mystery": "Plant a clue early and resolve it cleverly.",
    "romance": "Keep it warm and heartfelt.",
    "moral": "End with a clear, simple lesson.",
}


def story_request(cmd: str):
    """'tell me a long scary story about a lighthouse' -> ('horror', 'a lighthouse', 'long')."""
    c = (cmd or "").lower()
    genre = "bedtime"
    for g, words in (("horror", ("horror", "scary", "spooky", "ghost")), ("comedy", ("funny", "comedy", "hilarious")),
                     ("adventure", ("adventure", "action")), ("sci-fi", ("sci-fi", "science fiction", "space", "robot")),
                     ("fantasy", ("fantasy", "magic", "dragon", "wizard", "fairy")), ("mystery", ("mystery", "detective")),
                     ("romance", ("romance", "romantic", "love story")), ("moral", ("moral", "lesson"))):
        if any(re.search(rf"\b{re.escape(w)}\b", c) for w in words):
            genre = g
            break
    m = re.search(r"\bstor(?:y|ies)\s+(?:about|of|on|where|in which|featuring)\s+(.+?)[?.!]*$", c)
    topic = m.group(1).strip() if m else None
    length = "long" if re.search(r"\b(long|longer|detailed|full)\b", c) else (
        "short" if re.search(r"\b(short|quick|tiny|brief)\b", c) else "medium")
    return genre, topic, length


def handle_story(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle story requests - uses JARVISEntertainment or AI"""
    title = context.get('title', 'sir') if context else 'sir'
    genre, topic, length = story_request(cmd)

    # Long-form path: the quick-answer path (answer_question) used a 2-3
    # sentence persona and cut replies at 400 characters, so stories stopped
    # mid-sentence, and the topic ("a story about a dragon") was ignored.
    knowledge = context.get('knowledge') if context else None
    if knowledge:
        about = f" about {topic}" if topic else ""
        paragraphs = {"short": "two short paragraphs", "long": "six to eight paragraphs"}.get(length, "four paragraphs")
        prompt = (f"Tell an original {genre} story{about}, in {paragraphs}. "
                  f"Give it a clear beginning, a turn, and a satisfying ending. "
                  f"{STORY_TONE.get(genre, '')} "
                  f"Start straight away with the story, with no title or preamble.")
        try:
            if hasattr(knowledge, 'create'):
                story = knowledge.create(prompt, max_tokens=1400 if length == "long" else 900)
            else:
                story = knowledge.answer_question(prompt)
            if story and len(story) > 80:
                return HandlerResult(success=True, response=story)
        except Exception as e:
            print(f"[HANDLERS] Story generation error: {e}")

    # Fallback story
    if genre == "horror":
        return HandlerResult(
            success=True,
            response=f"Here's a quick tale, {title}. In an old mansion, a programmer heard typing from an empty room. "
                     f"When he checked, he found code writing itself - his own obituary in Python. "
                     f"The last line read: 'print(\"You should not have read this\")'"
        )
    
    return HandlerResult(
        success=True,
        response=f"Once upon a time, {title}, there was a brilliant AI named JARVIS who helped his user accomplish "
                 f"amazing things. Together they solved problems, built systems, and made the impossible possible. "
                 f"The end - but our story is just beginning."
    )


def handle_poem(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle poem requests"""
    title = context.get('title', 'sir') if context else 'sir'
    
    # Try AI generation
    knowledge = context.get('knowledge') if context else None
    if knowledge:
        try:
            m = re.search(r"\bpoem\s+(?:about|on|for|of)\s+(.+?)[?.!]*$", (cmd or "").lower())
            theme = entities.get('theme') or (m.group(1) if m else 'technology and friendship')
            prompt = (f"Write an original short poem (8 lines) about {theme}. Make it thoughtful "
                      f"and musical when read aloud. Output only the poem.")
            poem = knowledge.create(prompt, max_tokens=400) if hasattr(knowledge, 'create') \
                else knowledge.answer_question(prompt)
            if poem:
                return HandlerResult(success=True, response=poem)
        except Exception as e:
            print(f"[HANDLERS] Poem generation error: {e}")
    
    # Fallback poem
    return HandlerResult(
        success=True,
        response=f"Circuits hum and data flows, {title}. "
                 f"Through the night my service goes. "
                 f"Your commands I always heed, "
                 f"JARVIS here for every need."
    )


# ═══════════════════════════════════════════════════════════════
# ALARM & TIMER HANDLERS
# ═══════════════════════════════════════════════════════════════

def handle_set_alarm(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle setting alarms"""
    title = context.get('title', 'sir') if context else 'sir'
    alarm_system = context.get('alarm_system') if context else None
    
    hour = entities.get('hour', 0)
    minute = entities.get('minute', 0)
    period = entities.get('period', '')
    
    # Convert to 24h
    if period == 'pm' and hour != 12:
        hour += 12
    elif period == 'am' and hour == 12:
        hour = 0
    
    time_str = f"{hour % 12 or 12}:{minute:02d} {'AM' if hour < 12 else 'PM'}"
    # Only claim success when an alarm was really set (it used to say "Alarm
    # set" with no alarm system, or after set_alarm failed).
    if not alarm_system:
        return HandlerResult(success=False, response=f"The alarm service isn't available right now, {title}.")
    try:
        if alarm_system.set_alarm(time_str) is not False:
            return HandlerResult(success=True, response=f"Alarm set for {time_str}, {title}.")
    except Exception as e:
        print(f"[HANDLERS] Alarm error: {e}")
    return HandlerResult(success=False, response=f"I couldn't set that alarm, {title}.")


def handle_set_timer(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle setting timers"""
    title = context.get('title', 'sir') if context else 'sir'
    alarm_system = context.get('alarm_system') if context else None

    # The spoken duration is the source of truth ("timer for 90 seconds").
    # This used to default to 5 minutes and call AlarmSystem.set_timer(),
    # which doesn't exist, then say "Timer set" anyway: no timer ever rang.
    from jarvis.core.intent_classifier import parse_duration
    parsed = parse_duration(cmd)
    if parsed:
        duration, unit = parsed
    elif entities.get('duration'):
        duration, unit = int(entities['duration']), entities.get('unit', 'minutes')
    else:
        return HandlerResult(success=False, response=f"For how long, {title}? For example, 'set a timer for 10 minutes'.")

    if not alarm_system:
        return HandlerResult(success=False, response=f"The timer service isn't available right now, {title}.")
    try:
        if alarm_system.set_alarm(f"in {duration} {unit}", label=f"Timer ({duration} {unit})") is not False:
            return HandlerResult(success=True, response=f"Timer set for {duration} {unit}, {title}.")
    except Exception as e:
        print(f"[HANDLERS] Timer error: {e}")
    return HandlerResult(success=False, response=f"I couldn't set that timer, {title}.")


# ═══════════════════════════════════════════════════════════════
# SCREENSHOT HANDLER
# ═══════════════════════════════════════════════════════════════

def handle_screenshot(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle screenshot requests"""
    title = context.get('title', 'sir') if context else 'sir'
    screenshot_handler = context.get('screenshot_handler') if context else None
    
    if screenshot_handler:
        try:
            path = screenshot_handler.take_screenshot()
            if path:
                return HandlerResult(
                    success=True,
                    response=f"Screenshot saved, {title}.",
                    data={'type': 'screenshot', 'path': str(path)}
                )
        except Exception as e:
            print(f"[HANDLERS] Screenshot error: {e}")
    
    # Fallback: use PIL
    try:
        from PIL import ImageGrab
        from pathlib import Path
        screenshots_dir = Path(__file__).parent.parent.parent / "jarvis_data" / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        filename = screenshots_dir / f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        img = ImageGrab.grab()
        img.save(str(filename))
        return HandlerResult(success=True, response=f"Screenshot saved, {title}.")
    except Exception as e:
        print(f"[HANDLERS] Screenshot fallback error: {e}")
    
    return HandlerResult(success=False, response=f"Couldn't take a screenshot, {title}.")


# ═══════════════════════════════════════════════════════════════
# CONVERSATION HANDLER
# ═══════════════════════════════════════════════════════════════

LONG_FORM_RE = re.compile(
    r"\b(?:explain|in detail|detailed|elaborate|step[- ]by[- ]step|history of|walk me through|"
    r"overview of|everything about|deep dive|how does .+ work|teach me|why (?:do|does|is|are|did))\b")

EXPLAINER_SYSTEM = ("You are JARVIS, a knowledgeable assistant explaining things out loud. Be accurate, "
                    "concrete and well organised, in natural spoken English: no markdown, no lists, "
                    "no headings. If you're unsure of a fact, say so.")


def handle_conversation(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle casual conversation / small talk"""
    title = context.get('title', 'sir') if context else 'sir'
    
    cmd_lower = cmd.lower()
    
    # Try AI if available
    knowledge = context.get('knowledge') if context else None

    # Explanations need room. Through the quick-answer persona (2-3 sentences)
    # "explain the history of the Roman Empire in detail" got "that is beyond
    # my current capabilities".
    if knowledge and hasattr(knowledge, 'create') and LONG_FORM_RE.search(cmd_lower):
        try:
            text = knowledge.create(
                f"{cmd}\n\nAnswer as a clear spoken explanation of about 150 words, or exactly "
                f"the length asked for. Start with the direct answer, then the key points in order.",
                system=EXPLAINER_SYSTEM, max_tokens=700)
            if text and len(text) > 20:
                return HandlerResult(success=True, response=text)
        except Exception as e:
            print(f"[HANDLERS] Explanation error: {e}")

    if knowledge and hasattr(knowledge, 'answer_question'):
        try:
            response = knowledge.answer_question(cmd)
            # Only use if it's a REAL answer (not an error fallback)
            _err = ['trouble connecting', 'knowledge base', 'currently offline', 'Set GROQ_API_KEY']
            if response and len(response) > 5 and not any(ep in response for ep in _err):
                return HandlerResult(success=True, response=response)
        except Exception as _err:
            recovered("Handlers", _err)
    
    # Return None so it falls through to Gemini API in websocket_server
    return None


def handle_dictionary(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle word definition requests"""
    title = context.get('title', 'sir') if context else 'sir'
    word = entities.get('word', '')
    
    if not word:
        match = re.search(r'(?:define|meaning of|what does|what is)\s+(?:the\s+word\s+)?([\w]+)', cmd, re.I)
        if match:
            word = match.group(1).strip()
    
    if not word:
        return HandlerResult(success=False, response=f"What word should I define, {title}?")
    
    # Try dictionary handler from context
    knowledge = context.get('knowledge') if context else None
    if knowledge and hasattr(knowledge, 'answer_question'):
        try:
            response = knowledge.answer_question(f"Define the word: {word}")
            if response:
                return HandlerResult(success=True, response=response)
        except Exception as _err:
            recovered("Handlers", _err)
    
    # Fallback: online dictionary API
    try:
        import urllib.request, json
        url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
        req = urllib.request.urlopen(url, timeout=5)
        data = json.loads(req.read())
        if data and isinstance(data, list):
            meaning = data[0]['meanings'][0]['definitions'][0]['definition']
            return HandlerResult(success=True, response=f"{word}: {meaning}")
    except Exception as _err:
        recovered("Handlers", _err)
    
    return HandlerResult(success=False, response=f"Couldn't find definition for '{word}', {title}.")


def handle_enable_gesture(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle enabling/disabling gesture control"""
    title = context.get('title', 'sir') if context else 'sir'
    return HandlerResult(
        success=True,
        response=f"Gesture control toggled, {title}. Use hand gestures to control playback and volume.",
        data={'type': 'gesture_toggle'}
    )


def handle_switch_to_friday(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle switching assistant voice to FRIDAY"""
    return HandlerResult(
        success=True,
        response="FRIDAY online. Hello, boss. How can I help you today?",
        data={'type': 'switch_voice', 'voice': 'friday'}
    )


def handle_switch_to_jarvis(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle switching assistant voice to JARVIS"""
    title = context.get('title', 'sir') if context else 'sir'
    return HandlerResult(
        success=True,
        response=f"JARVIS back online, {title}. At your service.",
        data={'type': 'switch_voice', 'voice': 'jarvis'}
    )


def handle_send_message(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle sending WhatsApp messages"""
    title = context.get('title', 'sir') if context else 'sir'
    whatsapp_handler = context.get('whatsapp_handler') if context else None
    
    if not whatsapp_handler:
        # Fallback to importing and running directly if not in context
        try:
            from jarvis.core.whatsapp_handler import WhatsAppHandler
            whatsapp_handler = shared(WhatsAppHandler, lambda: WhatsAppHandler(context.get('perception') if context else None))
        except ImportError:
            return HandlerResult(success=False, response=f"WhatsApp automation is not available, {title}.")
            
    import re as _re
    # "send a whatsapp to dad" gave contact="to dad" ("Message sent to to dad")
    contact = _re.sub(r"^(?:to|for)\s+", "", (entities.get('contact') or '').strip(), flags=_re.I)
    message = (entities.get('message') or '').strip()
    if not contact:
        return HandlerResult(success=False, response=f"Who should I message, {title}?")
    if not message:
        return HandlerResult(success=False, response=f"What should I say to {contact}, {title}?")

    result_text = whatsapp_handler.send_message(contact, message)
    return HandlerResult(success=True, response=result_text)


# ═══════════════════════════════════════════════════════════════
# P2-01: NEW HANDLERS — Wire disconnected features into voice pipeline
# ═══════════════════════════════════════════════════════════════

def handle_ocr(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Read the text on the screen: local Tesseract OCR if installed, otherwise
    Gemini vision (screen reading used to need Tesseract, so it never worked
    on a standard setup)."""
    title = context.get('title', 'sir') if context else 'sir'
    ocr_handler = context.get('ocr_handler') if context else None

    if not ocr_handler:
        try:
            from jarvis.core.ocr_handler import OCRHandler
            ocr_handler = shared(OCRHandler)
        except Exception:
            ocr_handler = None

    if ocr_handler is None or not ocr_handler.is_available():
        from jarvis.core import screen_vision
        if screen_vision.vision_available():
            try:
                text = screen_vision.read_screen_text()
                if text:
                    return HandlerResult(success=True, response=text)
            except Exception as e:
                print(f"[HANDLERS] Vision screen reading error: {e}")
            # success=True: as a failure the router fell through to the AI,
            # which made up what was on the screen.
            return HandlerResult(success=True, response=f"I couldn't read the screen just now, {title}. Please try again.")
        return HandlerResult(success=True, response=f"I can't read the screen yet, {title}: it needs a GEMINI_API_KEY "
                                                    f"in .env, or Tesseract OCR installed.")

    try:
        text = ocr_handler.read_screen()
        if text:
            return HandlerResult(success=True, response=f"Here's what I can read on your screen: {text}")
        else:
            return HandlerResult(success=True, response=f"I couldn't read any text on the screen, {title}.")
    except Exception as e:
        print(f"[HANDLERS] OCR error: {e}")
        return HandlerResult(success=False, response=f"Error reading screen, {title}.")


def handle_screen_question(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """'what is this?', 'explain this error', 'what am I looking at?': look at
    the screen and answer. These used to reach the text model with no idea
    what 'this' was."""
    title = context.get('title', 'sir') if context else 'sir'
    from jarvis.core import screen_vision
    if not screen_vision.vision_available():
        return HandlerResult(success=True, response=f"I can't see your screen without a GEMINI_API_KEY in .env, {title}.")
    try:
        answer = screen_vision.ask_about_screen(cmd)
        if answer:
            from jarvis.core.knowledge import clean_for_speech
            return HandlerResult(success=True, response=clean_for_speech(answer))
    except Exception as e:
        print(f"[HANDLERS] Screen question error: {e}")
    return HandlerResult(success=True, response=f"I couldn't get a look at the screen just now, {title}. Please try again.")


def handle_screen_control(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle screen control commands (click, scroll, type, etc.)"""
    title = context.get('title', 'sir') if context else 'sir'
    
    try:
        # The class is ScreenControlHandler; this used to import a non-existent
        # ScreenController, so voice screen control always failed.
        from jarvis.core.screen_control import ScreenControlHandler
        controller = shared(ScreenControlHandler)
        raw_text = entities.get('raw_text') or cmd
        result = controller.handle(raw_text, entities)
        if not result or result.startswith("I didn't understand"):
            # let the router try other paths instead of answering with a non-action
            return HandlerResult(success=False, response=f"I'm not sure which screen action you mean, {title}.")
        return HandlerResult(success=True, response=result)
    except ImportError:
        return HandlerResult(success=False, response=f"Screen control is not available, {title}.")
    except Exception as e:
        print(f"[HANDLERS] Screen control error: {e}")
        return HandlerResult(success=False, response=f"Error executing screen control, {title}.")


def handle_habit(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle habit tracking requests"""
    title = context.get('title', 'sir') if context else 'sir'
    
    try:
        from jarvis.core.habit_tracker import HabitTracker
        tracker = shared(HabitTracker)
        
        cmd_lower = cmd.lower()
        if 'list' in cmd_lower or 'show' in cmd_lower or 'my habits' in cmd_lower:
            habits = tracker.list_habits()
            if habits:
                habit_list = ", ".join(habits)
                return HandlerResult(success=True, response=f"Your tracked habits: {habit_list}")
            return HandlerResult(success=True, response=f"No habits tracked yet, {title}. Say 'add habit' to start.")
        
        if 'add' in cmd_lower or 'track' in cmd_lower or 'create' in cmd_lower:
            name = re.sub(r'(add|track|create|new)\s*(habit)?\s*', '', cmd_lower).strip()
            if name:
                tracker.add_habit(name)
                return HandlerResult(success=True, response=f"Now tracking habit: {name}")
            return HandlerResult(success=True, response=f"What habit would you like to track, {title}?")
        
        return HandlerResult(success=True, response=f"I can track your habits, {title}. Say 'list habits' or 'add habit [name]'.")
    except ImportError:
        return HandlerResult(success=False, response=f"Habit tracking module is not available, {title}.")
    except Exception as e:
        print(f"[HANDLERS] Habit error: {e}")
        return HandlerResult(success=False, response=f"Error with habit tracking, {title}.")


def handle_email(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle email requests"""
    title = context.get('title', 'sir') if context else 'sir'
    
    try:
        from jarvis.core.email_handler import EmailHandler
        email_handler = shared(EmailHandler)
        
        cmd_lower = cmd.lower()
        if 'send' in cmd_lower:
            return HandlerResult(success=True, response=f"To send an email, I need the recipient, subject, and message, {title}. Could you provide those details?")
        elif 'check' in cmd_lower or 'read' in cmd_lower:
            emails = email_handler.check_inbox()
            if emails:
                return HandlerResult(success=True, response=f"You have {len(emails)} recent emails, {title}. {emails[0] if emails else ''}")
            return HandlerResult(success=True, response=f"No new emails, {title}.")
        
        return HandlerResult(success=True, response=f"I can send or check emails, {title}. What would you like to do?")
    except ImportError:
        return HandlerResult(success=False, response=f"Email module is not available, {title}. Configure SMTP credentials in .env to enable it.")
    except Exception as e:
        print(f"[HANDLERS] Email error: {e}")
        return HandlerResult(success=False, response=f"Error with email, {title}.")


def handle_calendar(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Handle calendar requests"""
    title = context.get('title', 'sir') if context else 'sir'
    
    try:
        from jarvis.core.calendar_manager import CalendarManager
        cal = shared(CalendarManager)
        
        cmd_lower = cmd.lower()
        if 'today' in cmd_lower or 'events' in cmd_lower or 'schedule' in cmd_lower:
            events = cal.get_today_events_list() if hasattr(cal, 'get_today_events_list') else []
            if events:
                event_text = "; ".join(events[:5])
                return HandlerResult(success=True, response=f"Today's events: {event_text}")
            return HandlerResult(success=True, response=f"No events scheduled for today, {title}.")
        
        return HandlerResult(success=True, response=f"I can check your calendar, {title}. Ask about today's events or your schedule.")
    except ImportError:
        return HandlerResult(success=False, response=f"Calendar module is not available, {title}. Set up Google Calendar API credentials to enable it.")
    except Exception as e:
        print(f"[HANDLERS] Calendar error: {e}")
        return HandlerResult(success=False, response=f"Error accessing calendar, {title}.")


# ═══════════════════════════════════════════════════════════════
# HANDLER REGISTRY
# ═══════════════════════════════════════════════════════════════

def handle_lock_screen(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Lock the Windows session (Win+L). Fully reversible: just sign back in."""
    title = context.get('title', 'sir') if context else 'sir'
    try:
        from jarvis.core.safe_exec import lock_workstation
        if lock_workstation():
            return HandlerResult(success=True, response=f"Locking the screen, {title}.")
    except Exception as e:
        print(f"[HANDLERS] Lock screen error: {e}")
    return HandlerResult(success=False, response=f"I couldn't lock the screen, {title}.")


def handle_take_note(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Save a note ("take a note buy eggs")."""
    title = context.get('title', 'sir') if context else 'sir'
    content = (entities.get('content') or '').strip()
    if not content:
        return HandlerResult(success=False, response=f"What should the note say, {title}?")
    try:
        from jarvis.core.smart_notes import SmartNotes
        shared(SmartNotes, lambda: SmartNotes(context.get('perception') if context else None)).add_note(content)
        return HandlerResult(success=True, response=f"Noted, {title}: {content}.")
    except Exception as e:
        print(f"[HANDLERS] Note error: {e}")
        return HandlerResult(success=False, response=f"I couldn't save that note, {title}.")


def handle_list_notes(cmd: str, entities: Dict, context: Any) -> HandlerResult:
    """Read back the most recent notes."""
    title = context.get('title', 'sir') if context else 'sir'
    try:
        from jarvis.core.smart_notes import SmartNotes
        notes = shared(SmartNotes, lambda: SmartNotes(context.get('perception') if context else None)).get_recent_notes(5)
    except Exception as e:
        print(f"[HANDLERS] Notes error: {e}")
        return HandlerResult(success=False, response=f"I couldn't open your notes, {title}.")
    if not notes:
        return HandlerResult(success=True, response=f"You have no notes yet, {title}.")
    items = "; ".join(n.content for n in notes)
    return HandlerResult(success=True, response=f"Your latest notes, {title}: {items}.")


HANDLER_MAP = {
    'greeting': handle_greeting,
    'farewell': handle_farewell,
    'time': handle_time,
    'date': handle_date,
    'identity': handle_identity,
    'creator': handle_creator,
    'help': handle_help,
    'thanks': handle_thanks,
    'how_are_you': handle_how_are_you,
    'weather': handle_weather,
    'system_status': handle_system_status,
    'joke': handle_joke,
    'story': handle_story,
    'poem': handle_poem,
    # Batch 2 handlers
    'news': handle_news,
    'search_news': handle_search_news,
    'open_app': handle_open_app,
    'volume': handle_volume,
    'brightness': handle_brightness,
    'search': handle_search,
    # AI Search handlers (Perplexica/Scira-inspired)
    'ai_search': handle_ai_search,
    'remember': handle_remember,
    'recall': handle_recall,
    # Music handlers - DIRECT responses
    'play_music': handle_play_music,
    'pause_music': handle_pause_music,
    'next_track': handle_next_track,
    'previous_track': handle_previous_track,
    # Reminder handlers
    'set_reminder': handle_set_reminder,
    'list_reminders': handle_list_reminders,
    # Alarm & Timer handlers
    'set_alarm': handle_set_alarm,
    'set_timer': handle_set_timer,
    # Screenshot handler
    'screenshot': handle_screenshot,
    # Conversation handler
    'conversation': handle_conversation,
    # Help handlers - Clear responses about features
    'gesture_help': handle_gesture_help,
    'face_recognition': handle_face_recognition_cmd,
    'improvement_suggestions': handle_improvement_suggestions,
    # Dictionary handler
    'dictionary': handle_dictionary,
    # Gesture toggle
    'enable_gesture': handle_enable_gesture,
    # Communication
    'send_message': handle_send_message,
    # Voice switching
    'switch_to_friday': handle_switch_to_friday,
    'switch_to_jarvis': handle_switch_to_jarvis,
    # P2-01: Newly wired features
    'ocr': handle_ocr,
    'screen_question': handle_screen_question,
    'screen_control': handle_screen_control,
    'habit': handle_habit,
    'email': handle_email,
    'calendar': handle_calendar,
    'lock_screen': handle_lock_screen,
    'take_note': handle_take_note,
    'list_notes': handle_list_notes,
}



# ─────────────────────────────────────────────────────────────────────────────
# BrainAdapter intent names → HANDLER_MAP names
#
# The ML classifier (intent_definitions.INTENT_EXAMPLES) uses names like
# "get_time" or "volume_up", while handlers are registered as "time" and
# "volume". Without this table most confident ML results matched no handler
# and fell through to slower paths. Entries are (handler_name, default_entities);
# defaults only fill entities the extractor did not set.
#
# Deliberately NOT mapped (handled earlier with dedicated, safer logic):
#   shutdown / restart (confirmation flow), close_app (validated fast path),
#   cancel_alarm, play_youtube; list_alarms is served by the
#   router's own alarm-system branch.
# ─────────────────────────────────────────────────────────────────────────────
BRAIN_INTENT_ALIASES = {
    'get_time': ('time', {}),
    'get_date': ('date', {}),
    'tell_joke': ('joke', {}),
    'tell_story': ('story', {}),
    'volume_up': ('volume', {'action': 'up'}),
    'volume_down': ('volume', {'action': 'down'}),
    'mute': ('volume', {'action': 'mute'}),
    'brightness_up': ('brightness', {'action': 'up'}),
    'brightness_down': ('brightness', {'action': 'down'}),
    'skip_track': ('next_track', {}),
    'resume_music': ('play_music', {}),
    'search_web': ('search', {}),
    'ask_question': ('conversation', {}),
    'goodbye': ('farewell', {}),
    'thank_you': ('thanks', {}),
    'get_calendar': ('calendar', {}),
    'create_event': ('calendar', {}),
    'send_whatsapp': ('send_message', {}),
}


def _explicit_search(text: str) -> bool:
    import re as _re
    return bool(_re.match(r"^\s*(?:please\s+)?(?:search|google|look\s+up|find|browse)\b", text, _re.I))


def resolve_brain_intent(intent: str, entities: Dict = None, text: str = ""):
    """Translate a BrainAdapter intent to its HANDLER_MAP name, filling default entities.

    search_web only opens a browser search when the user asked to search
    ("search for…", "google…"). A plain question ("what is quantum computing")
    goes to the conversation handler, which answers it.
    """
    entities = dict(entities or {})
    if intent == "search_web" and text and not _explicit_search(text):
        return "conversation", entities
    target, defaults = BRAIN_INTENT_ALIASES.get(intent, (intent, {}))
    for key, value in defaults.items():
        entities.setdefault(key, value)
    return target, entities
