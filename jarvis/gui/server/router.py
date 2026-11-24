"""
The intent router: brain/keyword classification, handler dispatch, and answering what no handler covers.
"""

import asyncio
import json
import logging
import re
import subprocess
import time
from datetime import datetime

from jarvis.core.services import shared
from jarvis.gui.command_rules import POWER_CONFIRM_WINDOW_S
from jarvis.gui.data_providers import maybe_title
from jarvis.gui.hud_types import turn_text
from jarvis.gui.server.features import HANDLER_MAP
from jarvis.gui.server.features import ROUTER_AVAILABLE
from jarvis.gui.server.features import classify_intent
from jarvis.gui.server.features import jlog
from jarvis.gui.server.tables import HUD_COMMANDS
from jarvis.gui.server.tables import NEWS_CATEGORIES
from jarvis.gui.server.tables import ROUTER_ERROR_PHRASES
from jarvis.gui.server.tables import _is_precise_rule

_log = logging.getLogger(__name__)

# Returned by an extracted step that didn't handle the request: the
# caller carries on with its next step.
_NEXT = object()


class RouterMixin:
    """The intent router: brain/keyword classification, handler dispatch, and answering what no handler covers.

    Part of JARVISWebSocketServer (see jarvis/gui/websocket_server.py).
    """

    # ── step 3: router, HUD features, AI ─────────────────────────────────
    async def _cmd_route_and_answer(self, cmd: str, command: str, title: str, websocket) -> str:
        # The router's handlers make blocking network calls (LLM, weather,
        # news): a worker thread, so one slow request can't freeze the server
        router_response = await self._run_blocking(self._route_through_router, command)
        if router_response and not any(ep in router_response for ep in ROUTER_ERROR_PHRASES):
            return router_response

        for category in NEWS_CATEGORIES:
            if category in cmd and ('news' in cmd or 'headlines' in cmd):
                news_data = self.get_news_data(category=category)   # also updates the news panel
                await self._send_to(websocket, json.dumps(news_data))
                items_text = ". ".join(news_data['items'][:3])
                return f"Here are the top {category} headlines, {title}: {items_text}"

        if any(p in cmd for p in HUD_COMMANDS):
            return await self._fallback_process(command, websocket)

        # General queries: the text model (see core/llm.py)
        from jarvis.core.llm import ask_gemini, gemini_client
        if gemini_client() is not None:
            try:
                reply = await asyncio.wait_for(self._run_blocking(ask_gemini, command), timeout=10.0)
            except asyncio.TimeoutError:
                _log.warning("[WebSocket] Gemini API timed out (10s)")
                reply = None
            if reply:
                return reply
            # The keyword fallback would answer an unrelated question with e.g.
            # a greeting ("translate hello..." -> "Good morning."). Be honest instead.
            return f"I couldn't reach the AI service just now{maybe_title(title)}. Please try again in a moment."

        return await self._fallback_process(command, websocket)   # no Gemini key: keywords


    def _route_through_router(self, command: str, force: bool = False) -> str:
        """Route command through direct handlers first, then IntentRouter.

        force=True skips the brain's clarification question (the user already
        answered 'yes' to it).
        """

        try:
            title = self.hud_perception.user_title

            # ══════════════════════════════════════════════════════════════
            # BRAIN-FIRST: Run through advanced ML pipeline before keywords
            # If the brain returns a valid high-confidence result, use its
            # intent + entities. Otherwise fall through to keyword engine.
            # ══════════════════════════════════════════════════════════════
            brain_result = None
            if getattr(self, '_brain', None):
                try:
                    brain_result = self._brain.process(command, source="voice")
                except Exception as be:
                    _log.warning(f"[WebSocket] Brain error (non-fatal): {be}")

            if brain_result and brain_result.is_valid:
                # Brain produced a confident result — use it
                # Translate ML intent names (get_time, volume_up …) to handler
                # names (time, volume …). If there is still no handler, use the
                # keyword classifier, which speaks HANDLER_MAP's names natively.
                from jarvis.core.intent_handlers import resolve_brain_intent
                intent_name, entities = resolve_brain_intent(brain_result.action,
                                                             brain_result.entities, command)
                # Names the router serves itself, outside HANDLER_MAP
                router_native = {'list_alarms', 'read_clipboard', 'next', 'previous', 'scroll'}
                kw_intent, kw_entities = classify_intent(command) if ROUTER_AVAILABLE else (None, {})
                if kw_intent != intent_name and _is_precise_rule(kw_intent, command):
                    # A precise keyword rule fired (an exact pattern with its own
                    # entities): it beats the ML guess. The brain called "news
                    # about diabetes" plain 'news' and the topic was lost; it
                    # sent "what is this" to web search.
                    intent_name, entities = kw_intent, kw_entities
                elif ROUTER_AVAILABLE and intent_name not in HANDLER_MAP and intent_name not in router_native:
                    if kw_intent in HANDLER_MAP:
                        intent_name, entities = kw_intent, kw_entities
                elif kw_intent == intent_name and kw_entities:
                    # Both layers agree: fill entities the ML extractor missed
                    # (e.g. the city in "weather in london") from the rule-based ones.
                    # For messages the rule parse wins: it reads contact and text
                    # straight from the sentence (the ML extractor returned the
                    # contact "message to mom").
                    if intent_name in ('send_message',):
                        entities = {**entities, **kw_entities}
                    else:
                        entities = {**kw_entities, **entities}
                if jlog: jlog.intent(f"BRAIN:{intent_name}", entities=entities)
                else: _log.info(f"[WebSocket] BRAIN Intent: {intent_name}, Entities: {entities}, Conf: {brain_result.confidence:.2f}")

                if brain_result.decision_type == 'refuse' and brain_result.decision_message:
                    return brain_result.decision_message
                # CLARIFY: the brain is unsure. If the rule-based keyword classifier
                # independently names a specific handler, that corroborates it:
                # proceed. Otherwise ask, and remember the command so "yes" runs it
                # (the question used to be a dead end).
                if brain_result.decision_type == 'clarify' and brain_result.decision_message and not force:
                    kw_intent, kw_entities = classify_intent(command) if ROUTER_AVAILABLE else (None, {})
                    if kw_intent == intent_name:
                        pass  # corroborated
                    elif kw_intent in HANDLER_MAP and kw_intent != 'conversation':
                        intent_name, entities = kw_intent, kw_entities
                    else:
                        self._pending_clarify = (command, time.time() + POWER_CONFIRM_WINDOW_S)
                        return brain_result.decision_message
                # If decision engine says WARN, prepend warning
                if brain_result.decision_type == 'warn' and brain_result.decision_message:
                    # Store warning to prepend to final response
                    self._brain_warning = brain_result.decision_message
            else:
                # Fallback to keyword-based classifier
                intent_name, entities = classify_intent(command)
                if jlog: jlog.intent(intent_name, entities=entities)
                else: _log.info(f"[WebSocket] Intent: {intent_name}, Entities: {entities}")

            # ══════════════════════════════════════════════════════════════
            # CONTEXT RESOLUTION: Disambiguate based on active_app
            # "next" → next_track (spotify) or next_page (pdf) etc.
            # ══════════════════════════════════════════════════════════════
            active_app = getattr(self.state_manager, 'active_app', None)

            # Clear stale context (5 min timeout)
            app_set_time = getattr(self.state_manager, '_active_app_time', 0)
            if active_app and (time.time() - app_set_time) > 300:
                active_app = None
                self.state_manager.active_app = None

            CONTEXT_MAP = {
                'next': {
                    'spotify': 'next_track', 'music': 'next_track',
                    'pdf': 'next_page', 'reader': 'next_page',
                    'browser': 'next_tab', 'chrome': 'next_tab',
                },
                'previous': {
                    'spotify': 'previous_track', 'music': 'previous_track',
                    'pdf': 'previous_page', 'reader': 'previous_page',
                },
                'scroll': {
                    'pdf': 'scroll_pdf', 'browser': 'scroll_page',
                },
            }

            intent_name = self._apply_app_context(CONTEXT_MAP, active_app, intent_name)

            # ══════════════════════════════════════════════════════════════
            # DIRECT HANDLERS: Critical system commands that MUST execute
            # These bypass the router to guarantee actual hardware control
            # ══════════════════════════════════════════════════════════════

            # --- VOLUME / BRIGHTNESS: the reply is what really happened ---
            if intent_name in ('volume', 'brightness') and self.system_control:
                text = f"{entities.get('action') or ''} {command}"
                return self.system_control.adjust(intent_name, text, entities.get('level'))

            # --- ALARM ---
            if intent_name == 'set_alarm' and self.alarm_system:
                from datetime import timedelta
                cmd_lower = command.lower()

                # Handle relative time: "5 minutes from now", "in 10 minutes"
                relative_match = re.search(r'(\d+)\s*(min|minute|minutes|hour|hours|hr|hrs)\s*(from now)?', cmd_lower)
                if relative_match:
                    amount = int(relative_match.group(1))
                    unit = relative_match.group(2)
                    if 'hour' in unit or 'hr' in unit:
                        alarm_time = datetime.now() + timedelta(hours=amount)
                    else:
                        alarm_time = datetime.now() + timedelta(minutes=amount)
                    time_str = alarm_time.strftime('%I:%M %p')
                    label = entities.get('label', 'Alarm')
                    result = self.alarm_system.set_alarm(time_str, label)
                    return result if isinstance(result, str) else f"Alarm set for {time_str} ({amount} {'hours' if 'hour' in unit else 'minutes'} from now), {title}."

                # Handle absolute time from entities. The ML entity extractor
                # gives time='07:00' (24h); the keyword classifier gives hour/minute.
                if entities.get('hour') is None and entities.get('time'):
                    tm = re.match(r'(\d{1,2}):(\d{2})', str(entities['time']))
                    if tm:
                        h24 = int(tm.group(1))
                        entities = {**entities, 'hour': (h24 % 12) or 12, 'minute': int(tm.group(2)),
                                    'period': 'PM' if h24 >= 12 else 'AM'}
                hour = entities.get('hour')
                minute = entities.get('minute', 0)
                period = entities.get('period', '')
                if hour is not None:
                    time_str = f"{hour}:{minute:02d} {period}".strip()
                    label = entities.get('label', 'Alarm')
                    result = self.alarm_system.set_alarm(time_str, label)
                    return result if isinstance(result, str) else f"Alarm set for {time_str}, {title}."

                return f"What time should I set the alarm for, {title}?"

            _r = self._route_list_alarms(intent_name, title)
            if _r is not _NEXT:
                return _r

            _r = self._route_open_app(entities, intent_name, title)
            if _r is not _NEXT:
                return _r

            # --- TOGGLE FEATURES (gesture, face, emotion) ---
            cmd_lower = command.lower()
            _r = self._route_feature_switches(cmd_lower, title)
            if _r is not _NEXT:
                return _r

            # --- MUSIC CONTROL ---
            if intent_name in ('play_music', 'pause_music', 'next_track', 'previous_track'):
                _r = self._route_music(command, intent_name, title)
                if _r is not _NEXT:
                    return _r

            # --- OCR / READ SCREEN ---
            # OCR: handled by HANDLER_MAP['ocr'] (handle_ocr). This inline copy
            # skipped the Tesseract availability check and said "No readable text".

            _r = self._route_read_clipboard(intent_name, title)
            if _r is not _NEXT:
                return _r

            return self._route_dispatch_handler(_r, command, entities, intent_name, title)

        except Exception as e:
            if jlog: jlog.error('Router pipeline failed', e)
            else:
                _log.warning(f"[WebSocket] Router error: {e}")
                import traceback
                traceback.print_exc()
            return None

    def _route_dispatch_handler(self, _r, command, entities, intent_name, title):
        """Step of _route_through_router(): dispatch handler."""
        # ══════════════════════════════════════════════════════════════
        # HANDLER_MAP DISPATCH: Direct handler lookup for all other intents
        # Time, date, greeting, joke, weather, story, etc.
        # ══════════════════════════════════════════════════════════════
        if ROUTER_AVAILABLE and intent_name in HANDLER_MAP:
            _r = self._route_handler_context(command, entities, intent_name, title)
            if _r is not _NEXT:
                return _r

        # No handler found - fall through
        return None


    def _route_music(self, command, intent_name, title):
        """Step of _route_through_router(): music."""
        if jlog: jlog.route('music', intent_name)
        try:
            from jarvis.core.music_handler import MusicHandler
            mh = shared(MusicHandler)
            result = mh.handle_command(command)
            if result:
                return result
        except Exception as e:
            _log.warning(f"[WebSocket] MusicHandler error: {e}")
        # Fallback: use media keys via ctypes
        try:
            from jarvis.core.music_handler import MediaKeyController
            mk = MediaKeyController()
            if intent_name == 'play_music':
                mk.play_pause()
                return f"Playing music, {title}."
            elif intent_name == 'pause_music':
                mk.play_pause()
                return f"Music paused, {title}."
            elif intent_name == 'next_track':
                mk.next_track()
                return f"Next track, {title}."
            elif intent_name == 'previous_track':
                mk.previous_track()
                return f"Previous track, {title}."
        except Exception as e:
            _log.warning(f"[WebSocket] MediaKey error: {e}")
        return _NEXT

    def _route_handler_context(self, command, entities, intent_name, title):
        """Step of _route_through_router(): handler context."""
        try:
            handler = HANDLER_MAP[intent_name]

            # Build handler context with all available subsystems
            handler_context = {
                'title': title,
                'system_stats': self.get_system_stats() if hasattr(self, 'get_system_stats') else {},
                'alarm_system': self.alarm_system,
                'screenshot_handler': self.screenshot_handler,
                'knowledge': self.knowledge,
                'state_manager': self.state_manager,
                'weather_handler': self.weather_handler,
                'news_handler': self.news_handler,
                'entertainment': self.entertainment,
                'system_control': self.system_control,
                'reminder_manager': getattr(self, 'reminder_manager', None),
                'whatsapp_handler': getattr(self, 'whatsapp_handler', None),
                'perception': self.hud_perception,
                'face_auth': getattr(self, 'face_recognition', None),
                'ai_search': self.knowledge,  # KnowledgeLayer doubles as AI search
                'ocr_handler': self.ocr_handler,  # P2-wire: OCR via lazy property
            }

            if jlog: jlog.route('HANDLER_MAP', intent_name)
            else: _log.info(f"[WebSocket] HANDLER_MAP dispatch: {intent_name}")

            result = handler(command, entities, handler_context)

            # A handler that spoke its answer (news search, weather report)
            # returns "" with should_speak=False. That is an answer: use what
            # it said. Treating it as "no handler" made the AI answer again,
            # so the user heard two different replies.
            if result and result.success and not result.response:
                result.response = turn_text()

            _r = self._route_handler_side_effects(result)
            if _r is not _NEXT:
                return _r
        except Exception as e:
            if jlog: jlog.error(f'Handler dispatch failed: {intent_name}', e)
            else: _log.warning(f"[WebSocket] Handler error for {intent_name}: {e}")
        return _NEXT

    def _route_handler_side_effects(self, result):
        """Step of _route_handler_context(): handler side effects."""
        if result and result.success and result.response:
            # Handle side-effects from handler data
            if result.data:
                data_type = result.data.get('type', '')
                if data_type == 'switch_voice':
                    voice = result.data.get('voice', 'jarvis')
                    if voice == 'friday':
                        self.hud_perception.switch_to_friday()
                    else:
                        self.hud_perception.switch_to_jarvis()
                # COORD-FIX: Forward news/weather data to HUD
                elif data_type == 'news' and result.data.get('items'):
                    # The router runs in a worker thread, so hand the
                    # update to the event loop. (This called a
                    # _broadcast() that doesn't exist: the news reply
                    # was built, then thrown away by the AttributeError,
                    # and the AI was asked instead. The HUD's news
                    # panel listens for type 'news'.)
                    self._dispatch_from_thread('stats', {
                        'type': 'news',
                        'items': result.data['items'],
                        'category': result.data.get('category', ''),
                    })
            return result.response
        return _NEXT



    def _apply_app_context(self, CONTEXT_MAP, active_app, intent_name):
        """Step of _route_through_router(): app context."""
        if intent_name in CONTEXT_MAP and active_app:
            app_key = active_app.lower()
            mapping = CONTEXT_MAP[intent_name]
            for key, resolved in mapping.items():
                if key in app_key:
                    if jlog: jlog.intent(f'{intent_name}→{resolved}', context=active_app)
                    intent_name = resolved
                    break
        return intent_name

    def _route_list_alarms(self, intent_name, title):
        """Step of _route_through_router(): List_alarms."""
        if intent_name == 'list_alarms' and self.alarm_system:
            alarms = self.alarm_system.scheduler.get_all()
            if not alarms:
                return f"No active alarms, {title}."
            alarm_list = ", ".join([f"{a.label} at {a.trigger_time.strftime('%I:%M %p')}" for a in alarms])
            return f"Active alarms: {alarm_list}, {title}."
        return _NEXT

    def _route_open_app(self, entities, intent_name, title):
        """Step of _route_through_router(): OPEN APP."""
        # --- OPEN APP ---
        if intent_name == 'open_app':
            app_name = entities.get('app', '')
            if app_name:
                try:
                    from jarvis.core.app_finder import AppFinder
                    finder = shared(AppFinder)
                    success = finder.open_app(app_name)
                    if success:
                        self.state_manager.active_app = app_name.lower()
                        self.state_manager._active_app_time = time.time()
                        if jlog: jlog.state(active_app=app_name.lower())
                        return f"Opening {app_name}, {title}."
                    else:
                        return f"Couldn't find {app_name}, {title}. Try the full name."
                except Exception as e:
                    if jlog: jlog.error(f'App open failed: {app_name}', e)
                    else: _log.warning(f"[WebSocket] App open error: {e}")
                    return f"Had trouble opening {app_name}, {title}."
        return _NEXT

    def _route_read_clipboard(self, intent_name, title):
        """Step of _route_through_router(): READ CLIPBOARD."""
        # --- READ CLIPBOARD ---
        if intent_name == 'read_clipboard':
            try:
                text = subprocess.run(['powershell', '-command', 'Get-Clipboard'],
                                     capture_output=True, text=True, timeout=5).stdout.strip()
                if text:
                    short_text = text[:300] + '...' if len(text) > 300 else text
                    return f"Clipboard contains: {short_text}"
                return f"Clipboard is empty, {title}."
            except Exception as e:
                return f"Clipboard error: {e}"
        return _NEXT


    def _route_feature_switches(self, cmd_lower, title):
        """Step of _route_through_router(): feature switches."""
        if any(w in cmd_lower for w in ['enable', 'disable', 'turn on', 'turn off', 'start', 'stop']):
            enabling = any(w in cmd_lower for w in ['enable', 'turn on', 'start'])

            if 'gesture' in cmd_lower:
                if jlog: jlog.route('feature_toggle', 'gesture')
                return self.set_gesture_enabled(enabling, title)

            elif 'face' in cmd_lower:
                if jlog: jlog.route('feature_toggle', 'face')
                self.face_enabled = enabling
                if enabling and self.face_recognition:
                    self.face_recognition.start_monitoring()
                elif self.face_recognition:
                    self.face_recognition.stop_monitoring()
                return f"Face recognition {'enabled' if enabling else 'disabled'}, {title}."

            elif 'emotion' in cmd_lower or 'mood' in cmd_lower:
                if jlog: jlog.route('feature_toggle', 'emotion')
                self.emotion_enabled = enabling
                return f"Emotion detection {'enabled' if enabling else 'disabled'}, {title}."
        return _NEXT

