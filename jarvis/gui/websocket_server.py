"""
JARVIS WebSocket server: the gateway between the browser HUD and JARVIS.

The server is one class, JARVISWebSocketServer, assembled from parts that each
own one responsibility (jarvis/gui/server/):

    messages     every incoming HUD message (process_message), mood tracking
    router       intent classification and handler dispatch
    commands     local commands, one command = one turn (process_command)
    pending      questions awaiting an answer (PC power, WhatsApp drafts)
    speech       voice output: one owner per reply, announcements, stop
    gestures     camera gestures
    voice_input  the server's own microphone loop
    boot         loading subsystems (critical now, the rest in the background)
    services     subsystems loaded on first use
    transport    per-client send queues, channels, thread-safe dispatch
    features     optional imports and their *_AVAILABLE flags
    tables       command tables and phrase lists

This file keeps start-up (paths, .env), client connections (handle_client) and
the server's lifecycle. Run it directly to start the server:

    python jarvis/gui/websocket_server.py
"""

import asyncio
import json
import logging
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import websockets

_log = logging.getLogger(__name__)

# ── Paths: `from jarvis...` must work however this file is started ──────────
# Adds the project root (parent of jarvis/) to sys.path. jarvis/ itself must
# NOT be on sys.path: that let modules load twice, as core.X and jarvis.core.X
# (see jarvis/__init__.py).
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))
_log.info(f"[WebSocket] Project root: {_project_root}")

# ── API keys from .env, before any feature module reads them ────────────────
try:
    from dotenv import load_dotenv
    env_path = _project_root / ".env"
    load_dotenv(env_path)
    _log.info(f"[WebSocket] Loaded .env from {env_path}")
except ImportError:
    _log.info("[WebSocket] python-dotenv not installed, using system env vars")

from jarvis.gui.command_rules import (  # noqa: E402
    ALLOWED_WS_ORIGINS,
    HUD_HTTP_PORT,
    check_ws_token,
    is_urgent_message,
)
from jarvis.gui.data_providers import (  # noqa: E402
    get_news_data as _get_news_data,
    get_system_stats as _get_system_stats,
    get_weather_data as _get_weather_data,
)
from jarvis.gui.fallback_processor import FallbackProcessor  # noqa: E402
from jarvis.gui.hud_types import HUDPerception  # noqa: E402
from jarvis.gui.state_controller import UIStateController as StateManager  # noqa: E402

# Optional features (each import may fail and switch its feature off)
from jarvis.gui.server.features import GESTURE_AVAILABLE  # noqa: E402

# The server, by responsibility
from jarvis.gui.server.boot import BootMixin  # noqa: E402
from jarvis.gui.server.commands import CommandsMixin  # noqa: E402
from jarvis.gui.server.gestures import GestureMixin  # noqa: E402
from jarvis.gui.server.messages import MessageMixin  # noqa: E402
from jarvis.gui.server.pending import PendingMixin  # noqa: E402
from jarvis.gui.server.router import RouterMixin  # noqa: E402
from jarvis.gui.server.services import ServicesMixin  # noqa: E402
from jarvis.gui.server.speech import SpeechMixin  # noqa: E402
from jarvis.gui.server.tables import _gesture_mp_available  # noqa: E402
from jarvis.gui.server.transport import TransportMixin  # noqa: E402
from jarvis.gui.server.voice_input import VoiceInputMixin  # noqa: E402

# Importable from here too, as before the split (tests and older callers)
from jarvis.gui.command_rules import (  # noqa: E402,F401
    detect_pc_power_action,
    is_jarvis_exit_command,
    normalize_command,
)
from jarvis.gui.server.features import MISSING_IMPORTS  # noqa: E402,F401
from jarvis.gui.server.tables import FEATURE_TOGGLE_RE, _is_precise_rule  # noqa: E402,F401

__all__ = [
    "JARVISWebSocketServer", "HUDPerception",
    # importable from here, as before the split
    "MISSING_IMPORTS", "FEATURE_TOGGLE_RE", "_is_precise_rule",
    "normalize_command", "is_jarvis_exit_command", "detect_pc_power_action",
]


def _display_time(ts) -> str:
    """'Nov 23, 11:23 AM' from a datetime or an ISO string (chat history stores
    strings; .strftime() on one crashed the conversation search)."""
    from datetime import datetime as _dt
    if not ts:
        return ""
    if isinstance(ts, str):
        try:
            ts = _dt.fromisoformat(ts)
        except ValueError:
            return ts
    return ts.strftime('%b %d, %I:%M %p')


class JARVISWebSocketServer(MessageMixin, RouterMixin, CommandsMixin, PendingMixin, SpeechMixin,
                            GestureMixin, VoiceInputMixin, BootMixin, ServicesMixin, TransportMixin):
    """WebSocket server with FULL JARVISUltimate integration"""
    
    def __init__(self, host="localhost", port=8765):
        # DEBUG LOGGING
        self.log_file = os.path.join(os.path.dirname(__file__), "server_debug.log")
        with open(self.log_file, "w") as f:
            f.write(f"[{datetime.now()}] Server initializing...\n")
            
        def log(msg):
            with open(self.log_file, "a") as f:
                f.write(f"[{datetime.now()}] {msg}\n")
        self.log = log
        
        self.log("Starting __init__")
        self.host = host
        self.port = port
        # Pending PC shutdown/restart awaiting the user's 'confirm': (action, expires_at)
        self._pending_power_action = None
        self.clients = set()
        self._client_channels = {}   # {websocket: set('command','stats','live','sensors')}
        self._client_queues = {}     # {websocket: asyncio.Queue} — per-client backpressure
        self._recent_result_text = ''  # For cross-pipeline dedup
        self._recent_result_time = 0
        self._last_stats_hash = ''  # Delta compression for periodic updates
        self.running = False
        self._voice_thread = None
        self._voice_loop = None  # asyncio event loop ref for cross-thread injection
        self._gesture_thread = None
        
        # Core JARVIS instance
        self.jarvis = None
        
        # HUD perception wrapper. Speech outside a command (alarms, reminders,
        # hotkeys) goes to _announce, the single place that shows and voices it.
        self.hud_perception = HUDPerception()
        self.hud_perception.announcer = self._announce

        # Feature handlers
        self.perception = None
        self.weather_handler = None
        self.news_handler = None
        self.system_status = None
        self._gesture_controller = None
        self._face_recognition = None
        self._emotion_detector = None
        
        # NEW: Additional feature handlers
        self.screenshot_handler = None
        self._ocr_handler = None
        self.dictionary_handler = None
        self.email_handler = None
        self.entertainment = None
        self.smart_notes = None
        self.alarm_system = None
        self.system_control = None
        self._knowledge = None  # Groq / OpenRouter / Gemini answers
        self.reminder_manager = None  # For reminders
        self.screen_control = None  # Screen mouse/keyboard control
        self._pdf_handler = None  # PDF reader/extraction
        
        # NEW: Additional feature handlers
        self.whatsapp_handler = None  # WhatsApp messaging
        self.calendar = None  # Google Calendar
        self.proactive_assistant = None  # Proactive suggestions
        self.email_handler_obj = None  # Email/Gmail handler
        self._youtube_downloader = None  # YouTube download
        self.hotkey_system = None  # Global hotkeys
        self._chat_history = None  # SQLite FTS5 chat history
        self._context_memory = None  # Context memory for conversations
        self.habit_tracker = None  # Daily habits
        self.task_manager_obj = None  # Tasks and reminders
        self.wellness_monitor = None  # Health reminders
        self._clipboard_intelligence = None  # Clipboard monitoring
        
        # IntentRouter for clean command routing
        self.router = None
        self.is_speaking = False  # Gesture controller needs this
        
        # State tracking
        self.current_user = None
        self.current_emotion = None
        self.last_gesture = None
        
        # ALL FEATURES AUTO-ENABLED ON STARTUP (fully operational JARVIS)
        # Gestures open the camera: on at boot only if the user turned them on
        # last time (or JARVIS_GESTURES=1). They used to claim "on from boot"
        # while never actually running.
        self.gesture_enabled = self._load_gesture_pref()
        self.face_enabled = True      # Always-on: face recognition
        self.emotion_enabled = True   # Always-on: emotion detection
        
        # Mute control - palm gesture can mute JARVIS
        self.muted_by_gesture = False  # Palm closed = JARVIS silent
        
        # CLEAN ARCHITECTURE: Centralized state manager (replaces manual deduplication)
        self.state_manager = StateManager()
        # The HUD's gesture switch shows the state manager's flag, which was
        # hard-coded on: the HUD said gestures were on while the camera was off
        self.state_manager.gesture_enabled = self.gesture_enabled

        # Thread pool for async-safe heavy execution
        self.executor = ThreadPoolExecutor(max_workers=4)
        
        # Instantiate fallback command processor
        self.fallback_processor = FallbackProcessor(self)
        
        # Initialize everything
        self.log("Calling _init_jarvis")
        self._init_jarvis()
        self.log("__init__ complete")
    
    def recall_conversation(self, query: str) -> str:
        """Search chat history for past conversations matching query."""
        if not self.chat_history:
            return "Chat history not ready yet, sir."
        try:
            results = self.chat_history.search(query, limit=5)
            if not results:
                return f"No conversations found matching '{query}'."
            
            lines = [f"Found {len(results)} relevant conversation(s):"]
            for msg in results:
                role = "You" if msg.role == 'user' else "JARVIS"
                ts = _display_time(getattr(msg, 'timestamp', None))
                # Chat messages keep their words in .content (.text doesn't exist,
                # so the search used to read out "ChatMessage(id=857, ...)")
                text = (getattr(msg, 'content', None) or getattr(msg, 'text', '') or '')[:150]
                lines.append(f"  [{ts}] {role}: {text}")
            return "\n".join(lines)
        except Exception as e:
            return f"Search error: {e}"
    
    def get_system_stats(self):
        """Get current system statistics — delegates to data_providers."""
        return _get_system_stats()
    
    def get_weather_data(self, city=None):
        """Get weather data — delegates to data_providers."""
        return _get_weather_data(weather_handler=self.weather_handler, city=city)
    
    def get_news_data(self, category='general', count=5, location=None):
        """Get news headlines — delegates to data_providers."""
        return _get_news_data(news_handler=self.news_handler, category=category,
                              count=count, location=location)
    
    def get_feature_status(self):
        """Get status of all advanced features"""
        sm = self.state_manager
        return {
            'type': 'feature_status',
            'jarvis_full': self.jarvis is not None,
            'gesture_available': GESTURE_AVAILABLE and _gesture_mp_available(),  # never loads MediaPipe
            'gesture_enabled': self.gesture_enabled,
            'face_available': self.face_recognition is not None,
            'face_enabled': self.face_enabled,
            'emotion_available': self.emotion_detector is not None,
            'emotion_enabled': self.emotion_enabled,
            'current_user': self.current_user,
            'current_emotion': self.current_emotion,
            'last_gesture': getattr(sm, 'last_gesture', None) or self.last_gesture,
            'whatsapp_available': self.whatsapp_handler is not None,
            'active_app': getattr(sm, 'active_app', None),
            'current_mood': getattr(sm, 'current_mood', None),
            'mood_confidence': getattr(sm, 'mood_confidence', None),
            'emotion_vector': getattr(sm, 'emotion_vector', None),
            'fatigue_score': getattr(sm, 'fatigue_score', None),
            'attention_score': getattr(sm, 'attention_score', None),
        }
    
    async def handle_client(self, websocket, path=None):
        """Handle a client connection"""
        self.clients.add(websocket)
        # Subscribe to all channels by default
        self._client_channels[websocket] = {'command', 'stats', 'live', 'sensors'}
        # Per-client queue for backpressure (maxsize=50)
        self._client_queues[websocket] = asyncio.Queue(maxsize=50)
        client_id = id(websocket)
        _log.info(f"[WebSocket] Client connected: {client_id}")
        
        # Start per-client sender loop (drains queue → ws.send)
        sender_task = asyncio.create_task(self._client_sender(websocket))
        stats_task = None

        # Commands run one at a time, in order, on a per-client worker, so the
        # reader below never waits on a slow command. "stop" and state queries
        # are answered immediately; before, they queued behind e.g. a 15 s AI call.
        command_queue = asyncio.Queue(maxsize=20)

        async def _command_worker():
            while True:
                queued = await command_queue.get()
                try:
                    await self.process_message(websocket, queued)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    _log.warning(f"[WebSocket] Command error: {e}")

        worker_task = asyncio.create_task(_command_worker())

        try:
            await self._send_init_payload(websocket)
            
            # Start periodic updates
            stats_task = asyncio.create_task(self.send_periodic_updates(websocket))
            
            async for message in websocket:
                try:
                    data = json.loads(message)
                    if not isinstance(data, dict):
                        continue
                    # Handle channel subscription messages
                    if data.get('type') == 'subscribe':
                        channels = data.get('channels', [])
                        if channels:
                            self._client_channels[websocket] = set(channels)
                        continue
                    if is_urgent_message(data):
                        await self.process_message(websocket, data)
                        continue
                    try:
                        command_queue.put_nowait(data)
                    except asyncio.QueueFull:
                        await self._send_to(websocket, {
                            'type': 'error',
                            'message': 'Still working on your earlier commands. Try again in a moment.'})
                except json.JSONDecodeError:
                    _log.warning("[WebSocket] Invalid JSON")
                except Exception as e:
                    _log.warning(f"[WebSocket] Error: {e}")

        except websockets.exceptions.ConnectionClosed:
            _log.info(f"[WebSocket] Client disconnected: {client_id}")
        finally:
            # Cancel this client's tasks however the connection ended. The stats
            # task used to be cancelled only on a clean close, so every dropped
            # connection left one polling stats/weather/news forever, and
            # reconnects piled them up.
            worker_task.cancel()
            if stats_task is not None:
                stats_task.cancel()
            sender_task.cancel()
            self.clients.discard(websocket)
            self._client_channels.pop(websocket, None)
            self._client_queues.pop(websocket, None)
            # Save session state on disconnect for next boot
            if self.startup_orchestrator:
                try:
                    self.startup_orchestrator.save_session()
                    _log.info("[BOOT] Session state saved on disconnect")
                except Exception as e:
                    _log.warning(f"[BOOT] Session save error: {e}")

    async def _send_init_payload(self, websocket):
        """Send a new client everything the HUD shows at start: greeting,
        briefing, stats, weather, news and feature status, in one message."""
        # ══════ BOOT SEQUENCE: Batched single payload ══════
        name = self.hud_perception.assistant_name

        # Generate boot briefing from orchestrator
        boot_briefing = None
        if self.startup_orchestrator:
            try:
                boot_briefing = await self._run_blocking(
                    self.startup_orchestrator.generate_boot_briefing)
                _log.info(f"[BOOT] Briefing generated: {boot_briefing.get('greeting', '')[:60]}")
            except Exception as e:
                _log.warning(f"[BOOT] Briefing error: {e}")

        # Build greeting for HUD chat panel (always shown — Gemini Live handles audio separately)
        greeting_text = None
        greeting_text = self._greeting_text(boot_briefing, greeting_text, name)

        # ━━━ SINGLE BATCHED INIT PAYLOAD (1 send instead of 6) ━━━
        # Weather and news are network calls and stats sample the CPU for
        # 0.1 s: gather them in worker threads, concurrently. On the event loop
        # they froze every client and the keepalive pings, and the resulting
        # disconnect/reconnect cycle re-ran them (the "overloaded" socket).
        stats, weather, news = await asyncio.gather(
            self._run_blocking(self.get_system_stats),
            self._run_blocking(self.get_weather_data),
            self._run_blocking(self.get_news_data),
        )
        init_payload = {
            'type': 'init_payload',
            'assistant_info': {'name': name, 'is_friday': self.hud_perception.is_friday},
            'system_stats': stats,
            'weather': weather,
            'news': news,
            'features': self.get_feature_status(),
        }
        self._client_greet_aloud(greeting_text, init_payload)
        if boot_briefing:
            init_payload['briefing'] = boot_briefing

        await self._send_to(websocket, init_payload)

    def _greeting_text(self, boot_briefing, greeting_text, name):
        """Step of handle_client(): text."""
        if boot_briefing:
            greeting_text = boot_briefing.get('spoken_briefing', f'{name} online, sir.')
        else:
            hour = datetime.now().hour
            greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"
            greeting_text = f'{greeting}, sir. {name} online. How can I help you?'
        return greeting_text

    def _client_greet_aloud(self, greeting_text, init_payload):
        """Step of handle_client(): greet aloud."""
        if greeting_text:
            # Greet aloud once per run, not on every reconnect. In live mode
            # Gemini greets by itself.
            _greet_speak = False
            if not getattr(self, '_greeted_aloud', False) and not self._live_ready() \
                    and not getattr(self, 'live_engine', None):
                self._greeted_aloud = True
                _greet_speak = not self._voice_reply(greeting_text)
            init_payload['greeting'] = {'text': greeting_text, 'speak': _greet_speak}

    
    async def start(self):
        """Start the server"""
        with open(self.log_file, "a") as f:
            f.write(f"[{datetime.now()}] Entering start()\n")
            
        self.running = True
        _log.info(f"\n{'='*55}")
        _log.info(f"  {self.hud_perception.assistant_name} WebSocket Server")
        _log.info(f"{'='*55}")
        _log.info(f"  Address: ws://{self.host}:{self.port}")
        _log.info("  Status:  Online")
        _log.info(f"  Voice:   {self.hud_perception.assistant_name}")
        _log.info(f"  Full JARVIS: {'Yes' if self.jarvis else 'Fallback Mode'}")
        _log.info(f"  Gesture: {'Available' if self.gesture_controller else 'Not Available'}")
        _log.info(f"  Face:    {'Available' if self.face_recognition else 'Not Available'}")
        _log.info(f"  Emotion: {'Available' if self.emotion_detector else 'Not Available'}")
        _log.info(f"{'='*55}\n")
        
        try:
            with open(self.log_file, "a") as f:
                f.write(f"[{datetime.now()}] Starting websockets.serve on {self.host}:{self.port}\n")
            
            # Store event loop ref so voice thread can inject coroutines
            self._voice_loop = asyncio.get_event_loop()
            
            # Start voice listening thread
            self._start_voice_thread()
            
            # Start gesture processing thread
            self._start_gesture_thread()
                
            # SECURITY: only the local HUD page (or a non-browser local client,
            # which sends no Origin header) may connect. Without this check any
            # website open in the user's browser could drive JARVIS via
            # ws://localhost:8765 and run commands on this PC.
            # SECURITY (2): every client must also present the per-session token
            # (injected into the HUD page / read by local Python clients).
            async with websockets.serve(self.handle_client, self.host, self.port,
                                        origins=ALLOWED_WS_ORIGINS,
                                        process_request=check_ws_token):
                with open(self.log_file, "a") as f:
                    f.write(f"[{datetime.now()}] Server running, waiting for connections...\n")
                await asyncio.Future()
        except Exception as e:
            with open(self.log_file, "a") as f:
                f.write(f"[{datetime.now()}] Error in start(): {e}\n")
            _log.warning(f"[WebSocket] Error in start: {e}")
            import traceback
            traceback.print_exc()

    def run_in_thread(self):
        """Run in background thread"""
        with open(self.log_file, "a") as f:
            f.write(f"[{datetime.now()}] run_in_thread called\n")
            
        def run():
            try:
                with open(self.log_file, "a") as f:
                    f.write(f"[{datetime.now()}] Thread started, calling asyncio.run\n")
                asyncio.run(self.start())
            except Exception as e:
                with open(self.log_file, "a") as f:
                    f.write(f"[{datetime.now()}] Thread crashed: {e}\n")
                    
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread


if __name__ == "__main__":
    # Serve the HUD too: it carries the session token the WebSocket requires.
    from jarvis.gui.web_hud_launcher import start_http_server
    start_http_server(HUD_HTTP_PORT)
    server = JARVISWebSocketServer()
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        _log.info("\n[WebSocket] Server stopped")
