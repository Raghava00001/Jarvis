"""
The server's own microphone loop (used when Gemini Live is off).
"""

import asyncio
import logging
import threading
import time

_log = logging.getLogger(__name__)


class VoiceInputMixin:
    """The server's own microphone loop (used when Gemini Live is off).

    Part of JARVISWebSocketServer (see jarvis/gui/websocket_server.py).
    """

    # ═══════════════════════════════════════════════════════════════
    # VOICE LISTENING THREAD
    # Runs perception.listen() in background, injects into async pipeline
    # ═══════════════════════════════════════════════════════════════

    def _start_voice_thread(self):
        """Start background voice listening thread"""
        # When Gemini Live Engine is active, it owns the microphone exclusively.
        # Do NOT start the old STT pipeline — it would fight for the mic.
        if getattr(self, 'live_engine', None):
            _log.info("[VOICE] Gemini Live Engine active -- old voice listener SKIPPED")
            return

        if not self.perception:
            _log.info("[VOICE] No perception layer - voice input disabled")
            return

        self._voice_thread = threading.Thread(
            target=self._voice_listen_loop,
            daemon=True,
            name="JARVISVoiceThread"
        )
        self._voice_thread.start()
        _log.info("[VOICE] Background voice listening thread started")


    def _voice_listen_loop(self):
        """Background voice listening loop.

        Runs perception.listen() continuously and injects recognized text
        into the async WebSocket pipeline via asyncio.run_coroutine_threadsafe.

        CRITICAL: Two-layer echo prevention:
        1. Flag-based: Skip listening while JARVIS is speaking (mic_muted)
        2. Content-based: Filter out text that matches recent JARVIS responses
        """
        _log.info("[VOICE] Voice listening active - speak into microphone")

        # Store recent JARVIS responses for echo comparison
        if not hasattr(self, '_recent_responses'):
            self._recent_responses = []

        while self.running:
            try:
                # ━━━ LAYER 1: Flag-based echo guard + quiet mode ━━━
                # hud_perception.is_speaking covers the server voice engine,
                # which now speaks every reply
                if (self.perception.is_speaking or self.perception.mic_muted
                        or self.hud_perception.is_speaking):
                    time.sleep(0.3)
                    continue

                # Quiet mode: mic is OFF, only listen for wake word
                if getattr(self, 'quiet_mode', False):
                    # Keep mic muted in perception so normal pipeline stops
                    if self.perception:
                        self.perception.mic_muted = True

                    # Direct silent listen for wake word (bypasses perception noise)
                    import speech_recognition as sr
                    r = sr.Recognizer()
                    try:
                        with sr.Microphone() as source:
                            r.adjust_for_ambient_noise(source, duration=0.2)
                            audio = r.listen(source, timeout=1, phrase_time_limit=3)
                        text = r.recognize_google(audio).lower()
                        if any(w in text for w in ['jarvis', 'friday', 'hey jarvis', 'wake up']):
                            self.quiet_mode = False
                            if self.perception:
                                self.perception.mic_muted = False
                                self.perception.is_speaking = False
                            _log.info("[VOICE] Quiet mode OFF - wake word detected")
                            # Process the command after the wake word
                            if self._voice_loop and self.clients:
                                asyncio.run_coroutine_threadsafe(
                                    self._handle_voice_input(text),
                                    self._voice_loop
                                )
                    except Exception:
                        _log.debug("Ignored error", exc_info=True) # Silently drop everything else in quiet mode

                    time.sleep(0.5)
                    continue

                # Listen for speech (blocks until speech detected or timeout)
                text = self.perception.listen(timeout=10)

                if text and text.strip() and len(text.strip()) > 2:
                    text = text.strip()

                    # ━━━ LAYER 2: Content-based echo filter ━━━
                    # If voice input matches a recent JARVIS response, it's echo
                    text_words = set(text.lower().split())
                    is_echo = False
                    for recent_resp in self._recent_responses:
                        resp_words = set(recent_resp.lower().split())
                        if not text_words or not resp_words:
                            continue
                        # Check word overlap — if >50% of input words appear in response
                        overlap = len(text_words & resp_words)
                        if len(text_words) > 0 and overlap / len(text_words) > 0.5:
                            _log.info(f"[VOICE] Echo filtered: \"{text[:50]}...\" (matched recent response)")
                            is_echo = True
                            break

                    if is_echo:
                        continue

                    _log.info(f"[VOICE] Recognized: \"{text}\"")

                    # ━━━ INTERRUPT: Stop JARVIS if speaking when user talks ━━━
                    if self.perception.is_speaking:
                        _log.info("[VOICE] User spoke while JARVIS speaking - interrupting")
                        self._stop_speaking()
                        time.sleep(0.3)

                    # Inject into async event loop
                    if self._voice_loop and self.clients:
                        asyncio.run_coroutine_threadsafe(
                            self._handle_voice_input(text),
                            self._voice_loop
                        )
                    elif not self.clients:
                        _log.info("[VOICE] No clients connected, skipping")

            except Exception as e:
                err_str = str(e)
                # Don't spam on timeouts
                if 'listening timed out' not in err_str.lower() and 'WaitTimeoutError' not in err_str:
                    _log.warning(f"[VOICE] Listen error: {e}")
                time.sleep(0.5)


    async def _handle_voice_input(self, text: str):
        """Process voice input text through the command pipeline (called from voice thread)"""
        # Process through unified pipeline via first client only
        # NOTE: We do NOT send a separate 'voice_recognized' message.
        # The 'result' from process_message already contains the response.
        for ws in list(self.clients):
            try:
                data = {'type': 'voice_input', 'text': text}
                await self.process_message(ws, data)
                break  # Only process once via first client
            except Exception as e:
                _log.warning(f"[VOICE] Pipeline error: {e}")
