"""
Startup: the core JARVIS instance, the fallback processor, and loading every subsystem (critical ones now, the rest in the background).
"""

import logging
import os
import threading
from pathlib import Path

from jarvis.core.errors import recovered
from jarvis.core.services import shared
from jarvis.gui.server.features import ALARM_AVAILABLE
from jarvis.gui.server.features import AlarmSystem
from jarvis.gui.server.features import BRAIN_AVAILABLE
from jarvis.gui.server.features import CALENDAR_AVAILABLE
from jarvis.gui.server.features import CHAT_HISTORY_AVAILABLE
from jarvis.gui.server.features import CLIPBOARD_AVAILABLE
from jarvis.gui.server.features import CONTEXT_MEMORY_AVAILABLE
from jarvis.gui.server.features import CalendarIntegration
from jarvis.gui.server.features import ChatHistory
from jarvis.gui.server.features import ClipboardIntelligence
from jarvis.gui.server.features import ContextMemory
from jarvis.gui.server.features import DICTIONARY_AVAILABLE
from jarvis.gui.server.features import DictionaryHandler
from jarvis.gui.server.features import EMAIL_HANDLER_AVAILABLE
from jarvis.gui.server.features import EMOTION_AVAILABLE
from jarvis.gui.server.features import ENTERTAINMENT_AVAILABLE
from jarvis.gui.server.features import EmailHandler
from jarvis.gui.server.features import EmotionDetector
from jarvis.gui.server.features import FACE_AVAILABLE
from jarvis.gui.server.features import FaceRecognition
from jarvis.gui.server.features import GEMINI_LIVE_AVAILABLE
from jarvis.gui.server.features import GESTURE_AVAILABLE
from jarvis.gui.server.features import GeminiLiveEngine
from jarvis.gui.server.features import GestureController
from jarvis.gui.server.features import HABIT_TRACKER_AVAILABLE
from jarvis.gui.server.features import HANDLER_MAP
from jarvis.gui.server.features import HOTKEY_AVAILABLE
from jarvis.gui.server.features import HabitTracker
from jarvis.gui.server.features import HotkeySystem
from jarvis.gui.server.features import JARVISEntertainment
from jarvis.gui.server.features import JARVISUltimate
from jarvis.gui.server.features import JARVIS_AVAILABLE
from jarvis.gui.server.features import KNOWLEDGE_AVAILABLE
from jarvis.gui.server.features import KnowledgeLayer
from jarvis.gui.server.features import NEWS_AVAILABLE
from jarvis.gui.server.features import NOTES_AVAILABLE
from jarvis.gui.server.features import NewsHandler
from jarvis.gui.server.features import OCRHandler
from jarvis.gui.server.features import OCR_AVAILABLE
from jarvis.gui.server.features import PDFHandler
from jarvis.gui.server.features import PDF_AVAILABLE
from jarvis.gui.server.features import PERCEPTION_AVAILABLE
from jarvis.gui.server.features import PROACTIVE_AVAILABLE
from jarvis.gui.server.features import PerceptionLayer
from jarvis.gui.server.features import ProactiveAssistant
from jarvis.gui.server.features import REMINDER_AVAILABLE
from jarvis.gui.server.features import ROUTER_AVAILABLE
from jarvis.gui.server.features import ReminderManager
from jarvis.gui.server.features import SCREENSHOT_AVAILABLE
from jarvis.gui.server.features import SCREEN_CONTROL_AVAILABLE
from jarvis.gui.server.features import SYSTEM_CONTROL_AVAILABLE
from jarvis.gui.server.features import ScreenControlHandler
from jarvis.gui.server.features import ScreenshotHandler
from jarvis.gui.server.features import SmartNotes
from jarvis.gui.server.features import SystemControl
from jarvis.gui.server.features import TASK_MANAGER_AVAILABLE
from jarvis.gui.server.features import TaskManager
from jarvis.gui.server.features import WEATHER_AVAILABLE
from jarvis.gui.server.features import WELLNESS_AVAILABLE
from jarvis.gui.server.features import WHATSAPP_AVAILABLE
from jarvis.gui.server.features import WeatherHandler
from jarvis.gui.server.features import WellnessMonitor
from jarvis.gui.server.features import WhatsAppHandler
from jarvis.gui.server.features import YOUTUBE_AVAILABLE
from jarvis.gui.server.features import YouTubeDownloader
from jarvis.gui.server.features import get_brain_adapter

_log = logging.getLogger(__name__)


class BootMixin:
    """Startup: the core JARVIS instance, the fallback processor, and loading every subsystem (critical ones now, the rest in the background).

    Part of JARVISWebSocketServer (see jarvis/gui/websocket_server.py).
    """

    def _init_jarvis(self):
        """Initialize JARVISUltimate and all handlers"""
        _log.info("\n" + "="*60)
        _log.info("     JARVIS WebSocket Server - Full Integration")
        _log.info("="*60 + "\n")

        # Try to initialize full JARVIS
        if JARVIS_AVAILABLE:
            # We defer JARVISUltimate instantiation to Phase 2 to not block < 2s boot
            self.jarvis = None
            self._init_fallback()
        else:
            self._init_fallback()

        # Initialize standalone modules if not from JARVIS
        self._init_standalone_modules()

        # Initialize startup orchestrator for boot briefing
        self.startup_orchestrator = None
        try:
            from jarvis.core.startup_orchestrator import StartupOrchestrator
            boot_context = {
                "chat_history": getattr(self, '_chat_history', None),
                "weather_handler": getattr(self, 'weather_handler', None),
                "calendar": getattr(self, 'calendar', None),
                "reminder_manager": getattr(self, 'reminder_manager', None),
            }
            # Boot orchestrator - pass None for jarvis, it will handle it
            self.startup_orchestrator = StartupOrchestrator(None, boot_context)
            _log.info("[BOOT] Startup Orchestrator ready")
        except Exception as e:
            _log.warning(f"[BOOT] Startup Orchestrator error: {e}")

        _log.info("\n" + "="*60)
        _log.info("     Server Ready - All Features Initialized")
        _log.info("="*60 + "\n")


    def _init_fallback(self):
        """Initialize with individual components"""
        _log.info("[WebSocket] Using fallback initialization...")

        if PERCEPTION_AVAILABLE:
            try:
                self.perception = shared(PerceptionLayer)
                self.hud_perception.attach(self.perception)
                _log.info("[WebSocket] Perception layer initialized")
            except Exception as e:
                _log.warning(f"[WebSocket] Perception error: {e}")


    def _init_standalone_modules(self):
        """Initialize modules: CRITICAL ones immediately, DEFERRED ones in background.

        This cuts perceived startup from ~30s to ~10s by loading only essential
        modules first and deferring rarely-used ones to a background thread.
        """
        import time as _time
        start = _time.time()

        self._boot_critical_modules(_time, start)

        self._boot_deferred_modules(_time)

    def _boot_critical_modules(self, _time, start):
        """Step of _init_standalone_modules(): critical modules."""
        # ══════════════════════════════════════════════════════════════
        # PHASE 1: CRITICAL MODULES (sync — must be ready before server accepts clients)
        # ══════════════════════════════════════════════════════════════
        _log.info("[BOOT] Phase 1: Loading critical modules...")

        # Fast / Lightweight handlers
        if not getattr(self, 'news_handler', None) and NEWS_AVAILABLE:
            try:
                self.news_handler = shared(NewsHandler, lambda: NewsHandler(self.hud_perception))
            except Exception as e:
                recovered("WebSocket", e)

        if not getattr(self, 'weather_handler', None) and WEATHER_AVAILABLE:
            try:
                self.weather_handler = shared(WeatherHandler, lambda: WeatherHandler(self.hud_perception))
            except Exception as e:
                recovered("WebSocket", e)

        # Setup lazy property backings to None
        self._emotion_detector = None
        self._face_recognition = None
        self._gesture_controller = None
        self._chat_history = None
        self._context_memory = None
        self._knowledge = None
        self._ocr_handler = None
        self._pdf_handler = None
        self._youtube_downloader = None
        self._clipboard_intelligence = None


        # ContextMemory is created lazily by the `context_memory` property on
        # first use (it loads embeddings, so doing it here would slow boot).
        # The old eager assignment here always failed: the property has no setter.

        self._boot_hotkeys()

        # Reminders & Tasks
        if REMINDER_AVAILABLE:
            try:
                self.reminder_manager = shared(ReminderManager, lambda: ReminderManager(self.hud_perception))
                self.reminder_manager.start()
            except Exception: _log.debug("Ignored error", exc_info=True)

        if TASK_MANAGER_AVAILABLE:
            try:
                self.task_manager_obj = shared(TaskManager, lambda: TaskManager(self.hud_perception))
            except Exception: _log.debug("Ignored error", exc_info=True)

        # System control (needed for voice commands)
        if SYSTEM_CONTROL_AVAILABLE:
            try:
                self.system_control = shared(SystemControl, lambda: SystemControl(self.hud_perception))
            except Exception as e:
                _log.warning(f"[WebSocket] System control init error: {e}")

        # Screenshot (needed for read_screen tool)
        if SCREENSHOT_AVAILABLE:
            try:
                self.screenshot_handler = shared(ScreenshotHandler, lambda: ScreenshotHandler(self.hud_perception))
            except Exception as e:
                _log.warning(f"[WebSocket] Screenshot init error: {e}")

        # Gemini Live Engine (core AI voice — must start immediately)
        self.live_engine = None
        self._boot_gemini_live()

        if ROUTER_AVAILABLE:
            _log.info(f"[WebSocket] Intent routing ready (classify_intent + HANDLER_MAP with {len(HANDLER_MAP)} handlers)")

        critical_time = _time.time() - start
        _log.info(f"[BOOT] Phase 1 complete in {critical_time:.1f}s — server accepting connections")

    def _boot_deferred_modules(self, _time):
        """Step of _init_standalone_modules(): deferred modules."""
        # ══════════════════════════════════════════════════════════════
        # PHASE 2: DEFERRED MODULES (background ThreadPoolExecutor)
        # ══════════════════════════════════════════════════════════════
        def _prewarm_jarvis():
            if JARVIS_AVAILABLE:
                try:
                    # Build subsystems with the HUD perception and reuse every
                    # service the server already created (see core/services.py)
                    self.jarvis = JARVISUltimate(service_perception=self.hud_perception)
                    self.perception = self.jarvis.perception
                    self.hud_perception.attach(self.perception)
                    # Re-apply Gemini Live flag (lost when hud_perception was recreated)
                    if getattr(self, 'live_engine', None):
                        self.hud_perception._gemini_live_active = True
                    self.news_handler = self.jarvis.news_handler
                    self.weather_handler = self.jarvis.weather
                    if getattr(self, 'startup_orchestrator', None):
                        self.startup_orchestrator.jarvis = self.jarvis

                    # C-06: Force identity from voice_prefs.json after Phase 2
                    # Prevents FRIDAY from persisting when prefs say 'jarvis'
                    try:
                        _prefs_path = Path(__file__).parent.parent.parent / "data" / "voice_prefs.json"
                        if _prefs_path.exists():
                            import json as _jl
                            with open(_prefs_path) as _f:
                                _name = _jl.load(_f).get("assistant", "jarvis")
                            self.hud_perception.assistant_name = _name.upper()
                            self.hud_perception.is_friday = (_name.lower() == "friday")
                            _log.info(f"[BG LOAD] Forced identity: {_name.upper()}")
                    except Exception as _e:
                        _log.warning(f"[BG LOAD] Identity force failed (non-critical): {_e}")

                    _log.info("[BG LOAD] JARVIS core prewarmed")
                except Exception as e:
                    _log.warning(f"[BG LOAD ERROR] JARVIS core prewarming failed: {e}")

        def _load_deferred():
            defer_start = _time.time()
            _log.info("[BOOT] Phase 2: Loading deferred modules in background...")

            import concurrent.futures

            # Start JARVIS init directly in the background sequentially first
            _prewarm_jarvis()

            # ── Initialize Brain Adapter (wires advanced ML modules) ──
            if BRAIN_AVAILABLE:
                try:
                    self._brain = get_brain_adapter()
                    # COORD-FIX: Bridge brain state to UI state controller
                    if hasattr(self, 'state_manager') and self.state_manager:
                        self._brain.ui_state_controller = self.state_manager
                    _log.info("[BG LOAD] Brain Adapter initialized")
                    if hasattr(self, 'perception') and self.perception:
                        self._brain.start_perception_consumer(self.perception)
                        _log.info("[BG LOAD] Brain Perception Consumer started")
                except Exception as e:
                    _log.warning(f"[BG LOAD ERROR] Brain Adapter: {e}")
                    self._brain = None
            else:
                self._brain = None

            deferred_modules = [
                (EMOTION_AVAILABLE, '_emotion_detector', lambda: shared(EmotionDetector), "EmotionDetector"),
                (FACE_AVAILABLE, '_face_recognition', lambda: shared(FaceRecognition, lambda: FaceRecognition(self.hud_perception)), "FaceRecognition"),
                (GESTURE_AVAILABLE and self.gesture_enabled, '_gesture_controller', lambda: shared(GestureController, lambda: GestureController(self.hud_perception)), "GestureController"),
                (CHAT_HISTORY_AVAILABLE, '_chat_history', lambda: shared(ChatHistory, lambda: ChatHistory(self.hud_perception)), "ChatHistory"),
                (CONTEXT_MEMORY_AVAILABLE, '_context_memory', lambda: shared(ContextMemory), "ContextMemory"),
                (KNOWLEDGE_AVAILABLE, '_knowledge', lambda: shared(KnowledgeLayer, lambda: KnowledgeLayer(self.hud_perception)), "KnowledgeLayer"),
                (OCR_AVAILABLE, '_ocr_handler', lambda: shared(OCRHandler, lambda: OCRHandler(self.hud_perception)), "OCR"),
                (DICTIONARY_AVAILABLE, 'dictionary_handler', lambda: shared(DictionaryHandler, lambda: DictionaryHandler(self.hud_perception)), "Dictionary"),
                (ENTERTAINMENT_AVAILABLE, 'entertainment', lambda: shared(JARVISEntertainment, lambda: JARVISEntertainment(self.hud_perception, self.knowledge)), "Entertainment"),
                (NOTES_AVAILABLE, 'smart_notes', lambda: shared(SmartNotes, lambda: SmartNotes(self.hud_perception)), "Smart Notes"),
                (ALARM_AVAILABLE, 'alarm_system', lambda: shared(AlarmSystem, lambda: AlarmSystem(self.hud_perception)), "Alarm"),
                (SCREEN_CONTROL_AVAILABLE, 'screen_control', lambda: shared(ScreenControlHandler), "Screen Control"),
                (WHATSAPP_AVAILABLE, 'whatsapp_handler', lambda: shared(WhatsAppHandler, lambda: WhatsAppHandler(self.hud_perception)), "WhatsApp"),
                (CALENDAR_AVAILABLE, 'calendar', lambda: shared(CalendarIntegration, lambda: CalendarIntegration(self.hud_perception)), "Calendar"),
                (PROACTIVE_AVAILABLE, 'proactive_assistant', lambda: shared(ProactiveAssistant, lambda: ProactiveAssistant(self.hud_perception)), "Proactive"),
                (EMAIL_HANDLER_AVAILABLE, 'email_handler_obj', lambda: shared(EmailHandler, lambda: EmailHandler(self.hud_perception, getattr(self, '_knowledge', None))), "Email"),
                (YOUTUBE_AVAILABLE, '_youtube_downloader', lambda: shared(YouTubeDownloader, lambda: YouTubeDownloader(self.hud_perception)), "YouTube"),
                (HABIT_TRACKER_AVAILABLE, 'habit_tracker', lambda: shared(HabitTracker, lambda: HabitTracker(self.hud_perception)), "Habits"),
                (WELLNESS_AVAILABLE, 'wellness_monitor', lambda: shared(WellnessMonitor, lambda: WellnessMonitor(self.hud_perception)), "Wellness"),
                (PDF_AVAILABLE, '_pdf_handler', lambda: shared(PDFHandler, lambda: PDFHandler(self.hud_perception)), "PDF"),
                (CLIPBOARD_AVAILABLE, '_clipboard_intelligence', lambda: getattr(self, '_init_clipboard', lambda: None)(), "Clipboard"),
            ]

            def _load_module_safe(mod_def):
                available, attr_name, factory, label = mod_def
                if available and getattr(self, attr_name, None) is None:
                    try:
                        setattr(self, attr_name, factory())
                        _log.info(f"[BG LOAD] {label} loaded")
                        return True
                    except Exception as e:
                        _log.warning(f"[BG LOAD ERROR] {label}: {e}")
                return False

            loaded = 0
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                results = list(executor.map(_load_module_safe, deferred_modules))
                loaded = sum(1 for r in results if r)

            defer_time = _time.time() - defer_start
            _log.info(f"[BOOT] Phase 2 complete: deferred batch finished. {loaded} modules loaded in {defer_time:.1f}s")

        # Launch deferred loading in background thread
        self._deferred_thread = threading.Thread(
            target=_load_deferred,
            daemon=True,
            name="JARVISDeferredInit"
        )
        self._deferred_thread.start()


    def _boot_hotkeys(self):
        """Step of _init_standalone_modules(): hotkeys."""
        # Hotkeys (must register immediately)
        if HOTKEY_AVAILABLE:
            try:
                # C-05: Pass a proper callback so hotkeys actually work
                self.hotkey_system = shared(HotkeySystem, lambda: HotkeySystem(
                    self.hud_perception,
                    jarvis_callback=self._on_hotkey_action
                ))
            except Exception: _log.debug("Ignored error", exc_info=True)

    def _boot_gemini_live(self):
        """Step of _init_standalone_modules(): gemini live."""
        if GEMINI_LIVE_AVAILABLE:
            try:
                api_key = os.getenv("GEMINI_API_KEY")
                self.live_engine = GeminiLiveEngine(
                    api_key=api_key,
                    server=self
                )
                self.live_engine.start()
                if self.hud_perception:
                    self.hud_perception._gemini_live_active = True
                _log.info("[WebSocket] Gemini Live Engine Initialized & Started")
            except Exception as e:
                _log.warning(f"[WebSocket] Gemini Live Engine error: {e}")



    def _init_clipboard(self):
        """Create ClipboardIntelligence with HUD suggestion callback."""
        def _push_clipboard_suggestion(suggestion):
            # Through the per-client queues (this runs on the clipboard thread)
            try:
                self._dispatch_from_thread('sensors', {
                    'type': 'clipboard_suggestion',
                    'suggestion': suggestion.get('suggestion', ''),
                    'action': suggestion.get('action', ''),
                    'content_type': suggestion.get('type', ''),
                })
            except Exception as e:
                _log.warning(f"[CLIPBOARD] Suggestion push error: {e}")

        clip = ClipboardIntelligence(
            perception=self.hud_perception,
            on_suggestion=_push_clipboard_suggestion
        )
        clip.start()
        return clip
