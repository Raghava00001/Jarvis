"""
Optional features of the HUD server.

Each subsystem is imported in its own try block, so a missing library (e.g.
MediaPipe, Gmail API) only disables that feature. *_AVAILABLE says whether it
loaded; MISSING_IMPORTS lists what didn't, for the feature status panel.
"""

import logging


_log = logging.getLogger(__name__)

try:
    from jarvis.core.logger import get_logger
    jlog = get_logger()
except ImportError:
    jlog = None
JARVIS_AVAILABLE = False
PERCEPTION_AVAILABLE = False
GESTURE_AVAILABLE = False
FACE_AVAILABLE = False
EMOTION_AVAILABLE = False
NEWS_AVAILABLE = False
WEATHER_AVAILABLE = False
SCREENSHOT_AVAILABLE = False
OCR_AVAILABLE = False
DICTIONARY_AVAILABLE = False
EMAIL_AVAILABLE = False
ENTERTAINMENT_AVAILABLE = False
NOTES_AVAILABLE = False
ALARM_AVAILABLE = False
SYSTEM_CONTROL_AVAILABLE = False
CONTEXT_MEMORY_AVAILABLE = False
SCREEN_CONTROL_AVAILABLE = False
try:
    from jarvis.core.jarvis_ultimate import JARVISUltimate
    JARVIS_AVAILABLE = True
    _log.info("[WebSocket] JARVISUltimate available - FULL INTEGRATION")
except ImportError as e:
    _log.warning(f"[WebSocket] JARVISUltimate not available: {e}")
    JARVIS_AVAILABLE = False
MISSING_IMPORTS = []
def _optional_missing(err):
    MISSING_IMPORTS.append(str(err))
    _log.warning(f"[WebSocket] Optional feature unavailable: {err}")
try:
    from jarvis.core.perception import PerceptionLayer
    PERCEPTION_AVAILABLE = True
except ImportError as _e:
    _optional_missing(_e)
try:
    from jarvis.core.gesture_controller import GestureController  # (also asked for a non-existent GestureType, so this always failed)
    GESTURE_AVAILABLE = True
    _log.info("[WebSocket] Gesture controller available")
except ImportError as _e:
    _optional_missing(_e)
try:
    from jarvis.core.face_recognition_auth import FaceRecognition, UserType
    FACE_AVAILABLE = True
    _log.info("[WebSocket] Face recognition available")
except ImportError as _e:
    _optional_missing(_e)
try:
    # EmotionState comes from mood_engine (imported above); importing the
    # detector's EmotionState here used to silently replace it
    from jarvis.core.emotion_detector import EmotionDetector
    EMOTION_AVAILABLE = True
    _log.info("[WebSocket] Emotion detector available")
except ImportError as _e:
    _optional_missing(_e)
try:
    from jarvis.core.news_handler import NewsHandler
    NEWS_AVAILABLE = True
except ImportError as _e:
    _optional_missing(_e)
try:
    from jarvis.core.weather_handler import WeatherHandler
    WEATHER_AVAILABLE = True
except ImportError as _e:
    _optional_missing(_e)
try:
    from jarvis.core.system_status import SystemStatus
    SYSTEM_STATUS_AVAILABLE = True
except ImportError:
    SYSTEM_STATUS_AVAILABLE = False
try:
    from jarvis.core.screenshot_handler import ScreenshotHandler
    SCREENSHOT_AVAILABLE = True
    _log.info("[WebSocket] Screenshot handler available")
except ImportError as _e:
    _optional_missing(_e)
try:
    from jarvis.core.ocr_handler import OCRHandler
    OCR_AVAILABLE = True
    _log.info("[WebSocket] OCR handler available")
except ImportError as _e:
    _optional_missing(_e)
try:
    from jarvis.core.dictionary_handler import DictionaryHandler
    DICTIONARY_AVAILABLE = True
    _log.info("[WebSocket] Dictionary handler available")
except ImportError as _e:
    _optional_missing(_e)
try:
    from jarvis.core.email_handler import EmailHandler
    EMAIL_AVAILABLE = True
    _log.info("[WebSocket] Email handler available")
except ImportError as _e:
    _optional_missing(_e)
try:
    from jarvis.core.entertainment import JARVISEntertainment
    ENTERTAINMENT_AVAILABLE = True
    _log.info("[WebSocket] Entertainment module available")
except ImportError as _e:
    _optional_missing(_e)
try:
    from jarvis.core.smart_notes import SmartNotes
    NOTES_AVAILABLE = True
    _log.info("[WebSocket] Smart notes available")
except ImportError as _e:
    _optional_missing(_e)
try:
    from jarvis.core.alarm_system import AlarmSystem
    ALARM_AVAILABLE = True
    _log.info("[WebSocket] Alarm system available")
except ImportError as _e:
    _optional_missing(_e)
REMINDER_AVAILABLE = False
try:
    from jarvis.core.reminder_manager import ReminderManager
    REMINDER_AVAILABLE = True
    _log.info("[WebSocket] Reminder manager available")
except ImportError as _e:
    _optional_missing(_e)
try:
    from jarvis.core.system_control import SystemControl
    SYSTEM_CONTROL_AVAILABLE = True
    _log.info("[WebSocket] System control available")
except ImportError as _e:
    _optional_missing(_e)
KNOWLEDGE_AVAILABLE = False
try:
    from jarvis.core.knowledge import KnowledgeLayer
    KNOWLEDGE_AVAILABLE = True
    _log.info("[WebSocket] Knowledge layer (Gemini AI) available")
except ImportError as _e:
    _optional_missing(_e)
ROUTER_AVAILABLE = False
try:
    from jarvis.core.intent_router import IntentRouter, Intent, HandlerResult
    from jarvis.core.intent_classifier import classify_intent
    from jarvis.core.intent_handlers import HANDLER_MAP
    ROUTER_AVAILABLE = True
    _log.info("[WebSocket] IntentRouter and handlers available")
except ImportError as e:
    _log.warning(f"[WebSocket] IntentRouter not available: {e}")
try:
    from jarvis.core.context_memory import ContextMemory, WorkingMemory
    CONTEXT_MEMORY_AVAILABLE = True
    _log.info("[WebSocket] ContextMemory available - enhanced conversations")
except ImportError as _e:
    _optional_missing(_e)
try:
    from jarvis.core.screen_control import ScreenControlHandler
    SCREEN_CONTROL_AVAILABLE = True
    _log.info("[WebSocket] Screen control available")
except ImportError as _e:
    _optional_missing(_e)
GEMINI_LIVE_AVAILABLE = False
try:
    from jarvis.core.gemini_live_engine import GeminiLiveEngine
    import os
    if os.getenv("JARVIS_USE_GEMINI_LIVE", "0") == "1" and os.getenv("GEMINI_API_KEY"):
        GEMINI_LIVE_AVAILABLE = True
        _log.info("[WebSocket] Gemini Live Engine available and enabled by .env")
except ImportError as e:
    _log.warning(f"[WebSocket] Gemini Live Engine not available: {e}")
PDF_AVAILABLE = False
try:
    from jarvis.core.pdf_handler import PDFHandler
    PDF_AVAILABLE = True
    _log.info("[WebSocket] PDF handler available")
except ImportError as _e:
    _optional_missing(_e)
BRAIN_AVAILABLE = False
try:
    from jarvis.core.brain_adapter import BrainAdapter, get_brain_adapter
    BRAIN_AVAILABLE = True
    _log.info("[WebSocket] Brain Adapter available")
except ImportError as e:
    _log.warning(f"[WebSocket] Brain Adapter not available: {e}")
WHATSAPP_AVAILABLE = False
try:
    from jarvis.core.whatsapp_handler import WhatsAppHandler
    WHATSAPP_AVAILABLE = True
    _log.info("[WebSocket] WhatsApp handler available")
except ImportError as _e:
    _optional_missing(_e)
CALENDAR_AVAILABLE = False
try:
    from jarvis.core.calendar_integration import CalendarIntegration
    CALENDAR_AVAILABLE = True
    _log.info("[WebSocket] Calendar integration available")
except ImportError as _e:
    _optional_missing(_e)
PROACTIVE_AVAILABLE = False
try:
    from jarvis.core.proactive_assistant import ProactiveAssistant
    PROACTIVE_AVAILABLE = True
    _log.info("[WebSocket] Proactive assistant available")
except ImportError as _e:
    _optional_missing(_e)
EMAIL_HANDLER_AVAILABLE = EMAIL_AVAILABLE
YOUTUBE_AVAILABLE = False
try:
    from jarvis.core.youtube_downloader import YouTubeDownloader
    YOUTUBE_AVAILABLE = True
    _log.info("[WebSocket] YouTube downloader available")
except ImportError as _e:
    _optional_missing(_e)
HOTKEY_AVAILABLE = False
try:
    from jarvis.core.hotkey_system import HotkeySystem
    HOTKEY_AVAILABLE = True
    _log.info("[WebSocket] Hotkey system available")
except ImportError as _e:
    _optional_missing(_e)
CHAT_HISTORY_AVAILABLE = False
try:
    from jarvis.core.chat_history import ChatHistory
    CHAT_HISTORY_AVAILABLE = True
    _log.info("[WebSocket] Chat history available")
except ImportError as _e:
    _optional_missing(_e)
HABIT_TRACKER_AVAILABLE = False
try:
    from jarvis.core.habit_tracker import HabitTracker
    HABIT_TRACKER_AVAILABLE = True
    _log.info("[WebSocket] Habit tracker available")
except ImportError as _e:
    _optional_missing(_e)
TASK_MANAGER_AVAILABLE = False
try:
    from jarvis.core.task_manager import TaskManager
    TASK_MANAGER_AVAILABLE = True
    _log.info("[WebSocket] Task manager available")
except ImportError as _e:
    _optional_missing(_e)
WELLNESS_AVAILABLE = False
try:
    from jarvis.core.wellness_monitor import WellnessMonitor
    WELLNESS_AVAILABLE = True
    _log.info("[WebSocket] Wellness monitor available")
except ImportError as _e:
    _optional_missing(_e)
CLIPBOARD_AVAILABLE = False
try:
    from jarvis.core.clipboard_intelligence import ClipboardIntelligence
    CLIPBOARD_AVAILABLE = True
    _log.info("[WebSocket] Clipboard Intelligence available")
except ImportError as _e:
    _optional_missing(_e)


# A name whose import failed above is None (its *_AVAILABLE flag is False),
# so other modules can import it unconditionally.
for _name in (
    'AlarmSystem',
    'BrainAdapter',
    'CalendarIntegration',
    'ChatHistory',
    'ClipboardIntelligence',
    'ContextMemory',
    'DictionaryHandler',
    'EmailHandler',
    'EmotionDetector',
    'FaceRecognition',
    'GeminiLiveEngine',
    'GestureController',
    'HANDLER_MAP',
    'HabitTracker',
    'HandlerResult',
    'HotkeySystem',
    'Intent',
    'IntentRouter',
    'JARVISEntertainment',
    'JARVISUltimate',
    'KnowledgeLayer',
    'NewsHandler',
    'OCRHandler',
    'PDFHandler',
    'PerceptionLayer',
    'ProactiveAssistant',
    'ReminderManager',
    'ScreenControlHandler',
    'ScreenshotHandler',
    'SmartNotes',
    'SystemControl',
    'SystemStatus',
    'TaskManager',
    'UserType',
    'WeatherHandler',
    'WellnessMonitor',
    'WhatsAppHandler',
    'WorkingMemory',
    'YouTubeDownloader',
    'classify_intent',
    'get_brain_adapter',
    'get_logger',
):
    globals().setdefault(_name, None)
del _name



# Exported to the rest of the server (pyflakes: these imports are the point of this module)
__all__ = [
    'ALARM_AVAILABLE',
    'AlarmSystem',
    'BRAIN_AVAILABLE',
    'BrainAdapter',
    'CALENDAR_AVAILABLE',
    'CHAT_HISTORY_AVAILABLE',
    'CLIPBOARD_AVAILABLE',
    'CONTEXT_MEMORY_AVAILABLE',
    'CalendarIntegration',
    'ChatHistory',
    'ClipboardIntelligence',
    'ContextMemory',
    'DICTIONARY_AVAILABLE',
    'DictionaryHandler',
    'EMAIL_AVAILABLE',
    'EMAIL_HANDLER_AVAILABLE',
    'EMOTION_AVAILABLE',
    'ENTERTAINMENT_AVAILABLE',
    'EmailHandler',
    'EmotionDetector',
    'FACE_AVAILABLE',
    'FaceRecognition',
    'GEMINI_LIVE_AVAILABLE',
    'GESTURE_AVAILABLE',
    'GeminiLiveEngine',
    'GestureController',
    'HABIT_TRACKER_AVAILABLE',
    'HANDLER_MAP',
    'HOTKEY_AVAILABLE',
    'HabitTracker',
    'HandlerResult',
    'HotkeySystem',
    'Intent',
    'IntentRouter',
    'JARVISEntertainment',
    'JARVISUltimate',
    'JARVIS_AVAILABLE',
    'KNOWLEDGE_AVAILABLE',
    'KnowledgeLayer',
    'MISSING_IMPORTS',
    'NEWS_AVAILABLE',
    'NOTES_AVAILABLE',
    'NewsHandler',
    'OCRHandler',
    'OCR_AVAILABLE',
    'PDFHandler',
    'PDF_AVAILABLE',
    'PERCEPTION_AVAILABLE',
    'PROACTIVE_AVAILABLE',
    'PerceptionLayer',
    'ProactiveAssistant',
    'REMINDER_AVAILABLE',
    'ROUTER_AVAILABLE',
    'ReminderManager',
    'SCREENSHOT_AVAILABLE',
    'SCREEN_CONTROL_AVAILABLE',
    'SYSTEM_CONTROL_AVAILABLE',
    'SYSTEM_STATUS_AVAILABLE',
    'ScreenControlHandler',
    'ScreenshotHandler',
    'SmartNotes',
    'SystemControl',
    'SystemStatus',
    'TASK_MANAGER_AVAILABLE',
    'TaskManager',
    'UserType',
    'WEATHER_AVAILABLE',
    'WELLNESS_AVAILABLE',
    'WHATSAPP_AVAILABLE',
    'WeatherHandler',
    'WellnessMonitor',
    'WhatsAppHandler',
    'WorkingMemory',
    'YOUTUBE_AVAILABLE',
    'YouTubeDownloader',
    'classify_intent',
    'get_brain_adapter',
    'get_logger',
    'jlog',
]