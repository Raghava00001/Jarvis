"""
Gesture Controller: hand gestures from the camera, via MediaPipe.

Two kinds of gesture (see hand_poses.py for how they're recognised):

  Communication (handled by the server, see websocket_server._on_gesture):
    open_palm    hold   stop speaking
    thumbs_up    hold   "yes" to a pending question (e.g. "shut down the PC?")
    thumbs_down  hold   "no" / cancel
    peace        hold   wake JARVIS: listen without the wake word

  Control (act on the app you're using, see GESTURE_ACTIONS):
    swipe left/right/up/down, fist (play/pause)

Updated for the MediaPipe Tasks API (0.10.x+).
"""

import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np

from jarvis.core.hand_poses import GestureTracker
from jarvis.core.services import shared

# MediaPipe is loaded on first use, not at import: importing it also loads
# TensorFlow, and this module is imported at server start even when gestures
# are never enabled.
import importlib.util
MP_AVAILABLE = importlib.util.find_spec("mediapipe") is not None
mp = mp_python = mp_vision = MpImage = MpImageFormat = None
HandLandmarker = None
HandLandmarkerOptions = None
_MP_LOADED = False

COMMUNICATION_GESTURES = ("open_palm", "thumbs_up", "thumbs_down", "peace")

GESTURE_EMOJI = {
    "open_palm": "✋", "thumbs_up": "👍", "thumbs_down": "👎", "peace": "✌️", "fist": "✊",
    "point": "☝️", "swipe_left": "👈", "swipe_right": "👉", "swipe_up": "👆", "swipe_down": "👇",
}


def _load_mediapipe() -> bool:
    """Import the MediaPipe Tasks API once; returns whether it is usable."""
    global mp, mp_python, mp_vision, MpImage, MpImageFormat, _MP_LOADED, MP_AVAILABLE
    global HandLandmarker, HandLandmarkerOptions
    if _MP_LOADED:
        return MP_AVAILABLE
    _MP_LOADED = True
    try:
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision as mp_vision
        from mediapipe import Image as MpImage
        from mediapipe import ImageFormat as MpImageFormat

        HandLandmarker = mp_vision.HandLandmarker
        HandLandmarkerOptions = mp_vision.HandLandmarkerOptions
        MP_AVAILABLE = True
        print("[GESTURE] MediaPipe Tasks API available")
    except Exception as e:
        MP_AVAILABLE = False
        print(f"[GESTURE] MediaPipe Tasks not available: {e}")
    return MP_AVAILABLE


class GestureController:
    """Detects gestures in camera frames with MediaPipe's HandLandmarker."""

    MODEL_URL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
    MODEL_NAME = "hand_landmarker.task"

    def __init__(self, perception=None):
        print("[GESTURE] Initializing Gesture Controller...")
        self.perception = perception
        self.landmarker = None
        self.active = False
        self.tracker = GestureTracker(mirror=True)
        self.tracking_mode = False
        if _load_mediapipe():
            self._initialize_landmarker()
        else:
            print("[GESTURE] Gesture Controller Disabled (MediaPipe Tasks not available)")

    def _get_model_path(self) -> Optional[str]:
        """Get or download the hand landmarker model"""
        model_dir = Path(__file__).parent.parent / "data" / "models"
        model_dir.mkdir(parents=True, exist_ok=True)
        model_path = model_dir / self.MODEL_NAME
        if not model_path.exists():
            print("[GESTURE] Downloading hand landmarker model...")
            try:
                import urllib.request
                urllib.request.urlretrieve(self.MODEL_URL, str(model_path))
                print(f"[GESTURE] Model downloaded to {model_path}")
            except Exception as e:
                print(f"[GESTURE] Failed to download model: {e}")
                return None
        return str(model_path)

    def _initialize_landmarker(self):
        model_path = self._get_model_path()
        if not model_path or not os.path.exists(model_path):
            print("[GESTURE] Model not available")
            return
        try:
            options = HandLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=model_path),
                running_mode=mp_vision.RunningMode.IMAGE,
                num_hands=1,
                min_hand_detection_confidence=0.6,
                min_hand_presence_confidence=0.6,
                min_tracking_confidence=0.5,
            )
            self.landmarker = HandLandmarker.create_from_options(options)
            self.active = True
            print("[GESTURE] Gesture Controller Ready (Tasks API)")
        except Exception as e:
            print(f"[GESTURE] Landmarker init error: {e}")
            self.active = False

    # Kept for callers that toggle "tracking"; detection no longer depends on it
    def enable_tracking(self, enabled: bool = True):
        self.tracking_mode = enabled

    def disable_tracking(self):
        self.tracking_mode = False
        self.tracker.reset()

    def landmarks(self, frame: np.ndarray):
        """The 21 landmarks of the most prominent hand in a BGR frame, or None."""
        import cv2
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = self.landmarker.detect(MpImage(image_format=MpImageFormat.SRGB, data=rgb))
        if not result.hand_landmarks:
            return None
        return result.hand_landmarks[0]

    def detect(self, frame: np.ndarray, t: Optional[float] = None) -> Tuple[str, Dict[str, Any]]:
        """Process one camera frame. Returns (gesture, meta):
        'disabled', 'idle' (no hand), 'tracking' (hand, no gesture yet), 'error',
        or a gesture name with meta {'confidence', 'kind'}."""
        if not self.active or self.landmarker is None:
            return "disabled", {}
        try:
            lm = self.landmarks(frame)
            event = self.tracker.update(lm, t if t is not None else time.time())
            if lm is None:
                return "idle", {}
            if event is None:
                return "tracking", {"confidence": 0.0}
            return event.name, {"confidence": event.confidence, "kind": event.kind}
        except Exception as e:
            print(f"[GESTURE] Detection error: {e}")
            return "error", {"error": str(e)}

    def close(self):
        if self.landmarker:
            self.landmarker.close()
            self.landmarker = None
        self.active = False


# ═══════════════════════════════════════════════════════════════
# CONTROL GESTURES: what each one does in the app you're using.
# Media keys and volume work whatever has focus; key presses go to your app
# (focus is taken off the JARVIS HUD first). Pinch no longer clicks the mouse:
# it fired by accident and clicked wherever the cursor happened to be.
# ═══════════════════════════════════════════════════════════════

GESTURE_ACTIONS = {
    "youtube": {"swipe_right": "seek_forward", "swipe_left": "seek_backward",
                "swipe_up": "volume_up", "swipe_down": "volume_down", "fist": "play_pause"},
    "music":   {"swipe_right": "next_track", "swipe_left": "previous_track",
                "swipe_up": "volume_up", "swipe_down": "volume_down", "fist": "play_pause"},
    "browser": {"swipe_right": "next_tab", "swipe_left": "previous_tab",
                "swipe_up": "scroll_up", "swipe_down": "scroll_down", "fist": "play_pause"},
    "pdf":     {"swipe_right": "next_page", "swipe_left": "previous_page",
                "swipe_up": "scroll_up", "swipe_down": "scroll_down"},
    "slides":  {"swipe_right": "next_slide", "swipe_left": "previous_slide"},
    "default": {"swipe_up": "scroll_up", "swipe_down": "scroll_down", "fist": "play_pause"},
}

_APP_PATTERNS = (
    ("youtube", r"youtube"),
    ("music", r"spotify|apple music|groove|media player|vlc|winamp|soundcloud|amazon music|jiosaavn|gaana"),
    ("pdf", r"\.pdf\b|acrobat|pdf reader|sumatra|foxit"),
    ("slides", r"powerpoint|google slides|keynote|impress"),
    ("browser", r"chrome|edge|firefox|brave|opera|vivaldi|safari"),
)


def app_context(window_title: str) -> str:
    """Gesture context for a window title: youtube, music, pdf, slides, browser or default."""
    t = (window_title or "").lower()
    for app, pattern in _APP_PATTERNS:
        if re.search(pattern, t):
            return app
    return "default"


def get_gesture_action(gesture: str, app: str = "default") -> Optional[str]:
    """Map gesture to action based on the app context."""
    return GESTURE_ACTIONS.get(app, GESTURE_ACTIONS["default"]).get(gesture)


ACTION_LABELS = {
    "play_pause": "Play/pause", "next_track": "Next track", "previous_track": "Previous track",
    "seek_forward": "Forward 10 s", "seek_backward": "Back 10 s",
    "volume_up": "Volume up", "volume_down": "Volume down",
    "scroll_up": "Scrolled up", "scroll_down": "Scrolled down",
    "next_tab": "Next tab", "previous_tab": "Previous tab",
    "next_page": "Next page", "previous_page": "Previous page",
    "next_slide": "Next slide", "previous_slide": "Previous slide",
}


def execute_gesture_action(action: str) -> bool:
    """Perform a control action. Returns True if it was executed."""
    if not action:
        return False
    try:
        import pyautogui
    except ImportError:
        print("[GESTURE] pyautogui not available for gesture actions")
        return False

    # (needs your app focused?, what to do)
    actions = {
        "play_pause": (False, lambda: pyautogui.press("playpause")),
        "next_track": (False, lambda: pyautogui.press("nexttrack")),
        "previous_track": (False, lambda: pyautogui.press("prevtrack")),
        "volume_up": (False, lambda: pyautogui.press("volumeup", presses=2)),
        "volume_down": (False, lambda: pyautogui.press("volumedown", presses=2)),
        "scroll_up": (False, lambda: pyautogui.scroll(5)),
        "scroll_down": (False, lambda: pyautogui.scroll(-5)),
        "seek_forward": (True, lambda: pyautogui.press("l")),
        "seek_backward": (True, lambda: pyautogui.press("j")),
        "next_tab": (True, lambda: pyautogui.hotkey("ctrl", "tab")),
        "previous_tab": (True, lambda: pyautogui.hotkey("ctrl", "shift", "tab")),
        "next_page": (True, lambda: pyautogui.press("pagedown")),
        "previous_page": (True, lambda: pyautogui.press("pageup")),
        "next_slide": (True, lambda: pyautogui.press("right")),
        "previous_slide": (True, lambda: pyautogui.press("left")),
    }
    entry = actions.get(action)
    if entry is None:
        print(f"[GESTURE] Unknown action: {action}")
        return False
    needs_focus, run = entry
    try:
        if needs_focus:
            from jarvis.core.screen_control import focus_away_from_jarvis
            focus_away_from_jarvis()
        run()
        print(f"[GESTURE] Executed action: {action}")
        return True
    except Exception as e:
        print(f"[GESTURE] Action execution error: {e}")
        return False


def get_gesture_controller(perception=None) -> GestureController:
    return shared(GestureController, lambda: GestureController(perception))
