import collections
import enum
import math
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple
from src.config import AppConfig
from src.tracker import HandLandmarksData


class GestureType(str, enum.Enum):
    IDLE = "IDLE"
    MOVE = "MOVE"
    INDEX_DIAL_READY = "INDEX_DIAL_READY"        # Index pointing dial ready
    ROTATING_ZOOM_IN = "ROTATING_ZOOM_IN"        # Clockwise Dial Rotation -> Zoom In
    ROTATING_ZOOM_OUT = "ROTATING_ZOOM_OUT"      # Anticlockwise Dial Rotation -> Zoom Out
    CLICKING_LOCK = "CLICKING"
    LEFT_CLICK = "LEFT_CLICK"
    LEFT_DRAG = "LEFT_DRAG"
    RIGHT_CLICK = "RIGHT_CLICK"
    DOUBLE_CLICK = "DOUBLE_CLICK"                # Pinky + Thumb Pinch
    MEDIT_PAN_DRAG = "MEDIT_PAN_DRAG"            # Medit / Dental CAD Right-Click Drag


@dataclass
class GestureEvent:
    gesture: GestureType
    cursor_point_norm: Optional[Tuple[float, float]] = None  # Normalized (x, y) 0.0-1.0
    
    # Left click & drag
    is_left_click_trigger: bool = False
    is_left_down: bool = False
    is_left_up: bool = False
    
    # Right click & Medit Right-Drag
    is_right_click_trigger: bool = False
    is_right_down: bool = False
    is_right_up: bool = False
    
    # Middle click & Middle-Drag
    is_middle_down: bool = False
    is_middle_up: bool = False
    
    # Double Click (Pinky)
    is_double_click_trigger: bool = False
    
    # Rotational Dial Zoom Scroll Delta
    scroll_delta: float = 0.0
    
    # Fist toggle notification & visual progress (0.0 to 1.0)
    is_fist_toggle: bool = False
    fist_progress: float = 0.0
    
    sensitivity_multiplier: float = 1.0
    allow_cursor_move: bool = True
    
    raw_index_pinch: float = 1.0
    raw_middle_pinch: float = 1.0
    raw_ring_pinch: float = 1.0
    raw_pinky_pinch: float = 1.0
    
    trajectory_points: Optional[List[Tuple[float, float]]] = None


class GestureEngine:
    def __init__(self, config: AppConfig):
        self.config = config
        
        # Fist Pause / Resume toggle state
        self.fist_start_time: float = 0.0
        self.fist_toggle_fired: bool = False
        
        # Zoom state lock machine (Hysteresis)
        self.is_zoom_locked: bool = False
        self.zoom_enter_count: int = 0
        self.zoom_exit_count: int = 0

        # Dynamic Circular Trajectory Buffer (Sliding Window Circle Center)
        self.index_trail = collections.deque(maxlen=10)
        self.prev_center_angle: Optional[float] = None
        self.smoothed_zoom_rate: float = 0.0
        
        # Pinch states with hysteresis
        self.is_left_pinched: bool = False
        self.is_middle_pinched: bool = False
        self.is_pinky_pinched: bool = False
        
        # Timing
        self.left_pinch_start_time: float = 0.0
        self.middle_pinch_start_time: float = 0.0
        self.pinky_pinch_start_time: float = 0.0
        
        self.last_left_click_time: float = 0.0
        self.last_right_click_time: float = 0.0
        self.last_double_click_time: float = 0.0
        self.last_freeze_time: float = 0.0
        
        # Active hold/drag modes
        self.is_left_dragging: bool = False
        self.is_middle_dragging: bool = False

    def update(self, hand_data: Optional[HandLandmarksData]) -> GestureEvent:
        """
        Classifies hand state into precision mouse, 3D CAD navigation,
        Sliding-Center Circular Dial Zoom (Clockwise=In, Anticlockwise=Out),
        Pinky Double Click, and Fist Pause/Resume toggling.
        """
        now = time.time()
        event = GestureEvent(gesture=GestureType.IDLE, allow_cursor_move=False)

        if hand_data is None:
            if self.is_left_dragging:
                self.is_left_dragging = False
                event.is_left_up = True
            if self.is_middle_dragging:
                self.is_middle_dragging = False
                if self.config.cad_drag_button == "right":
                    event.is_right_up = True
                else:
                    event.is_middle_up = True
            self.is_left_pinched = False
            self.is_middle_pinched = False
            self.is_pinky_pinched = False
            self.fist_start_time = 0.0
            self.fist_toggle_fired = False
            self.is_zoom_locked = False
            self.zoom_enter_count = 0
            self.zoom_exit_count = 0
            self.index_trail.clear()
            self.prev_center_angle = None
            self.smoothed_zoom_rate = 0.0
            return event

        cursor_norm = hand_data.index_mcp_norm
        event.cursor_point_norm = cursor_norm

        dist_idx_thumb = hand_data.pinch_index_thumb
        dist_mid_thumb = hand_data.pinch_middle_thumb
        dist_ring_thumb = hand_data.pinch_ring_thumb
        dist_pinky_thumb = hand_data.pinch_pinky_thumb

        event.raw_index_pinch = dist_idx_thumb
        event.raw_middle_pinch = dist_mid_thumb
        event.raw_ring_pinch = dist_ring_thumb
        event.raw_pinky_pinch = dist_pinky_thumb

        # ----------------- 0. ZOOM STATE MACHINE (HYSTERESIS LOCK) -----------------
        is_normal_open_palm = (
            hand_data.middle_extended
            and hand_data.ring_extended
            and hand_data.pinky_extended
        )

        if hand_data.is_index_pointing and not hand_data.is_fist:
            self.zoom_enter_count += 1
            if self.zoom_enter_count >= 2:
                self.is_zoom_locked = True
        else:
            self.zoom_enter_count = 0

        if is_normal_open_palm and not hand_data.is_index_pointing:
            self.zoom_exit_count += 1
            if self.zoom_exit_count >= 2:
                self.is_zoom_locked = False
                self.index_trail.clear()
                self.prev_center_angle = None
                self.smoothed_zoom_rate = 0.0
        else:
            self.zoom_exit_count = 0

        # If LOCKED in Zoom Mode: 100% LOCKOUT of all other gestures & pinches!
        if self.is_zoom_locked:
            if self.is_left_dragging:
                self.is_left_dragging = False
                event.is_left_up = True
            if self.is_middle_dragging:
                self.is_middle_dragging = False
                if self.config.cad_drag_button == "right":
                    event.is_right_up = True
                else:
                    event.is_middle_up = True
            self.is_left_pinched = False
            self.is_middle_pinched = False
            self.is_pinky_pinched = False
            self.fist_start_time = 0.0
            self.fist_toggle_fired = False
            event.fist_progress = 0.0
            event.raw_index_pinch = 1.0
            event.raw_middle_pinch = 1.0
            event.raw_ring_pinch = 1.0
            event.raw_pinky_pinch = 1.0

            # Dynamic Sliding-Center Circular Dial Zoom
            tip_pos = hand_data.index_tip_norm
            self.index_trail.append(tip_pos)
            event.trajectory_points = list(self.index_trail)

            if len(self.index_trail) >= 4:
                cx = sum(p[0] for p in self.index_trail) / len(self.index_trail)
                cy = sum(p[1] for p in self.index_trail) / len(self.index_trail)
                curr_angle = math.atan2(tip_pos[1] - cy, tip_pos[0] - cx)

                if self.prev_center_angle is not None:
                    d_theta = curr_angle - self.prev_center_angle
                    while d_theta > math.pi:
                        d_theta -= 2.0 * math.pi
                    while d_theta < -math.pi:
                        d_theta += 2.0 * math.pi

                    p_last = self.index_trail[-2]
                    step_speed = math.hypot(tip_pos[0] - p_last[0], tip_pos[1] - p_last[1])
                    if step_speed > 0.0025:
                        instant_rate = d_theta * 18.0
                        self.smoothed_zoom_rate = 0.55 * self.smoothed_zoom_rate + 0.45 * instant_rate
                    else:
                        self.smoothed_zoom_rate *= 0.60

                    if abs(self.smoothed_zoom_rate) > 0.06:
                        scroll_amount = self.smoothed_zoom_rate * self.config.scroll_speed
                        event.scroll_delta = scroll_amount
                        if scroll_amount > 0:
                            event.gesture = GestureType.ROTATING_ZOOM_IN
                        else:
                            event.gesture = GestureType.ROTATING_ZOOM_OUT
                    else:
                        event.gesture = GestureType.INDEX_DIAL_READY

                self.prev_center_angle = curr_angle
            else:
                event.gesture = GestureType.INDEX_DIAL_READY

            event.allow_cursor_move = False
            return event

        # ----------------- 1. Closed Fist Pause / Resume Toggle -----------------
        if hand_data.is_fist:
            self.index_trail.clear()
            self.prev_center_angle = None
            self.smoothed_zoom_rate = 0.0
            event.scroll_delta = 0.0
            if self.fist_start_time == 0.0:
                self.fist_start_time = now

            hold_time = now - self.fist_start_time
            event.fist_progress = min(1.0, hold_time / max(0.1, self.config.fist_toggle_hold_sec))

            if hold_time >= self.config.fist_toggle_hold_sec:
                if not self.fist_toggle_fired:
                    self.fist_toggle_fired = True
                    self.config.is_tracking_enabled = not self.config.is_tracking_enabled
                    event.is_fist_toggle = True
        else:
            self.fist_start_time = 0.0
            self.fist_toggle_fired = False
            event.fist_progress = 0.0

        if not self.config.is_tracking_enabled:
            if self.is_left_dragging:
                self.is_left_dragging = False
                event.is_left_up = True
            if self.is_middle_dragging:
                self.is_middle_dragging = False
                if self.config.cad_drag_button == "right":
                    event.is_right_up = True
                else:
                    event.is_middle_up = True
            event.gesture = GestureType.IDLE
            event.allow_cursor_move = False
            self.index_trail.clear()
            self.prev_center_angle = None
            self.smoothed_zoom_rate = 0.0
            event.scroll_delta = 0.0
            return event

        # ----------------- 3. Hysteresis Pinch State Updates (Open Palm Mode) -----------------
        thresh_l = self.config.pinch_threshold_left
        thresh_m = self.config.pinch_threshold_middle
        thresh_p = self.config.pinch_threshold_pinky
        hyst = self.config.pinch_hysteresis

        # 1. Left Pinch (Index + Thumb)
        if not self.is_left_pinched:
            if dist_idx_thumb < thresh_l:
                self.is_left_pinched = True
                self.left_pinch_start_time = now
                self.last_freeze_time = now
        else:
            if dist_idx_thumb > (thresh_l + hyst):
                self.is_left_pinched = False

        # 2. Middle Pinch (Middle + Thumb -> Medit Pan/Rotate Drag)
        if not self.is_middle_pinched:
            if dist_mid_thumb < thresh_m and (hand_data.middle_extended or hand_data.all_fingers_extended or hand_data.four_fingers_extended):
                self.is_middle_pinched = True
                self.middle_pinch_start_time = now
                self.last_freeze_time = now
        else:
            if dist_mid_thumb > (thresh_m + hyst):
                self.is_middle_pinched = False

        # 3. Pinky Pinch (Pinky + Thumb -> Double Click)
        if not self.is_pinky_pinched:
            if dist_pinky_thumb < thresh_p and (hand_data.pinky_extended or hand_data.all_fingers_extended or hand_data.four_fingers_extended):
                self.is_pinky_pinched = True
                self.pinky_pinch_start_time = now
                self.last_freeze_time = now
        else:
            if dist_pinky_thumb > (thresh_p + hyst):
                self.is_pinky_pinched = False

        event.allow_cursor_move = True

        # ----------------- 4. Action Evaluation -----------------

        # A. Pinky Pinch -> Double Click
        if self.is_pinky_pinched:
            event.gesture = GestureType.CLICKING_LOCK
            event.allow_cursor_move = False

        # B. Middle Pinch -> Medit 3D Pan / Rotate Drag (Right-Click Drag)
        elif self.is_middle_pinched:
            if self.is_left_dragging:
                self.is_left_dragging = False
                event.is_left_up = True

            pinch_duration = now - self.middle_pinch_start_time

            if pinch_duration >= self.config.drag_hold_sec:
                if not self.is_middle_dragging:
                    self.is_middle_dragging = True
                    if self.config.cad_drag_button == "right":
                        event.is_right_down = True
                    else:
                        event.is_middle_down = True
                event.gesture = GestureType.MEDIT_PAN_DRAG
                event.allow_cursor_move = True
            else:
                event.gesture = GestureType.CLICKING_LOCK
                event.allow_cursor_move = False

        # C. Index Pinch -> Left Click & Left Drag
        elif self.is_left_pinched:
            if self.is_middle_dragging:
                self.is_middle_dragging = False
                if self.config.cad_drag_button == "right":
                    event.is_right_up = True
                else:
                    event.is_middle_up = True

            pinch_duration = now - self.left_pinch_start_time

            if pinch_duration >= self.config.drag_hold_sec:
                if not self.is_left_dragging:
                    self.is_left_dragging = True
                    event.is_left_down = True
                event.gesture = GestureType.LEFT_DRAG
                event.allow_cursor_move = True
            else:
                event.gesture = GestureType.CLICKING_LOCK
                event.allow_cursor_move = False

        # D. Released / Open Hand
        else:
            # Handle Pinky Double Click release
            if self.pinky_pinch_start_time > 0.0:
                tap_time = now - self.pinky_pinch_start_time
                if tap_time < self.config.drag_hold_sec:
                    if (now - self.last_double_click_time) > self.config.click_debounce_sec:
                        self.last_double_click_time = now
                        event.is_double_click_trigger = True
                        event.gesture = GestureType.DOUBLE_CLICK

            # Handle Middle Drag release or single Right Click
            if self.is_middle_dragging:
                self.is_middle_dragging = False
                if self.config.cad_drag_button == "right":
                    event.is_right_up = True
                else:
                    event.is_middle_up = True
                event.gesture = GestureType.MOVE
            elif self.middle_pinch_start_time > 0.0:
                tap_time = now - self.middle_pinch_start_time
                if tap_time < self.config.drag_hold_sec:
                    if (now - self.last_right_click_time) > self.config.click_debounce_sec:
                        self.last_right_click_time = now
                        event.is_right_click_trigger = True
                        event.gesture = GestureType.RIGHT_CLICK

            # Handle Left Drag release or single Left Click
            if self.is_left_dragging:
                self.is_left_dragging = False
                event.is_left_up = True
                event.gesture = GestureType.MOVE
            elif self.left_pinch_start_time > 0.0:
                tap_time = now - self.left_pinch_start_time
                if tap_time < self.config.drag_hold_sec:
                    if (now - self.last_left_click_time) > self.config.click_debounce_sec:
                        self.last_left_click_time = now
                        event.is_left_click_trigger = True
                        event.gesture = GestureType.LEFT_CLICK

            self.left_pinch_start_time = 0.0
            self.middle_pinch_start_time = 0.0
            self.pinky_pinch_start_time = 0.0

            if hand_data.all_fingers_extended or hand_data.four_fingers_extended:
                if event.gesture == GestureType.IDLE:
                    event.gesture = GestureType.MOVE
            else:
                event.gesture = GestureType.IDLE
                event.allow_cursor_move = False

        # Click freeze stabilization
        if (now - self.last_freeze_time) < self.config.click_freeze_sec and not (self.is_left_dragging or self.is_middle_dragging):
            event.allow_cursor_move = False

        return event
