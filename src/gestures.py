"""Gesture state machine. Interruptions cancel pending clicks and release held buttons."""

import collections
import enum
import math
import time
from dataclasses import dataclass

from src.config import AppConfig
from src.tracker import HandLandmarksData


class GestureType(str, enum.Enum):
    IDLE = "IDLE"
    MOVE = "MOVE"
    INDEX_DIAL_READY = "INDEX_DIAL_READY"
    ROTATING_ZOOM_IN = "ROTATING_ZOOM_IN"
    ROTATING_ZOOM_OUT = "ROTATING_ZOOM_OUT"
    CLICKING_LOCK = "CLICKING"
    LEFT_CLICK = "LEFT_CLICK"
    LEFT_DRAG = "LEFT_DRAG"
    RIGHT_CLICK = "RIGHT_CLICK"
    DOUBLE_CLICK = "DOUBLE_CLICK"
    MEDIT_PAN_DRAG = "MEDIT_PAN_DRAG"


@dataclass
class GestureEvent:
    gesture: GestureType
    cursor_point_norm: tuple[float, float] | None = None
    is_left_click_trigger: bool = False
    is_left_down: bool = False
    is_left_up: bool = False
    is_right_click_trigger: bool = False
    is_right_down: bool = False
    is_right_up: bool = False
    is_middle_down: bool = False
    is_middle_up: bool = False
    is_double_click_trigger: bool = False
    scroll_delta: float = 0.0
    is_fist_toggle: bool = False
    fist_progress: float = 0.0
    sensitivity_multiplier: float = 1.0
    allow_cursor_move: bool = False
    raw_index_pinch: float = 1.0
    raw_middle_pinch: float = 1.0
    raw_ring_pinch: float = 1.0
    raw_pinky_pinch: float = 1.0
    trajectory_points: list[tuple[float, float]] | None = None


class GestureEngine:
    def __init__(self, config: AppConfig):
        self.config = config
        self.fist_start_time = None
        self.fist_toggle_fired = False
        self.is_zoom_locked = False
        self.zoom_enter_count = 0
        self.zoom_exit_count = 0
        self.index_trail = collections.deque(maxlen=10)
        self.prev_center_angle = None
        self.smoothed_zoom_rate = 0.0
        self.is_left_pinched = False
        self.is_middle_pinched = False
        self.is_pinky_pinched = False
        self.left_pinch_start_time = None
        self.middle_pinch_start_time = None
        self.pinky_pinch_start_time = None
        self.last_left_click_time = -math.inf
        self.last_right_click_time = -math.inf
        self.last_double_click_time = -math.inf
        self.last_freeze_time = -math.inf
        self.is_left_dragging = False
        self.is_middle_dragging = False
        self.drag_button = None
        self._cad_hold_cancelled = False

    def _release_drags(self, event):
        if self.is_left_dragging:
            event.is_left_up = True
            self.is_left_dragging = False
        if self.is_middle_dragging:
            # Release the button actually pressed, even if the preference changed.
            if self.drag_button == "middle":
                event.is_middle_up = True
            else:
                event.is_right_up = True
            self.is_middle_dragging = False
            self.drag_button = None

    def _cancel_pinches(self, event):
        self._release_drags(event)
        self._cad_hold_cancelled = False
        self.is_left_pinched = self.is_middle_pinched = self.is_pinky_pinched = False
        self.left_pinch_start_time = self.middle_pinch_start_time = self.pinky_pinch_start_time = (
            None
        )

    def _reset_zoom(self):
        self.is_zoom_locked = False
        self.zoom_enter_count = self.zoom_exit_count = 0
        self.index_trail.clear()
        self.prev_center_angle = None
        self.smoothed_zoom_rate = 0.0

    def reset(self):
        event = GestureEvent(GestureType.IDLE)
        self._cancel_pinches(event)
        self._reset_zoom()
        self.fist_start_time = None
        self.fist_toggle_fired = False
        return event

    def _dial(self, hand, event):
        event.gesture = GestureType.INDEX_DIAL_READY
        self.index_trail.append(hand.index_tip_norm)
        event.trajectory_points = list(self.index_trail)
        # Tangent direction changes measure curvature without a moving-center artifact.
        # Straight strokes and stationary pointing must not emit wheel events.
        if len(self.index_trail) < 3:
            return
        a, b, c = list(self.index_trail)[-3:]
        u = (b[0] - a[0], b[1] - a[1])
        v = (c[0] - b[0], c[1] - b[1])
        if min(math.hypot(*u), math.hypot(*v)) < 0.0025:
            self.smoothed_zoom_rate = 0.0
            return
        angle = math.atan2(u[0] * v[1] - u[1] * v[0], u[0] * v[0] + u[1] * v[1])
        if abs(angle) > math.pi / 2 or abs(angle) < 0.025:
            self.smoothed_zoom_rate = 0.0
            return
        instant_rate = angle * 18.0
        self.smoothed_zoom_rate = 0.55 * self.smoothed_zoom_rate + 0.45 * instant_rate
        event.scroll_delta = self.smoothed_zoom_rate * self.config.scroll_speed
        event.gesture = (
            GestureType.ROTATING_ZOOM_IN
            if event.scroll_delta > 0
            else GestureType.ROTATING_ZOOM_OUT
        )

    def update(self, hand_data: HandLandmarksData | None) -> GestureEvent:
        now = time.monotonic()
        event = GestureEvent(GestureType.IDLE)
        if hand_data is None:
            return self.reset()
        hand = hand_data
        event.cursor_point_norm = hand.index_mcp_norm
        event.raw_index_pinch = hand.pinch_index_thumb
        event.raw_middle_pinch = hand.pinch_middle_thumb
        event.raw_ring_pinch = hand.pinch_ring_thumb
        event.raw_pinky_pinch = hand.pinch_pinky_thumb

        if hand.is_fist:
            self._cancel_pinches(event)
            self._reset_zoom()
            if self.fist_start_time is None:
                self.fist_start_time = now
            duration = now - self.fist_start_time
            event.fist_progress = min(1.0, duration / self.config.fist_toggle_hold_sec)
            if duration >= self.config.fist_toggle_hold_sec and not self.fist_toggle_fired:
                self.fist_toggle_fired = True
                self.config.is_tracking_enabled = not self.config.is_tracking_enabled
                event.is_fist_toggle = True
            return event
        self.fist_start_time = None
        self.fist_toggle_fired = False
        if not self.config.is_tracking_enabled:
            self._cancel_pinches(event)
            self._reset_zoom()
            return event

        if hand.is_index_pointing:
            self._cancel_pinches(event)
            self.zoom_enter_count += 1
            self.zoom_exit_count = 0
            if self.zoom_enter_count >= 2:
                self.is_zoom_locked = True
                self._dial(hand, event)
            else:
                event.gesture = GestureType.INDEX_DIAL_READY
            return event
        self.zoom_enter_count = 0
        if self.is_zoom_locked:
            self.zoom_exit_count += 1
            # Stop scrolling immediately; two non-pointing frames unlock other gestures.
            self.smoothed_zoom_rate = 0.0
            self.index_trail.clear()
            if self.zoom_exit_count < 2:
                return event
            self._reset_zoom()

        distances = {
            "left": hand.pinch_index_thumb,
            "middle": hand.pinch_middle_thumb,
            "pinky": hand.pinch_pinky_thumb,
        }
        thresholds = {
            "left": self.config.pinch_threshold_left,
            "middle": self.config.pinch_threshold_middle,
            "pinky": self.config.pinch_threshold_pinky,
        }
        active = next((name for name in distances if getattr(self, f"is_{name}_pinched")), None)
        released = None
        if active and distances[active] > thresholds[active] + self.config.pinch_hysteresis:
            released = active
            setattr(self, f"is_{active}_pinched", False)
            active = None

        # Finish the previous gesture before accepting another; never overlap drags/clicks.
        if released:
            started = getattr(self, f"{released}_pinch_start_time")
            was_dragging = self.is_left_dragging or self.is_middle_dragging
            self._release_drags(event)
            if started is not None and not was_dragging and not self._cad_hold_cancelled:
                click_name = {"left": "left", "middle": "right", "pinky": "double"}[released]
                last = getattr(self, f"last_{click_name}_click_time")
                # A pinky release is always a double click; it has no hold action.
                if (
                    released == "pinky" or now - started < self.config.drag_hold_sec
                ) and now - last >= self.config.click_debounce_sec:
                    setattr(event, f"is_{click_name}_click_trigger", True)
                    event.gesture = {
                        "left": GestureType.LEFT_CLICK,
                        "right": GestureType.RIGHT_CLICK,
                        "double": GestureType.DOUBLE_CLICK,
                    }[click_name]
                    setattr(self, f"last_{click_name}_click_time", now)
                    self.last_freeze_time = now
            setattr(self, f"{released}_pinch_start_time", None)
            self._cad_hold_cancelled = False
            if was_dragging:
                event.gesture = GestureType.MOVE
            return event

        if active is None:
            candidates = [name for name in distances if distances[name] < thresholds[name]]
            if candidates:
                active = min(candidates, key=lambda name: distances[name] / thresholds[name])
                setattr(self, f"is_{active}_pinched", True)
                setattr(self, f"{active}_pinch_start_time", now)
                self.last_freeze_time = now

        if active:
            duration = now - getattr(self, f"{active}_pinch_start_time")
            event.gesture = GestureType.CLICKING_LOCK
            if active != "pinky" and duration >= self.config.drag_hold_sec:
                if active == "left":
                    if not self.is_left_dragging:
                        self.is_left_dragging = True
                        event.is_left_down = True
                    event.gesture = GestureType.LEFT_DRAG
                else:
                    if self._cad_hold_cancelled:
                        return event
                    # Changing CAD mode cancels this hold until the fingers separate.
                    if self.is_middle_dragging and self.drag_button != self.config.cad_drag_button:
                        self._release_drags(event)
                        self._cad_hold_cancelled = True
                        return event
                    if not self.is_middle_dragging:
                        self.is_middle_dragging = True
                        self.drag_button = self.config.cad_drag_button
                        if self.drag_button == "right":
                            event.is_right_down = True
                        else:
                            event.is_middle_down = True
                    event.gesture = GestureType.MEDIT_PAN_DRAG
                event.allow_cursor_move = True
        elif hand.all_fingers_extended or hand.four_fingers_extended:
            event.gesture = GestureType.MOVE
            event.allow_cursor_move = now - self.last_freeze_time >= self.config.click_freeze_sec
        return event
