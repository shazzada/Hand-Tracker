import math
import os
import subprocess
import sys
import threading
import time

import pyautogui

from src.config import AppConfig

# Optimize PyAutoGUI for minimum delay
pyautogui.PAUSE = 0.0
pyautogui.FAILSAFE = False

IS_MACOS = sys.platform == "darwin"
IS_WINDOWS = sys.platform.startswith("win")

if IS_MACOS:
    try:
        import Quartz.CoreGraphics as CG

        QUARTZ_AVAILABLE = True
    except ImportError:
        QUARTZ_AVAILABLE = False
else:
    QUARTZ_AVAILABLE = False


class SoundEffects:
    """Non-blocking native acoustic haptic audio player for macOS and Windows."""

    @staticmethod
    def _play_async(sound_type: str):
        def _worker():
            try:
                if IS_MACOS:
                    sound_files = {
                        "click": "/System/Library/Sounds/Tink.aiff",
                        "right_click": "/System/Library/Sounds/Pop.aiff",
                        "double_click": "/System/Library/Sounds/Ping.aiff",
                        "toggle": "/System/Library/Sounds/Morse.aiff",
                    }
                    path = sound_files.get(sound_type, "/System/Library/Sounds/Tink.aiff")
                    if os.path.exists(path):
                        subprocess.run(
                            ["afplay", "-v", "0.4", path],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                elif IS_WINDOWS:
                    import winsound

                    if sound_type in ("click", "right_click"):
                        winsound.MessageBeep(winsound.MB_OK)
                    elif sound_type == "double_click":
                        winsound.MessageBeep(winsound.MB_ICONASTERISK)
                    elif sound_type == "toggle":
                        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()

    @classmethod
    def click(cls):
        cls._play_async("click")

    @classmethod
    def right_click(cls):
        cls._play_async("right_click")

    @classmethod
    def double_click(cls):
        cls._play_async("double_click")

    @classmethod
    def toggle(cls):
        cls._play_async("toggle")


class MouseController:
    def __init__(self, config: AppConfig):
        self.config = config
        self.screen_left = self.screen_top = 0
        self.screen_width, self.screen_height = pyautogui.size()
        self._display_bounds = []
        self._load_displays()
        self.curr_x, self.curr_y = map(float, pyautogui.position())
        self.is_left_down = self.is_right_down = self.is_middle_down = False
        self._scroll_remainder = 0.0

    def _load_displays(self):
        """Use desktop coordinates, including displays left of the primary screen."""
        try:
            if IS_MACOS and QUARTZ_AVAILABLE:
                error, displays, count = CG.CGGetActiveDisplayList(32, None, None)
                if error:
                    return
                rectangles = [CG.CGDisplayBounds(display) for display in displays[:count]]
                bounds = [(r.origin.x, r.origin.y, r.size.width, r.size.height) for r in rectangles]
            else:
                from screeninfo import get_monitors

                bounds = [(m.x, m.y, m.width, m.height) for m in get_monitors()]
            if not bounds:
                return
            self._display_bounds = bounds
            self.screen_left = min(b[0] for b in bounds)
            self.screen_top = min(b[1] for b in bounds)
            self.screen_width = max(b[0] + b[2] for b in bounds) - self.screen_left
            self.screen_height = max(b[1] + b[3] for b in bounds) - self.screen_top
        except Exception:
            # Primary display remains usable if display enumeration is unavailable.
            self._display_bounds = []

    @staticmethod
    def ensure_access():
        if IS_MACOS and QUARTZ_AVAILABLE:
            preflight = getattr(CG, "CGPreflightPostEventAccess", None)
            if preflight is not None and not preflight():
                raise PermissionError(
                    "Enable Accessibility for Terminal or HandTracker in System Settings, then restart"
                )

    def sync_position(self):
        self.curr_x, self.curr_y = map(float, pyautogui.position())
        self._scroll_remainder = 0.0

    def get_effective_margins(self, sensitivity_multiplier: float = 1.0) -> tuple[float, float]:
        sensitivity = max(0.2, min(5.0, self.config.sensitivity * sensitivity_multiplier))
        return tuple(
            max(0.0, 0.5 - max(0.1, (1 - 2 * margin) / sensitivity) / 2)
            for margin in (self.config.active_margin_x, self.config.active_margin_y)
        )

    def map_coordinates(
        self, norm_x: float, norm_y: float, sensitivity_multiplier: float = 1.0
    ) -> tuple[float, float]:
        if not all(math.isfinite(value) for value in (norm_x, norm_y)):
            raise ValueError("Cursor coordinates must be finite")
        mx, my = self.get_effective_margins(sensitivity_multiplier)
        x = max(0.0, min(1.0, (norm_x - mx) / (1 - 2 * mx)))
        y = max(0.0, min(1.0, (norm_y - my) / (1 - 2 * my)))
        return (
            self.screen_left + x * (self.screen_width - 1),
            self.screen_top + y * (self.screen_height - 1),
        )

    def _clamp_position(self, x, y):
        x = max(self.screen_left, min(self.screen_left + self.screen_width - 1, x))
        y = max(self.screen_top, min(self.screen_top + self.screen_height - 1, y))
        if self._display_bounds:
            # A rectangular desktop may contain gaps between differently sized displays.
            candidates = [
                (max(left, min(left + width - 1, x)), max(top, min(top + height - 1, y)))
                for left, top, width, height in self._display_bounds
            ]
            x, y = min(candidates, key=lambda point: math.hypot(point[0] - x, point[1] - y))
        return x, y

    def smooth_coordinates(self, target_x: float, target_y: float) -> tuple[int, int]:
        if not all(math.isfinite(value) for value in (target_x, target_y)):
            raise ValueError("Cursor coordinates must be finite")
        dx, dy = target_x - self.curr_x, target_y - self.curr_y
        distance = math.hypot(dx, dy)
        smoothing = self.config.smoothing_factor
        if distance > 45:
            smoothing = max(0.06, smoothing * 0.2)
        elif distance > 18:
            smoothing = max(0.18, smoothing * 0.5)
        gain = 1.0 - smoothing
        if self.config.adaptive_acceleration_enabled:
            if distance < 6:
                gain *= self.config.precision_dampening_factor
            elif distance > 35:
                maximum = self.config.high_speed_boost_factor
                gain *= min(maximum, 1 + (distance - 35) / 70 * (maximum - 1))
        # Acceleration may converge faster but must never overshoot and oscillate.
        gain = min(1.0, max(0.0, gain)) if distance >= 1.2 else 0.0
        self.curr_x, self.curr_y = self._clamp_position(
            self.curr_x + dx * gain, self.curr_y + dy * gain
        )
        return round(self.curr_x), round(self.curr_y)

    def _post_mouse(self, kind, button, click_count=None):
        if not (IS_MACOS and QUARTZ_AVAILABLE):
            return False
        event_type = {
            ("down", "left"): CG.kCGEventLeftMouseDown,
            ("up", "left"): CG.kCGEventLeftMouseUp,
            ("drag", "left"): CG.kCGEventLeftMouseDragged,
            ("down", "right"): CG.kCGEventRightMouseDown,
            ("up", "right"): CG.kCGEventRightMouseUp,
            ("drag", "right"): CG.kCGEventRightMouseDragged,
            ("down", "middle"): CG.kCGEventOtherMouseDown,
            ("up", "middle"): CG.kCGEventOtherMouseUp,
            ("drag", "middle"): CG.kCGEventOtherMouseDragged,
        }
        buttons = {
            "left": CG.kCGMouseButtonLeft,
            "right": CG.kCGMouseButtonRight,
            "middle": CG.kCGMouseButtonCenter,
        }
        try:
            point = CG.CGPoint(x=self.curr_x, y=self.curr_y)
            event = CG.CGEventCreateMouseEvent(
                None, event_type.get((kind, button), CG.kCGEventMouseMoved), point, buttons[button]
            )
            if event is None:
                return False
            if click_count is not None:
                CG.CGEventSetIntegerValueField(event, CG.kCGMouseEventClickState, click_count)
            CG.CGEventPost(CG.kCGHIDEventTap, event)
            return True
        except Exception:
            return False

    def move_to(self, norm_x: float, norm_y: float, sensitivity_multiplier: float = 1.0):
        x, y = self.smooth_coordinates(
            *self.map_coordinates(norm_x, norm_y, sensitivity_multiplier)
        )
        button = next(
            (b for b in ("left", "right", "middle") if getattr(self, f"is_{b}_down")), "left"
        )
        kind = "drag" if getattr(self, f"is_{button}_down") else "move"
        if not self._post_mouse(kind, button):
            pyautogui.moveTo(x, y)

    def _button_down(self, button):
        if getattr(self, f"is_{button}_down"):
            return
        self.sync_position()
        # Retain ownership even if an OS call fails after posting a partial event.
        setattr(self, f"is_{button}_down", True)
        if not self._post_mouse("down", button):
            pyautogui.mouseDown(button=button)

    def _button_up(self, button):
        if not getattr(self, f"is_{button}_down"):
            return
        if not self._post_mouse("up", button):
            pyautogui.mouseUp(button=button)
        setattr(self, f"is_{button}_down", False)

    def _click(self, button, count=1):
        self.sync_position()
        try:
            for index in range(count):
                setattr(self, f"is_{button}_down", True)
                if not self._post_mouse("down", button, index + 1):
                    pyautogui.mouseDown(button=button)
                time.sleep(0.015)
                if not self._post_mouse("up", button, index + 1):
                    pyautogui.mouseUp(button=button)
                setattr(self, f"is_{button}_down", False)
                if index + 1 < count:
                    time.sleep(0.06)
        finally:
            self._button_up(button)
        if self.config.audio_feedback_enabled:
            if count == 2:
                SoundEffects.double_click()
            elif button == "right":
                SoundEffects.right_click()
            else:
                SoundEffects.click()

    def left_click(self):
        self._click("left")

    def right_click(self):
        self._click("right")

    def double_click(self):
        self._click("left", 2)

    def left_down(self):
        self._button_down("left")

    def left_up(self):
        self._button_up("left")

    def right_down(self):
        self._button_down("right")

    def right_up(self):
        self._button_up("right")

    def middle_down(self):
        self._button_down("middle")

    def middle_up(self):
        self._button_up("middle")

    def release_all(self):
        errors = []
        for button in ("left", "right", "middle"):
            try:
                self._button_up(button)
            except Exception as error:
                errors.append(error)
        self._scroll_remainder = 0.0
        if errors:
            raise RuntimeError(f"Could not release mouse button: {errors[0]}") from errors[0]

    def scroll(self, delta_y: float):
        if not math.isfinite(delta_y):
            raise ValueError("Scroll delta must be finite")
        # Preserve sub-unit motion so slow zoom works on every platform.
        scale = 1.5 if IS_MACOS and QUARTZ_AVAILABLE else 1.0
        self._scroll_remainder += delta_y * scale
        units = math.trunc(self._scroll_remainder)
        if not units:
            return
        if IS_MACOS and QUARTZ_AVAILABLE:
            try:
                event = CG.CGEventCreateScrollWheelEvent(None, CG.kCGScrollEventUnitPixel, 1, units)
                if event is None:
                    raise RuntimeError("Cannot create scroll event")
                CG.CGEventPost(CG.kCGHIDEventTap, event)
                self._scroll_remainder -= units
                return
            except Exception:
                pass
        pyautogui.scroll(units)
        self._scroll_remainder -= units
