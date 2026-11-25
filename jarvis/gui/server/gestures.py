"""
Hand gestures: the camera thread, switching gestures on/off, and what each gesture means.
"""

import json
import logging
import os
import threading
import time
from pathlib import Path

from jarvis.gui.data_providers import maybe_title
from jarvis.gui.server.features import GESTURE_AVAILABLE

_log = logging.getLogger(__name__)


class GestureMixin:
    """Hand gestures: the camera thread, switching gestures on/off, and what each gesture means.

    Part of JARVISWebSocketServer (see jarvis/gui/websocket_server.py).
    """

    # ═══════════════════════════════════════════════════════════════
    # GESTURES
    # Camera -> hand landmarks -> gestures (core/hand_poses.py) -> either a
    # communication gesture handled here (_on_gesture) or a control action in
    # the app the user is in (gesture_controller.execute_gesture_action).
    #
    # The thread used to start only if a GestureController existed at boot,
    # which it never did: the import also asked for a non-existent GestureType,
    # so GESTURE_AVAILABLE was always False and gestures never ran.
    # ═══════════════════════════════════════════════════════════════

    GESTURE_PREFS = Path(__file__).resolve().parents[3] / "jarvis_data" / "feature_prefs.json"


    def _load_gesture_pref(self) -> bool:
        """Gestures on at boot only if the user turned them on (it opens the camera).
        JARVIS_GESTURES=1/0 in .env overrides the saved choice."""
        env = os.getenv("JARVIS_GESTURES")
        if env in ("0", "1"):
            return env == "1"
        try:
            return bool(json.loads(self.GESTURE_PREFS.read_text(encoding="utf-8")).get("gestures", False))
        except Exception:
            return False


    def set_gesture_enabled(self, enabled: bool, title: str = 'sir') -> str:
        """Turn gestures on/off (HUD button, voice, typed). Remembered for next time."""
        reply = self._set_gesture_enabled(enabled, title)
        sm = getattr(self, 'state_manager', None)
        if sm is not None:
            sm.gesture_enabled = self.gesture_enabled   # what the HUD shows
        return reply


    def _set_gesture_enabled(self, enabled: bool, title: str) -> str:
        if enabled and not self.gesture_controller:
            self.gesture_enabled = False
            return f"Gesture control isn't available, {title}: MediaPipe could not be loaded."
        if enabled and not getattr(self.gesture_controller, 'active', False):
            self.gesture_enabled = False
            return f"Gesture control couldn't start, {title}: the hand-tracking model didn't load."
        self.gesture_enabled = bool(enabled)
        try:
            prefs = {}
            if self.GESTURE_PREFS.exists():
                prefs = json.loads(self.GESTURE_PREFS.read_text(encoding="utf-8"))
            prefs["gestures"] = self.gesture_enabled
            self.GESTURE_PREFS.parent.mkdir(parents=True, exist_ok=True)
            self.GESTURE_PREFS.write_text(json.dumps(prefs, indent=2), encoding="utf-8")
        except Exception as e:
            _log.warning(f"[GESTURE] Could not save preference: {e}")
        if self.gesture_enabled:
            return (f"Gesture control on{maybe_title(title)}. Open palm stops me, thumbs up means yes, "
                    f"thumbs down means no, a peace sign wakes me, and swipes control your app.")
        return f"Gesture control off{maybe_title(title)}. Camera released."


    def _start_gesture_thread(self):
        """Start the gesture thread. It idles (camera closed) while gestures are off."""
        if not GESTURE_AVAILABLE:
            _log.warning("[GESTURE] MediaPipe not installed - gestures unavailable")
            return
        self._gesture_thread = threading.Thread(
            target=self._gesture_process_loop, daemon=True, name="JARVISGestureThread")
        self._gesture_thread.start()
        _log.info("[GESTURE] Gesture thread started (camera opens only while gestures are on)")


    def _gesture_process_loop(self):
        from jarvis.core.gesture_controller import (
            app_context, get_gesture_action, execute_gesture_action, COMMUNICATION_GESTURES)
        from jarvis.core.shared_camera import get_shared_camera
        from jarvis.core.screen_control import user_window_title

        cam = get_shared_camera()
        registered = False
        last_frame_t = 0.0
        while self.running:
            try:
                # Camera on only while gestures are on: it used to open at boot
                # and stay on (camera light lit) even with gestures off.
                if not self.gesture_enabled:
                    if registered:
                        cam.unregister("gesture")
                        registered = False
                        if self.gesture_controller:
                            self.gesture_controller.disable_tracking()
                    time.sleep(0.5)
                    continue
                controller = self.gesture_controller
                if controller is None or not controller.active:
                    time.sleep(1.0)
                    continue
                if not registered:
                    cam.register("gesture")
                    registered = True

                frame, frame_t = cam.get_frame_stamped()
                if frame is None or frame_t == last_frame_t:
                    time.sleep(0.02)
                    continue
                last_frame_t = frame_t

                gesture, meta = controller.detect(frame, frame_t)
                if gesture in ('idle', 'tracking', 'disabled', 'error'):
                    continue

                if self.state_manager:
                    self.state_manager.update_gesture(gesture)
                if gesture in COMMUNICATION_GESTURES:
                    self._on_gesture(gesture, meta)
                    continue

                window = user_window_title()
                app = app_context(window)
                action = get_gesture_action(gesture, app)
                done = execute_gesture_action(action) if action else False
                _log.info(f"[GESTURE] {gesture} -> {action or 'nothing'} (app: {app})")
                self._gesture_feedback(gesture, action if done else None, app)
            except Exception as e:
                _log.warning(f"[GESTURE] Processing error: {e}")
                time.sleep(1)
        if registered:
            cam.unregister("gesture")


    def _gesture_feedback(self, gesture: str, action, app: str = 'default', note: str = None):
        """Show a gesture in the HUD (last-gesture panel + a chat line)."""
        from jarvis.core.gesture_controller import GESTURE_EMOJI, ACTION_LABELS
        label = note or (ACTION_LABELS.get(action, action) if action else None)
        self._dispatch_from_thread('sensors', {
            'type': 'gesture_action',
            'gesture': gesture,
            'action': action or '',
            'app': app,
            'label': label or '',
            'emoji': GESTURE_EMOJI.get(gesture, ''),
        })


    def _on_gesture(self, gesture: str, meta=None):
        """Communication gestures: JARVIS understands them like words.

        open_palm    stop speaking (only while talking)
        thumbs_up    "yes" to a pending question
        thumbs_down  "no" to a pending question
        peace        wake: listen without the wake word
        """
        title = getattr(self.hud_perception, 'user_title', 'sir')
        if gesture == 'open_palm':
            if self._is_jarvis_talking():
                self._stop_speaking()
                self._gesture_feedback(gesture, 'stop_speaking', note='Stopped speaking')
            return

        if gesture in ('thumbs_up', 'thumbs_down'):
            draft = self._whatsapp_with_draft()
            if gesture == 'thumbs_up' and draft:
                # A sent message can't be taken back, and a thumbs-up happens by
                # accident (on calls, in videos). Sending needs a spoken "send".
                # (Its "yes" would also reach the draft before any other question.)
                self._gesture_feedback(gesture, None, note="Say 'send' to send the WhatsApp message")
                return
            pending = (self._get_pending_power_action() or getattr(self, '_pending_clarify', None)
                       or draft)   # 👎 clears a typed WhatsApp draft
            if not pending:
                self._gesture_feedback(gesture, None, note='Nothing to answer')
                return
            reply = 'yes' if gesture == 'thumbs_up' else 'cancel'
            self._gesture_feedback(gesture, reply, note=f"Answered '{reply}'")
            self._run_on_loop(self._gesture_command(reply))
            return

        if gesture == 'peace':
            le = getattr(self, 'live_engine', None)
            if le is not None and hasattr(le, 'wake'):
                le.wake("peace gesture")
            self.quiet_mode = False
            if self.perception is not None:
                self.perception.mic_muted = False
            self._gesture_feedback(gesture, 'wake', note=f"Listening{maybe_title(title)}")


    async def _gesture_command(self, text: str):
        """Run a gesture's answer ("yes"/"cancel") through the normal pipeline,
        replying to the first connected HUD."""
        for ws in list(self.clients):
            await self.process_message(ws, {'type': 'command', 'text': text})
            return
