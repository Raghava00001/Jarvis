"""
Gesture recognition and handling.

Gestures never ran in the server: it imported a non-existent GestureType, so
GESTURE_AVAILABLE was always False and the gesture thread never started. The
detector itself reversed every swipe (unmirrored camera), reported "zoom" and
"rotate" on almost every frame (so swipes were rarely seen), judged pinch by
absolute distance (a far hand always pinched) and clicked the mouse on pinch.
"""

import json
import math
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from _server_src import server_source  # noqa: E402


# ─── synthetic hands (MediaPipe layout, hand pointing up, y grows down) ────

MCP = {"index": (0.44, 0.62), "middle": (0.50, 0.60), "ring": (0.56, 0.62), "pinky": (0.61, 0.65)}
BASE = {"index": 5, "middle": 9, "ring": 13, "pinky": 17}
THUMB = {
    None: [(0.40, 0.66), (0.45, 0.64)],     # tucked
    "out": [(0.33, 0.66), (0.29, 0.62)],
    "up": [(0.37, 0.58), (0.36, 0.48)],
}


def hand(extended=(), thumb=None, spread=None):
    pts = [None] * 21
    pts[0] = (0.50, 0.80)
    pts[1], pts[2] = (0.43, 0.75), (0.38, 0.70)
    pts[3], pts[4] = THUMB[thumb]
    for f, (x, y) in MCP.items():
        i = BASE[f]
        dx = (spread or {}).get(f, 0.0)
        if f in extended:
            seg = [(x, y), (x + dx * 0.4, y - 0.08), (x + dx * 0.7, y - 0.13), (x + dx, y - 0.18)]
        else:
            seg = [(x, y), (x, y - 0.06), (x, y - 0.02), (x, y + 0.03)]
        pts[i:i + 4] = seg
    return [SimpleNamespace(x=px, y=py) for px, py in pts]


def transform(lm, angle_deg=0.0, scale=1.0, shift=(0.0, 0.0), center=(0.5, 0.7)):
    a = math.radians(angle_deg)
    out = []
    for p in lm:
        x, y = p.x - center[0], p.y - center[1]
        x, y = x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)
        out.append(SimpleNamespace(x=center[0] + x * scale + shift[0], y=center[1] + y * scale + shift[1]))
    return out


POSE_HANDS = {
    "open_palm": lambda: hand(("index", "middle", "ring", "pinky"), thumb="out"),
    "fist": lambda: hand(()),
    "thumbs_up": lambda: hand((), thumb="up"),
    "thumbs_down": lambda: transform(hand((), thumb="up"), angle_deg=180),
    "peace": lambda: hand(("index", "middle"), spread={"index": -0.04, "middle": 0.03}),
    "point": lambda: hand(("index",)),
}


# ─── poses ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("pose", list(POSE_HANDS))
def test_each_pose_is_recognised(pose):
    from jarvis.core.hand_poses import classify_pose
    assert classify_pose(POSE_HANDS[pose]()) == pose


@pytest.mark.parametrize("pose", ["open_palm", "fist", "peace", "point"])
@pytest.mark.parametrize("angle,scale", [(25, 1.0), (-20, 1.0), (0, 0.45), (15, 1.6)])
def test_poses_work_at_any_angle_and_distance(pose, angle, scale):
    """The old thresholds were absolute: a hand far from the camera always 'pinched'."""
    from jarvis.core.hand_poses import classify_pose
    assert classify_pose(transform(POSE_HANDS[pose](), angle, scale)) == pose


def test_two_fingers_together_is_not_peace():
    from jarvis.core.hand_poses import classify_pose
    assert classify_pose(hand(("index", "middle"))) is None


# ─── tracker: holds, swipes, mirroring ─────────────────────────────────────

def _feed(tracker, frames, t0=0.0, dt=0.1):
    events = []
    for i, lm in enumerate(frames):
        ev = tracker.update(lm, t0 + i * dt)
        if ev:
            events.append(ev.name)
    return events


def test_pose_needs_a_short_still_hold_and_fires_once():
    from jarvis.core.hand_poses import GestureTracker
    tr = GestureTracker()
    up = POSE_HANDS["thumbs_up"]()
    assert _feed(tr, [up] * 2) == []            # 0.1 s: too short
    tr = GestureTracker()
    assert _feed(tr, [up] * 15) == ["thumbs_up"]  # held 1.4 s: fires once, not 10 times


def test_moving_hand_is_not_a_pose():
    from jarvis.core.hand_poses import GestureTracker
    tr = GestureTracker()
    frames = [transform(POSE_HANDS["fist"](), shift=(0.0, -0.05 * i)) for i in range(8)]
    assert "fist" not in _feed(tr, frames)


def _swipe(dx_total, steps=4, base=None, dy_total=0.0):
    base = base or POSE_HANDS["open_palm"]()
    return [transform(base, shift=(dx_total * i / steps, dy_total * i / steps)) for i in range(steps + 1)]


def test_swipe_direction_is_mirrored_like_a_selfie():
    """Moving your hand to your right moves it LEFT in the raw camera image.
    The old detector reported that as swipe_left: every swipe was reversed."""
    from jarvis.core.hand_poses import GestureTracker
    assert _feed(GestureTracker(), _swipe(-0.3)) == ["swipe_right"]
    assert _feed(GestureTracker(), _swipe(+0.3)) == ["swipe_left"]
    assert _feed(GestureTracker(), _swipe(0.0, dy_total=-0.3)) == ["swipe_up"]


def test_return_stroke_does_not_fire_the_opposite_swipe():
    from jarvis.core.hand_poses import GestureTracker
    tr = GestureTracker()
    out = _feed(tr, _swipe(-0.3))
    back = _swipe(+0.3, base=_swipe(-0.3)[-1])
    out += _feed(tr, back, t0=0.8)
    assert out == ["swipe_right"]


def test_slow_drift_is_not_a_swipe():
    from jarvis.core.hand_poses import GestureTracker
    frames = [transform(POSE_HANDS["point"](), shift=(-0.01 * i, 0)) for i in range(20)]
    assert not [e for e in _feed(GestureTracker(), frames) if e.startswith("swipe")]


# ─── actions ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("title,app", [
    ("Lo-fi beats - YouTube - Google Chrome", "youtube"),
    ("Spotify Premium", "music"),
    ("report.pdf - Adobe Acrobat Reader", "pdf"),
    ("Deck.pptx - PowerPoint", "slides"),
    ("Inbox - Gmail - Microsoft Edge", "browser"),
    ("main.py - Visual Studio Code", "default"),
])
def test_app_context_from_window_title(title, app):
    from jarvis.core.gesture_controller import app_context
    assert app_context(title) == app


def test_no_gesture_clicks_the_mouse():
    """Pinch used to click wherever the cursor was, and fired by accident."""
    from jarvis.core.gesture_controller import GESTURE_ACTIONS
    actions = {a for app in GESTURE_ACTIONS.values() for a in app.values()}
    assert not actions & {"click", "select", "select_text", "select_location"}
    assert all("pinch" not in app for app in GESTURE_ACTIONS.values())


def test_media_actions_use_media_keys_and_tabs_get_focus_first():
    import pyautogui
    from jarvis.core import gesture_controller as gc
    calls = []
    with patch.object(pyautogui, "press", side_effect=lambda *a, **k: calls.append(("press", a))), \
         patch.object(pyautogui, "hotkey", side_effect=lambda *a: calls.append(("hotkey", a))), \
         patch("jarvis.core.screen_control.focus_away_from_jarvis",
               side_effect=lambda: calls.append(("focus",))) as focus:
        assert gc.execute_gesture_action("next_track")
        assert gc.execute_gesture_action("next_tab")
    assert calls == [("press", ("nexttrack",)), ("focus",), ("hotkey", ("ctrl", "tab"))]
    assert focus.call_count == 1   # media keys don't need focus


# ─── server: communication gestures, on/off, camera ────────────────────────

def _server(tmp_path=None):
    import jarvis.gui.websocket_server as ws
    srv = object.__new__(ws.JARVISWebSocketServer)
    srv.hud_perception = SimpleNamespace(user_title="sir")
    srv.perception = None
    srv.live_engine = None
    srv.quiet_mode = True
    srv._pending_power_action = None
    srv._pending_clarify = None
    srv._gesture_feedback = MagicMock()
    srv._stop_speaking = MagicMock()
    srv._run_on_loop = MagicMock(side_effect=lambda coro: coro.close())
    srv._gesture_command = MagicMock(side_effect=lambda text: _Coro(text))
    if tmp_path is not None:
        srv.GESTURE_PREFS = tmp_path / "feature_prefs.json"
    return srv


class _Coro:
    def __init__(self, text):
        self.text = text

    def close(self):
        pass


def test_thumbs_up_answers_a_pending_question():
    srv = _server()
    srv._pending_power_action = ("shutdown", time.time() + 30)
    srv._on_gesture("thumbs_up")
    srv._gesture_command.assert_called_once_with("yes")
    srv._on_gesture("thumbs_down")
    srv._gesture_command.assert_called_with("cancel")


def test_thumbs_up_with_nothing_pending_does_nothing():
    srv = _server()
    srv._on_gesture("thumbs_up")
    srv._gesture_command.assert_not_called()


def test_open_palm_stops_speech_only_while_talking():
    srv = _server()
    srv._is_jarvis_talking = lambda: False
    srv._on_gesture("open_palm")
    srv._stop_speaking.assert_not_called()
    srv._is_jarvis_talking = lambda: True
    srv._on_gesture("open_palm")
    srv._stop_speaking.assert_called_once()


def test_peace_wakes_jarvis():
    srv = _server()
    srv.live_engine = MagicMock()
    srv._on_gesture("peace")
    srv.live_engine.wake.assert_called_once()
    assert srv.quiet_mode is False


def test_gesture_switch_is_remembered(tmp_path):
    srv = _server(tmp_path)
    type(srv).gesture_controller = property(lambda self: SimpleNamespace(active=True))
    try:
        assert "on" in srv.set_gesture_enabled(True)
        assert json.loads(srv.GESTURE_PREFS.read_text())["gestures"] is True
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("JARVIS_GESTURES", None)
            assert srv._load_gesture_pref() is True
        srv.set_gesture_enabled(False)
        assert srv._load_gesture_pref() is False
    finally:
        del type(srv).gesture_controller


def test_gestures_cannot_be_switched_on_without_a_working_model(tmp_path):
    srv = _server(tmp_path)
    type(srv).gesture_controller = property(lambda self: SimpleNamespace(active=False))
    try:
        reply = srv.set_gesture_enabled(True)
        assert srv.gesture_enabled is False and "couldn't" in reply
    finally:
        del type(srv).gesture_controller


def test_gesture_wiring_in_server_source():
    src = server_source()
    assert "import GestureController, GestureType" not in src      # the import that always failed
    assert "No gesture controller - gesture thread disabled" not in src
    assert 'cam.unregister("gesture")' in src                       # camera off while gestures are off
    assert "get_frame_stamped" in src                               # each frame processed once


@pytest.mark.parametrize("text,local", [
    ("enable gestures", True), ("disable gesture control", True), ("turn off face recognition", True),
    ("stop gestures", True), ("what are gestures", False), ("enable dark mode", False),
])
def test_feature_switches_stay_local_in_live_mode(text, local):
    import jarvis.gui.websocket_server as ws
    assert bool(ws.FEATURE_TOGGLE_RE.match(text)) is local
