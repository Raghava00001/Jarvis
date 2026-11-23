"""
Hand poses and swipes from MediaPipe hand landmarks: pure, testable logic.

Landmarks are the 21 MediaPipe hand points with normalised .x/.y (y grows
downward): 0 wrist; thumb 1-4; index 5-8; middle 9-12; ring 13-16; pinky 17-20
(each finger: MCP, PIP, DIP, TIP).

Design (why the old detector misfired):
  * Fingers are judged by distances from the wrist, relative to hand size, so
    it works at any distance from the camera and any hand angle. The old pinch
    and zoom thresholds were absolute: a far hand always "pinched".
  * The camera image is mirrored, like a selfie: moving your hand to your right
    is a right swipe. It used to be reported as a left swipe.
  * A pose (thumbs up, fist, ...) must be held still for HOLD_S before it
    counts, and fires once until the hand changes pose.
  * After a swipe, the opposite direction is ignored briefly: bringing the hand
    back used to fire the reverse action.
  * No "zoom"/"rotate" events: they fired on almost every frame and starved the
    swipe detector.
"""

from collections import deque
from dataclasses import dataclass
from math import hypot
from typing import Optional, Sequence

WRIST = 0
THUMB_MCP, THUMB_IP, THUMB_TIP = 2, 3, 4
FINGERS = {  # name: (mcp, pip, tip)
    "index": (5, 6, 8),
    "middle": (9, 10, 12),
    "ring": (13, 14, 16),
    "pinky": (17, 18, 20),
}

POSES = ("open_palm", "fist", "thumbs_up", "thumbs_down", "peace", "point")


def _d(a, b) -> float:
    return hypot(a.x - b.x, a.y - b.y)


def hand_size(lm: Sequence) -> float:
    """Wrist to middle-finger knuckle: the scale every other distance is divided by."""
    return max(_d(lm[WRIST], lm[9]), 1e-6)


def finger_state(lm: Sequence, finger: str) -> str:
    """'extended', 'curled' or 'between' for index/middle/ring/pinky."""
    _, pip, tip = FINGERS[finger]
    ratio = _d(lm[WRIST], lm[tip]) / max(_d(lm[WRIST], lm[pip]), 1e-6)
    if ratio > 1.15:
        return "extended"
    if ratio < 1.0:
        return "curled"
    return "between"


def thumb_direction(lm: Sequence) -> Optional[str]:
    """'up', 'down' or 'out' if the thumb is extended, else None (tucked)."""
    hs = hand_size(lm)
    tip, mcp, ip = lm[THUMB_TIP], lm[THUMB_MCP], lm[THUMB_IP]
    if _d(tip, lm[5]) / hs < 0.55 or _d(lm[WRIST], tip) < _d(lm[WRIST], ip):
        return None
    rise = (mcp.y - tip.y) / hs  # image y grows downward
    if rise > 0.45:
        return "up"
    if rise < -0.45:
        return "down"
    return "out"


def classify_pose(lm: Sequence) -> Optional[str]:
    """The static pose of one hand, or None if it isn't a clear one."""
    s = {f: finger_state(lm, f) for f in FINGERS}
    extended = [f for f, v in s.items() if v == "extended"]
    curled = [f for f, v in s.items() if v == "curled"]
    thumb = thumb_direction(lm)

    if len(extended) == 4:
        return "open_palm"
    if len(curled) == 4:
        tip_y = lm[THUMB_TIP].y
        finger_tips = [lm[FINGERS[f][2]].y for f in FINGERS]
        if thumb == "up" and tip_y < min(finger_tips):
            return "thumbs_up"
        if thumb == "down" and tip_y > max(finger_tips):
            return "thumbs_down"
        if thumb is None:
            return "fist"
        return None
    if set(extended) == {"index", "middle"} and s["ring"] == "curled" and s["pinky"] == "curled":
        # Fingers apart (a "V"), not two fingers held together: in a V the
        # tips are much further apart than the knuckles
        if _d(lm[8], lm[12]) > 1.5 * _d(lm[5], lm[9]):
            return "peace"
        return None
    if extended == ["index"] and len(curled) == 3:
        return "point"
    return None


@dataclass
class GestureEvent:
    name: str          # a pose name, or swipe_left/right/up/down
    kind: str          # "pose" or "swipe"
    confidence: float


class GestureTracker:
    """Turns a stream of hand landmarks into discrete gesture events."""

    HOLD_S = 0.35            # a pose must be held this long, hand still
    STILL = 0.35             # max palm travel during the hold, in hand sizes
    POSE_COOLDOWN_S = 1.5    # same pose again only after this
    SWIPE_WINDOW_S = 0.45    # a swipe must happen within this time
    SWIPE_DIST = 1.1         # palm travel for a swipe, in hand sizes
    SWIPE_COOLDOWN_S = 0.7   # any swipe after a swipe
    RETURN_BLOCK_S = 1.3     # opposite swipe after a swipe (the return stroke)
    LOST_RESET_S = 0.3       # hand gone this long: start fresh

    def __init__(self, mirror: bool = True):
        self.mirror = mirror
        self._track = deque()          # (t, x, y, hand_size)
        self._pose = None              # current candidate pose
        self._pose_since = 0.0
        self._pose_fired = False
        self._last_fire = {}           # event name -> time
        self._last_swipe = None        # (name, time)
        self._last_seen = None

    def reset(self):
        self._track.clear()
        self._pose, self._pose_fired = None, False

    def update(self, lm: Optional[Sequence], t: float) -> Optional[GestureEvent]:
        """Feed one frame (landmarks of one hand, or None); returns an event or None."""
        if lm is None:
            if self._last_seen is not None and t - self._last_seen > self.LOST_RESET_S:
                self.reset()
            return None
        self._last_seen = t
        hs = hand_size(lm)
        x = (lm[WRIST].x + lm[9].x) / 2
        y = (lm[WRIST].y + lm[9].y) / 2
        if self.mirror:
            x = 1.0 - x
        self._track.append((t, x, y, hs))
        while self._track and t - self._track[0][0] > max(self.SWIPE_WINDOW_S, self.HOLD_S) + 0.1:
            self._track.popleft()

        swipe = self._detect_swipe(t)
        if swipe:
            self._pose, self._pose_fired = None, False
            return swipe
        return self._detect_pose(lm, t)

    # ── swipes ──
    def _detect_swipe(self, t: float) -> Optional[GestureEvent]:
        recent = [p for p in self._track if t - p[0] <= self.SWIPE_WINDOW_S]
        if len(recent) < 3:
            return None
        hs = sum(p[3] for p in recent) / len(recent)
        dx = (recent[-1][1] - recent[0][1]) / hs
        dy = (recent[-1][2] - recent[0][2]) / hs
        if abs(dx) >= self.SWIPE_DIST and abs(dx) > 2 * abs(dy):
            name = "swipe_right" if dx > 0 else "swipe_left"
            dist = abs(dx)
        elif abs(dy) >= self.SWIPE_DIST and abs(dy) > 2 * abs(dx):
            name = "swipe_down" if dy > 0 else "swipe_up"
            dist = abs(dy)
        else:
            return None
        if self._last_swipe:
            last_name, last_t = self._last_swipe
            if t - last_t < self.SWIPE_COOLDOWN_S:
                return None
            if t - last_t < self.RETURN_BLOCK_S and _opposite(name) == last_name:
                return None
        self._last_swipe = (name, t)
        self._track.clear()  # the next swipe starts from here
        return GestureEvent(name, "swipe", min(1.0, 0.5 + dist / 4))

    # ── poses ──
    def _detect_pose(self, lm, t: float) -> Optional[GestureEvent]:
        pose = classify_pose(lm)
        if pose != self._pose:
            self._pose, self._pose_since, self._pose_fired = pose, t, False
            return None
        if pose is None or self._pose_fired or t - self._pose_since < self.HOLD_S:
            return None
        held = [p for p in self._track if p[0] >= self._pose_since]
        if len(held) < 3:
            return None
        hs = sum(p[3] for p in held) / len(held)
        travel = hypot(held[-1][1] - held[0][1], held[-1][2] - held[0][2]) / hs
        if travel > self.STILL:
            return None  # moving: probably mid-swipe, not a pose
        if t - self._last_fire.get(pose, -1e9) < self.POSE_COOLDOWN_S:
            return None
        self._pose_fired = True
        self._last_fire[pose] = t
        return GestureEvent(pose, "pose", 0.9)


def _opposite(name: str) -> str:
    return {"swipe_left": "swipe_right", "swipe_right": "swipe_left",
            "swipe_up": "swipe_down", "swipe_down": "swipe_up"}.get(name, "")
