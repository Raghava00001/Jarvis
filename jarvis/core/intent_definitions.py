"""
Intent Definitions
==================
Training data for embedding-based intent classification.
Each intent has 5+ example phrases for semantic matching.
"""

# Core intent examples - used to build intent embeddings
INTENT_EXAMPLES = {
    # Music Control
    "play_music": [
        "play music",
        "play a song",
        "start spotify",
        "put on some music",
        "play blinding lights",
        "i want to listen to music",
        "play some tunes",
        "turn on music",
        "play my playlist",
        "play songs by taylor swift",
    ],
    
    "pause_music": [
        "pause music",
        "stop the song",
        "pause playback",
        "stop playing",
        "pause the music",
        "hold the music",
    ],
    
    "resume_music": [
        "resume music",
        "continue playing",
        "unpause",
        "play again",
        "continue the song",
    ],
    
    "skip_track": [
        "skip this song",
        "next song",
        "play next",
        "skip track",
        "next track please",
    ],
    
    "previous_track": [
        "previous song",
        "go back",
        "play previous",
        "last song",
        "previous track",
    ],
    
    # Alarms & Reminders
    "set_alarm": [
        "set alarm for 7 am",
        "wake me up at 6",
        "set an alarm",
        "alarm at 9 pm",
        "set a reminder for 3 pm",
        "remind me in 10 minutes",
        "wake me up tomorrow at 8",
    ],
    
    "list_alarms": [
        "show my alarms",
        "what alarms do i have",
        "list all alarms",
        "show reminders",
    ],
    
    "cancel_alarm": [
        "cancel alarm",
        "delete alarm",
        "remove the alarm",
        "turn off alarm",
        "stop the alarm",
    ],
    
    # App Control
    "open_app": [
        "open chrome",
        "launch whatsapp",
        "start vscode",
        "open calculator",
        "launch spotify",
        "open notepad",
        "start discord",
        "open file explorer",
        "run the app",
        "open google chrome",
        "start brave browser",
        "open microsoft edge",
        "launch perplexity",
        "open chatgpt",
        "run visual studio code",
        "open the terminal",
        "start command prompt",
        "launch powershell",
        "open settings",
        "run excel",
        "launch word",
        "open steam",
        "run obs",
        "open zoom",
        "start teams",
        "can you open chrome",
        "please open firefox",
        "I need vscode open",
        "open cursor for me",
    ],
    
    "close_app": [
        "close chrome",
        "exit the app",
        "quit vscode",
        "close this window",
        "terminate the program",
    ],
    
    # Web Search & Information
    "search_web": [
        "search for quantum physics",
        "google best laptops",
        "look up latest news",
        "search the web for",
        "find information about",
        "what is machine learning",
    ],
    
    "ask_question": [
        "translate hello to spanish",
        "how do you say thank you in french",
        "how far is the moon",
        "tell me about python",
        "explain quantum computing",
        "what's the capital of france",
    ],
    
    # System Control
    "get_time": [
        "what time is it",
        "tell me the time",
        "what's the current time",
        "time please",
    ],
    
    "get_date": [
        "what's today's date",
        "what day is it",
        "tell me the date",
    ],
    
    "volume_up": [
        "increase volume",
        "volume up",
        "louder please",
        "turn it up",
        "make it louder",
    ],
    
    "volume_down": [
        "decrease volume",
        "volume down",
        "quieter please",
        "turn it down",
        "make it softer",
    ],
    
    "mute": [
        "mute",
        "silence",
        "mute the sound",
        "turn off sound",
    ],
    
    "brightness_up": [
        "increase brightness",
        "brighter screen",
        "turn up brightness",
        "make it brighter",
    ],
    
    "brightness_down": [
        "decrease brightness",
        "dim the screen",
        "lower brightness",
        "make it darker",
    ],
    
    # Calendar
    "get_calendar": [
        "what's on my calendar",
        "show my schedule",
        "what events do i have",
        "my appointments today",
        "upcoming events",
    ],
    
    "create_event": [
        "create a meeting",
        "add event to calendar",
        "schedule a meeting",
        "book an appointment",
    ],
    
    # Communication
    "send_whatsapp": [
        "send whatsapp message",
        "message on whatsapp",
        "whatsapp mom",
        "send a message to",
        "text on whatsapp",
    ],
    
    # Entertainment
    "tell_joke": [
        "tell me a joke",
        "make me laugh",
        "say something funny",
        "tell a joke",
    ],
    
    "tell_story": [
        "tell me a story",
        "tell a bedtime story",
        "narrate a story",
        "story time",
    ],
    
    # YouTube
    "play_youtube": [
        "play on youtube",
        "open youtube video",
        "search youtube for",
        "play this on youtube",
        "find on youtube",
    ],
    
    # System Actions
    "shutdown": [
        "shutdown computer",
        "turn off the pc",
        "shut down",
        "power off",
    ],
    
    "restart": [
        "restart computer",
        "reboot",
        "restart the system",
    ],
    
    "lock_screen": [
        "lock the screen",
        "lock computer",
        "lock my pc",
    ],
    
    # JARVIS Meta
    "greeting": [
        "hello jarvis",
        "hey jarvis",
        "good morning",
        "hi there",
        "how are you",
    ],
    
    "goodbye": [
        "goodbye jarvis",
        "bye",
        "see you later",
        "that's all",
        "exit",
        "quit",
    ],
    
    "help": [
        "what can you do",
        "help me",
        "show me what you can do",
        "list your capabilities",
    ],
    
    "thank_you": [
        "thank you",
        "thanks jarvis",
        "appreciate it",
        "thanks a lot",
    ],

    # ── Intents below are named after their HANDLER_MAP handler. Before v2.6
    # the classifier had no examples for them, so e.g. "what is the weather in
    # new york" was confidently classified as a web search and "set a timer"
    # as "what time is it".
    "weather": [
        "what's the weather like",
        "what is the weather in new york",
        "weather in london",
        "is it going to rain today",
        "how hot is it outside",
        "temperature outside",
        "weather forecast",
    ],
    "news": [
        "tell me the news",
        "latest headlines",
        "what's happening in the world",
        "sports news",
        "technology news",
        "read me the news",
    ],
    "set_timer": [
        "set a timer for 5 minutes",
        "start a 10 minute timer",
        "timer for 30 seconds",
        "count down 2 minutes",
        "set a timer",
    ],
    "set_reminder": [
        "remind me to drink water in 10 minutes",
        "remind me to call mom at 6",
        "set a reminder for the meeting",
        "don't let me forget to take my medicine",
    ],
    "list_reminders": [
        "show my reminders",
        "what are my reminders",
        "list reminders",
        "do i have any reminders",
    ],
    "system_status": [
        "system status",
        "battery level",
        "how much battery is left",
        "cpu usage",
        "how much memory am i using",
        "check system health",
    ],
    "screen_control": [
        "scroll down",
        "scroll up",
        "minimize window",
        "maximize window",
        "next tab",
        "close this tab",
        "zoom in",
    ],
    "screenshot": [
        "take a screenshot",
        "capture the screen",
        "screenshot this",
        "grab a screen capture",
    ],
    "identity": [
        "who are you",
        "what are you",
        "what is your name",
        "introduce yourself",
    ],
    "creator": [
        "who created you",
        "who made you",
        "who built you",
        "who is your creator",
    ],
    "how_are_you": [
        "how are you",
        "how are you doing",
        "how's it going jarvis",
        "are you okay",
    ],
    "switch_to_friday": [
        "switch to friday",
        "activate friday",
        "change voice to friday",
    ],
    "switch_to_jarvis": [
        "switch to jarvis",
        "activate jarvis",
        "change voice back to jarvis",
    ],
    "dictionary": [
        "define serendipity",
        "what does ephemeral mean",
        "meaning of the word ubiquitous",
        "dictionary lookup for resilience",
    ],
    "poem": [
        "tell me a poem",
        "write a poem about the sea",
        "recite a poem",
    ],
    "remember": [
        "remember that my car is parked on level 3",
        "remember my wifi password is in the drawer",
    ],
    "take_note": [
        "take a note buy eggs",
        "make a note that the meeting moved to friday",
        "note that the wifi password is in the drawer",
        "write down call the bank tomorrow",
    ],
    "recall": [
        "what did i ask you to remember",
        "where did i park my car",
        "what do you remember about me",
    ],
    "list_notes": [
        "show my notes",
        "read my notes",
        "what are my notes",
        "list all my notes",
    ],
}


# Intent categories for grouped handling
INTENT_CATEGORIES = {
    "music": ["play_music", "pause_music", "resume_music", "skip_track", "previous_track"],
    "alarm": ["set_alarm", "list_alarms", "cancel_alarm"],
    "app": ["open_app", "close_app"],
    "search": ["search_web", "ask_question"],
    "system": ["volume_up", "volume_down", "mute", "brightness_up", "brightness_down", 
               "shutdown", "restart", "lock_screen"],
    "calendar": ["get_calendar", "create_event"],
    "communication": ["send_whatsapp"],
    "entertainment": ["tell_joke", "tell_story", "play_youtube"],
    "time": ["get_time", "get_date"],
    "meta": ["greeting", "goodbye", "help", "thank_you"],
}


def get_category(intent: str) -> str:
    """Get the category for an intent"""
    for category, intents in INTENT_CATEGORIES.items():
        if intent in intents:
            return category
    return "unknown"
