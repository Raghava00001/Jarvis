"""
Voice output: one owner per reply (server voice, or Gemini in live mode), announcements outside a command, and stopping speech.
"""

import logging
import time

_log = logging.getLogger(__name__)


class SpeechMixin:
    """Voice output: one owner per reply (server voice, or Gemini in live mode), announcements outside a command, and stopping speech.

    Part of JARVISWebSocketServer (see jarvis/gui/websocket_server.py).
    """

    def _is_jarvis_talking(self) -> bool:
        """True while any voice output is playing: the server's voice engine,
        the perception layer, or Gemini Live."""
        if self.hud_perception.is_speaking:
            return True
        if self.perception is not None and getattr(self.perception, 'is_speaking', False):
            return True
        le = getattr(self, 'live_engine', None)
        if le is not None:
            q = getattr(le, 'audio_in_queue', None)
            if (q is not None and not q.empty()) or time.time() < getattr(le, '_speaking_until', 0):
                return True
        return False


    def _live_ready(self) -> bool:
        le = getattr(self, 'live_engine', None)
        return bool(le is not None and getattr(le, '_running', False)
                    and getattr(le, 'session', None) is not None)


    def _voice_reply(self, text: str) -> bool:
        """Speak a command reply once, through the server's voice engine.

        Returns False when the server can't speak (no TTS), so the caller lets
        the browser speak it instead. Never called in live mode: Gemini voices
        its own replies there.
        """
        if not text:
            return False
        return self.hud_perception.voice_out(text)


    def _announce(self, text: str) -> None:
        """Speech outside a command (alarm, reminder, hotkey), from any thread.

        Shown in the HUD chat, then voiced by whichever output owns the audio:
        Gemini Live in live mode (these used to be silently dropped there, so an
        alarm could ring without a sound), otherwise the local voice engine.
        """
        self._run_on_loop(self.dispatch('command', {
            'type': 'response', 'text': text, 'speak': False}))
        if self._live_ready():
            try:
                self._push_live_text(
                    "[System notice, not from the user. Tell the user this now, "
                    f"briefly and in your own words: {text}]", wake=False)
                return
            except Exception as e:
                _log.warning(f"[ANNOUNCE] Live announce failed, using local voice: {e}")
        self.hud_perception.voice_out(text)


    def _stop_speaking(self):
        """Stop JARVIS from speaking immediately — both server-side and browser TTS.

        Safe to call from any thread (the gesture thread calls it too).
        """
        # Stop the server's voice engine: the playing line and everything queued.
        # (Only the perception layers were stopped before, so with no
        # PerceptionLayer attached, queued replies kept talking after "stop".)
        self.hud_perception.stop_speaking()

        # Stop Gemini Live's current answer, if it's talking
        le = getattr(self, 'live_engine', None)
        if le is not None and hasattr(le, 'interrupt'):
            try:
                le.interrupt()
            except Exception as e:
                _log.warning(f"[WebSocket] Live interrupt error: {e}")

        if self.perception and hasattr(self.perception, 'stop_speaking'):
            self.perception.stop_speaking()

        # Reset mic mute flags
        if self.perception:
            self.perception.is_speaking = False
            self.perception.mic_muted = False

        # Stop through JARVIS backend perception
        if self.jarvis and hasattr(self.jarvis, 'perception') and hasattr(self.jarvis.perception, 'stop_speaking'):
            self.jarvis.perception.stop_speaking()

        # Stop entertainment/storyteller if running
        if self.entertainment and hasattr(self.entertainment, 'storyteller') and self.entertainment.storyteller:
            if hasattr(self.entertainment.storyteller, 'stop'):
                self.entertainment.storyteller.stop()

        # ━━━ BROADCAST TO ALL HUD CLIENTS: cancel browser speechSynthesis ━━━
        # Through the per-client queues: sending straight to the socket here raced the
        # sender task (two concurrent sends on one socket) and failed outright
        # when called from the gesture thread, which has no event loop.
        if self.clients:
            self._run_on_loop(self.dispatch('command', {'type': 'stop_speaking'}))

        self.state_manager.force_state("idle")
        _log.info("[WebSocket] Speech interrupted (server + browser)")
