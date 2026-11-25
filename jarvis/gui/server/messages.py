"""
Incoming HUD messages: one entry point (process_message) for typed, spoken and button input, plus mood tracking.
"""

import asyncio
import json
import logging
import os
import psutil

from jarvis.core.errors import recovered
from jarvis.gui.command_rules import CANCEL_RE
from jarvis.gui.command_rules import CONFIRM_RE
from jarvis.gui.command_rules import detect_pc_power_action
from jarvis.gui.command_rules import is_jarvis_exit_command
from jarvis.gui.command_rules import normalize_command
from jarvis.gui.hud_types import command_turn
from jarvis.gui.mood_engine import MoodTracker
from jarvis.gui.mood_engine import adapt_response_to_mood as _adapt_response_to_mood
from jarvis.gui.mood_engine import detect_mood_from_text as _detect_mood_from_text
from jarvis.gui.mood_engine import infer_action_from_text as _infer_action_from_text
from jarvis.gui.mood_engine import reduce_sir_usage as _reduce_sir_usage
from jarvis.gui.server.features import jlog
from jarvis.gui.server.tables import FEATURE_TOGGLE_RE

from jarvis.core.typo_fix import fix_typos

_log = logging.getLogger(__name__)

# Returned by an extracted step that didn't handle the request: the
# caller carries on with its next step.
_NEXT = object()


class MessageMixin:
    """Incoming HUD messages: one entry point (process_message) for typed, spoken and button input, plus mood tracking.

    Part of JARVISWebSocketServer (see jarvis/gui/websocket_server.py).
    """

    async def process_message(self, websocket, data):
        """Process incoming message using clean gateway architecture

        PROTOCOL:
        - Input: text_input, voice_input, command → all go to handle_input
        - Output: result (with action/response/confidence/state) + state updates
        """
        msg_type = data.get('type', '')
        # (A "hard gate" here used to drop every text_input whenever a live
        # engine object existed, even while it was disconnected, so typed
        # commands got no answer at all. The voice clash guard and live routing
        # below handle live mode, and fall back to the local pipeline when the
        # Gemini session is down.)

        _r = await self._on_stop_speaking(msg_type, websocket)
        if _r is not _NEXT:
            return _r

        # ═══════════════════════════════════════════════════════════════
        # UNIFIED INPUT HANDLER: text_input / voice_input / command
        # All user input flows through the same brain path
        # ═══════════════════════════════════════════════════════════════
        if msg_type in ('text_input', 'voice_input', 'command', 'chat'):
            _r = await self._on_input(data, msg_type, websocket)
            if _r is not _NEXT:
                return _r

        elif msg_type == 'switch_voice':
            await self._on_switch_voice(data, websocket)

        elif msg_type == 'get_status':
            await self._send_to(websocket, json.dumps(self.get_system_stats()))

        elif msg_type == 'get_state':
            # NEW: Broadcast complete JARVIS state - UI mirrors this
            await self._on_get_state(websocket)

        elif msg_type == 'get_weather':
            city = data.get('city')
            await self._send_to(websocket, json.dumps(self.get_weather_data(city)))

        elif msg_type == 'get_news':
            category = data.get('category', 'general')
            location = data.get('location')
            await self._send_to(websocket, json.dumps(self.get_news_data(category, location=location)))

        elif msg_type == 'globe_hover':
            # Handle globe location hover
            location = data.get('location', '')
            if location:
                news = self.get_news_data(location=location)
                await self._send_to(websocket, json.dumps(news))

        elif msg_type == 'toggle_feature':
            # Toggle gesture/face/emotion features
            await self._on_toggle_feature(data, websocket)

        elif msg_type == 'get_features':
            await self._send_to(websocket, json.dumps(self.get_feature_status()))

    async def _on_stop_speaking(self, msg_type, websocket):
        """Step of process_message(): stop speaking."""
        # ═══════════════════════════════════════════════════════════════
        # SPEECH INTERRUPTION: Stop JARVIS mid-speech
        # Gesture (palm) or explicit 'stop' command stops TTS immediately
        # ═══════════════════════════════════════════════════════════════
        if msg_type == 'stop_speaking':
            self._stop_speaking()
            self.state_manager.force_state("idle")
            await self._send_to(websocket, json.dumps({
                'type': 'state',
                'state': self.state_manager.get_full_state()
            }))
            return
        return _NEXT

    async def _on_input(self, data, msg_type, websocket):
        """Step of process_message(): input."""
        text = data.get('text', '') or data.get('payload', {}).get('text', '')

        # ── VOICE CLASH GUARD ─────────────────────────────────────
        # When Gemini Live is running, it owns the microphone and
        # produces its own audio responses.  The HUD still transcribes
        # speech and sends voice_input, which would create a SECOND
        # response path (text→TTS) clashing with the native audio.
        # Block that path here; text_input / command / chat still work.
        # ──────────────────────────────────────────────────────────
        _live_active = self._live_ready()
        _r = self._on_voice_input(_live_active, msg_type, text)
        if _r is not _NEXT:
            return _r

        # C-01: When Gemini Live is active, route text/command/chat INTO the live session
        # instead of running the legacy command pipeline. This prevents dual responses.
        # EXCEPTION: Local shutdown/exit commands bypass routing to guarantee clean termination.
        # Power commands and confirmations are handled locally (never by the LLM).
        is_local_power = False
        is_local_power = self._on_feature_switches(is_local_power, text)

        _r = self._on_input_chat(_live_active, is_local_power, msg_type, text)
        if _r is not _NEXT:
            return _r
        if not text:
            return

        if jlog: jlog.input(msg_type, text)
        else: _log.info(f"[WebSocket] Input ({msg_type}): {text}")

        _r = self._on_duplicate_speech(msg_type, text)
        if _r is not _NEXT:
            return _r

        # Update state: processing (skip intermediate 'listening' broadcast)
        self.state_manager.force_state("processing")
        self.state_manager.update_intent(msg_type, 0.0)

        # Mood: from the user's words (face too, if a face model is
        # installed); it lasts a few minutes and the AI is told about it
        # Typos in command words ("wether", "tiem") went to the AI chat
        text = fix_typos(text)
        mood = self._update_mood(text)

        # State: processing
        self.state_manager.force_state("processing")

        # ═══════════════════════════════════════════════════════════════
        # FAST PATH: Instant execution for common commands
        # Skips heavy routing chain — sub-100ms response
        # ═══════════════════════════════════════════════════════════════
        with command_turn() as fast_said:
            fast_response = self._try_fast_path(text)
        if fast_response is None and fast_said:
            fast_response = " ".join(fast_said)

        # ═══════════════════════════════════════════════════════════════
        # COMPOUND COMMAND SPLITTING
        # "set alarm for 5 min and remind me to drink water" → 2 commands
        # ═══════════════════════════════════════════════════════════════
        if not fast_response:
            sub_commands = self._split_compound_command(text)

        # ═══════════════════════════════════════════════════════════════
        # CORE: Process through JARVIS brain (or fallback)
        # Error recovery: if handler crashes, reset to idle + notify UI
        # ═══════════════════════════════════════════════════════════════
        try:
            if fast_response:
                response = fast_response
            elif len(sub_commands) > 1:
                # Process each sub-command and combine responses
                responses = []
                for i, sub_cmd in enumerate(sub_commands):
                    _log.info(f"[WebSocket] Processing sub-command {i+1}/{len(sub_commands)}: {sub_cmd}")
                    sub_response = await self._run_turn(sub_cmd.strip(), websocket)
                    if sub_response:
                        responses.append(sub_response)
                response = " Also, ".join(responses) if responses else "Done."
            else:
                response = await self._run_turn(text, websocket)
        except Exception as e:
            if jlog: jlog.error('Command processing failed', e)
            else: _log.warning(f"[WebSocket] CRITICAL: process_command failed: {e}")
            self.state_manager.force_state("idle")
            response = "I encountered an error processing that command. Please try again."
            await self._send_to(websocket, json.dumps({
                'type': 'error',
                'message': str(e)
            }))

        action, confidence, response = self._on_post_process_reply(mood, response, text)

        await self._on_speak_send_result(_live_active, action, confidence, mood, response, websocket)

        # NOTE: Removed duplicate apply_action send - result message above
        # already contains the response. Sending twice caused double messages.

        await self._on_bookkeeping_after_reply(action, response, text, websocket)
        return _NEXT

    def _on_post_process_reply(self, mood, response, text):
        """Step of _on_input(): Post process the reply."""
        # Infer action/intent from response (basic pattern matching)
        action = _infer_action_from_text(text)
        confidence = 0.85 if response and len(response) > 10 else 0.5
        if jlog: jlog.state(action=action, confidence=confidence, mood=mood)

        # Update state with intent
        self.state_manager.update_intent(action, confidence)

        # Adapt response based on mood
        response = _adapt_response_to_mood(
            response, mood,
            title=self.hud_perception.user_title,
            perception=self.perception,
            hud_perception=self.hud_perception,
            jarvis=self.jarvis
        )

        # ━━━ REDUCE "sir" OVERUSE (natural, not robotic) ━━━
        title = getattr(self.hud_perception, 'user_title', 'sir') if self.hud_perception else 'sir'
        response = _reduce_sir_usage(response, title=title)

        # ━━━ STORE RESPONSE FOR ECHO FILTERING ━━━
        # Voice loop compares mic input against these to filter echoes
        if not hasattr(self, '_recent_responses'):
            self._recent_responses = []
        self._recent_responses.append(response or '')
        if len(self._recent_responses) > 3:
            self._recent_responses.pop(0)
        return action, confidence, response


    async def _on_speak_send_result(self, _live_active, action, confidence, mood, response, websocket):
        live, server_spoke, silent = self._on_speak_reply(_live_active, response)

        await self._on_send_result(action, confidence, live, mood, response, server_spoke, silent, websocket)

    def _on_speak_reply(self, _live_active, response):
        """Speak the reply once (the server voice; Gemini in live mode), muting the mic first."""
        # State: speaking
        self.state_manager.force_state("speaking")

        self._on_mute_mic()

        # ━━━ SPEAK THE REPLY EXACTLY ONCE ━━━
        # Live mode: Gemini voices its own replies, so nothing is spoken here.
        # Otherwise the server's voice engine (the natural Edge voice) speaks
        # it; the browser's speechSynthesis is only a fallback when the server
        # has no TTS. Both used to speak, so replies were heard twice in two
        # different voices.
        silent = getattr(self, '_silent_response', False)
        live = _live_active
        server_spoke = False
        if response and not silent and not live:
            server_spoke = self._voice_reply(response)
        return live, server_spoke, silent

    async def _on_send_result(self, action, confidence, live, mood, response, server_spoke, silent, websocket):
        """Step of _on_speak_send_result(): SEND RESULT action response confidence state This is the SINGLE unified response."""
        # ═══════════════════════════════════════════════════════════════
        # SEND RESULT: action + response + confidence + state
        # This is the SINGLE unified response for all input
        # ═══════════════════════════════════════════════════════════════
        result = {
            'type': 'result',
            'action': action,
            # In live mode the text goes to Gemini, which answers itself, so
            # this path only runs for local power commands (never sent to the
            # LLM) or when the live session is down: always show it.
            'response': response,
            'confidence': confidence,
            'mood': mood,
            'silent': silent,
            'speak': bool(response) and not silent and not live and not server_spoke,
            'state': {'current': self.state_manager.state if self.state_manager else 'idle'},
            'channel': 'command'
        }
        # Reset silent flag
        self._silent_response = False
        if jlog: jlog.response(response or '', spoken=True)
        await self._send_to(websocket, json.dumps(result))

        # Record for cross-pipeline dedup
        import time as _rtime
        self._recent_result_text = response or ''
        self._recent_result_time = _rtime.time()

        # ━━━ SCHEDULE MIC UNMUTE after estimated speech duration ━━━
        # ~150 words/min = ~2.5 words/sec. Add 1s buffer for echo fade.
        word_count = len((response or '').split())
        speech_secs = max(2.0, word_count / 2.5 + 1.0)

        async def _unmute_after(delay):
            await asyncio.sleep(delay)
            if self.perception:
                self.perception.is_speaking = False
                self.perception.mic_muted = False
            self.state_manager.force_state("idle")

        asyncio.ensure_future(_unmute_after(speech_secs))



    async def _on_bookkeeping_after_reply(self, action, response, text, websocket):
        """Step of _on_input(): Bookkeeping after a reply."""
        self._on_save_chat_history(response, text)

        self._on_record_action(action, text)

        # Return to idle after speaking
        len(response.split()) if response else 1
        await asyncio.sleep(0.3)  # Brief pause before idle
        self.state_manager.force_state("idle")

        # Final state broadcast
        await self._send_to(websocket, json.dumps({
            'type': 'state',
            'state': self.state_manager.get_full_state()
        }))


    def _on_duplicate_speech(self, msg_type, text):
        """Step of _on_input(): duplicate speech."""
        # Deduplication: only for speech, where the mic can deliver the same
        # sentence twice. A typed or clicked command is always deliberate;
        # dropping it silently ("what time is it" asked twice in 2 s) left
        # the HUD waiting for an answer that never came.
        if msg_type == 'voice_input' and self.state_manager.is_duplicate_command(text):
            if jlog: jlog.warn(f'Skipping duplicate: "{text}"')
            return
        return _NEXT

    def _on_mute_mic(self):
        """Step of _on_input(): mute mic."""
        # ━━━ MUTE MIC BEFORE SPEAKING (prevents TTS echo) ━━━
        if self.perception:
            self.perception.mic_muted = True
            self.perception.is_speaking = True

    def _on_record_action(self, action, text):
        """Step of _on_input(): record action."""
        # Record action for proactive pattern learning
        if self.proactive_assistant:
            try:
                self.proactive_assistant.record_action(action, {'command': text})
            except Exception as _err:
                recovered("WebSocket", _err)


    def _on_feature_switches(self, is_local_power, text):
        """Step of _on_input(): feature switches."""
        if text.strip():
            cmd_check = normalize_command(text)
            is_local_power = (
                # Feature switches (gestures, face, emotion) are local
                # settings; in live mode the HUD's gesture button was sent
                # to Gemini, which can't flip them.
                bool(FEATURE_TOGGLE_RE.match(cmd_check))
                or is_jarvis_exit_command(cmd_check)
                or detect_pc_power_action(cmd_check) is not None
                or (self._get_pending_power_action() is not None
                    and bool(CONFIRM_RE.match(cmd_check) or CANCEL_RE.match(cmd_check)))
                or self._answers_whatsapp_draft(cmd_check)
            )
        return is_local_power


    def _on_voice_input(self, _live_active, msg_type, text):
        """Step of _on_input(): Voice_input."""
        if msg_type == 'voice_input' and _live_active:
            if jlog:
                jlog.warn(f'voice_input suppressed (Gemini Live active): "{text[:60]}"')
            else:
                _log.info(f"[WebSocket] voice_input suppressed (Gemini Live owns mic): {text[:60]}")
            return
        return _NEXT

    def _on_input_chat(self, _live_active, is_local_power, msg_type, text):
        """Step of _on_input(): Text_input command chat."""
        if _live_active and msg_type in ('text_input', 'command', 'chat') and text.strip() and not is_local_power:
            try:
                # Push user text into the Gemini Live session as a text turn
                self._push_live_text(text)
            except Exception as _live_err:
                _log.warning(f"[WebSocket] Live text injection failed, falling through: {_live_err}")
                # Fall through to legacy pipeline as safety net
            else:
                # Gemini owns this turn now. Never fall through after a
                # successful push (a logging error here used to run every
                # typed command twice: once by Gemini, once by the fast path).
                try:
                    if jlog:
                        jlog.info(f'Routed to Gemini Live: "{text[:60]}"')
                    else:
                        _log.info(f"[WebSocket] Routed text to Gemini Live: {text[:60]}")
                except Exception as _err:
                    recovered("WebSocket", _err)
                return
        return _NEXT

    def _on_save_chat_history(self, response, text):
        """Step of _on_input(): save chat history."""
        # Save to chat history for memory
        if self.chat_history:
            try:
                self.chat_history.add_message('user', text)
                self.chat_history.add_message('assistant', response)
            except Exception as e:
                if jlog: jlog.error('Chat history save failed', e)
                else: _log.warning(f"[WebSocket] Chat history error: {e}")


    async def _on_switch_voice(self, data, websocket):
        """Step of process_message(): Switch_voice."""
        voice = data.get('voice', 'jarvis')
        with command_turn() as said:
            if voice.lower() == 'friday':
                self.hud_perception.switch_to_friday()
            else:
                self.hud_perception.switch_to_jarvis()

        await self._send_to(websocket, json.dumps({
            'type': 'assistant_info',
            'name': self.hud_perception.assistant_name,
            'is_friday': self.hud_perception.is_friday
        }))

        # The greeting in the new voice, spoken once (server voice, or the
        # browser only if the server can't speak)
        greeting = " ".join(said)
        if greeting:
            live = self._live_ready()
            server_spoke = (not live) and self._voice_reply(greeting)
            await self._send_to(websocket, json.dumps({
                'type': 'response',
                'text': greeting,
                'speak': not live and not server_spoke
            }))

    async def _on_get_state(self, websocket):
        """Step of process_message(): Get_state."""
        full_state = self.state_manager.get_full_state()
        # Also include system stats for convenience
        full_state['cpu'] = psutil.cpu_percent(interval=0.1)
        full_state['memory'] = psutil.virtual_memory().percent
        full_state['battery'] = getattr(psutil.sensors_battery() or type('', (), {'percent': 100})(), 'percent')
        await self._send_to(websocket, json.dumps({
            'type': 'state',
            'state': full_state
        }))
        _log.info(f"[WebSocket] Sent full state: gesture={full_state.get('gesture_enabled')}, face={full_state.get('face_enabled')}, mood={full_state.get('emotion_enabled')}")

    async def _on_toggle_feature(self, data, websocket):
        """Step of process_message(): Toggle_feature."""
        feature = data.get('feature', '')
        enabled = data.get('enabled', False)

        if feature == 'gesture':
            await self._run_blocking(self.set_gesture_enabled, bool(enabled))
        elif feature == 'face':
            self.face_enabled = enabled
            if enabled and self.face_recognition:
                self.face_recognition.start_monitoring()
            elif self.face_recognition:
                self.face_recognition.stop_monitoring()
        elif feature == 'emotion':
            self.emotion_enabled = enabled

        await self._send_to(websocket, json.dumps(self.get_feature_status()))



    # ── Mood (emotion-aware replies) ─────────────────────────────────────
    def _update_mood(self, text: str) -> str:
        """Track the user's mood and hand it to the AI's personality prompt.

        The mood used to be detected but never reached the AI (nothing set
        perception.current_mood, which the knowledge layer reads), so replies
        never adapted. The Emotion switch off means no mood at all.
        """
        tracker = getattr(self, '_mood_tracker', None)
        if tracker is None:
            tracker = self._mood_tracker = MoodTracker()
        if getattr(self, 'emotion_enabled', True):
            detected = _detect_mood_from_text(text, emotion_enabled=True,
                                              emotion_detector=self.emotion_detector)
            mood = tracker.observe(detected)
        else:
            mood = tracker.observe('neutral', now=float('inf'))
        previous = getattr(self, 'current_emotion', None) or 'neutral'
        self.current_emotion = mood
        if mood != previous:
            _log.info(f"[MOOD] {previous} -> {mood}")
            sm = getattr(self, 'state_manager', None)
            if sm is not None:
                sm.update_mood(mood, 0.7)
        targets = [getattr(self, 'hud_perception', None)]
        try:
            from jarvis.core.services import peek
            from jarvis.core.knowledge import KnowledgeLayer
            kl = peek(KnowledgeLayer)
            targets.append(getattr(kl, 'perception', None) if kl else None)
        except Exception:
            _log.debug("Ignored error", exc_info=True)
        for p in targets:
            if p is not None:
                p.current_mood = None if mood == 'neutral' else mood
        return mood

        # SILENT actions do nothing

    # ── C-05: Hotkey callback handler ──
    def _on_hotkey_action(self, action):
        """Handle hotkey actions from HotkeySystem"""
        if action == "shutdown":
            import signal
            _log.info("[HOTKEY] Shutdown requested via hotkey")
            self.running = False
            os.kill(os.getpid(), signal.SIGTERM)
        elif action == "activate":
            # If Gemini Live is running, inject a greeting
            if getattr(self, 'live_engine', None) and self.live_engine._running:
                try:
                    self._push_live_text("Hey JARVIS, I need you.")
                except Exception as _err:
                    recovered("WebSocket", _err)
            else:
                self.hud_perception.speak("Yes sir, I'm here.")
