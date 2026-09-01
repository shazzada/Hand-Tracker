import math
import os
import subprocess
import sys
import threading
import time
from typing import Optional, Tuple

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
                        subprocess.run(["afplay", "-v", "0.4", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
        
        # Screen dimensions
        try:
            self.screen_width, self.screen_height = pyautogui.size()
        except Exception:
            self.screen_width, self.screen_height = 1920, 1080

        # Current smoothed cursor position
        self.curr_x: float = self.screen_width / 2.0
        self.curr_y: float = self.screen_height / 2.0
        
        # Dragging states
        self.is_left_down: bool = False
        self.is_right_down: bool = False
        self.is_middle_down: bool = False

    def map_coordinates(self, norm_x: float, norm_y: float, sensitivity_multiplier: float = 1.0) -> Tuple[float, float]:
        """
        Maps normalized camera coordinates (0.0-1.0) into full screen pixel coordinates
        using an absolute centered active region scaled by user sensitivity & sniper multiplier.
        """
        margin_x = max(0.02, min(0.35, self.config.active_margin_x))
        margin_y = max(0.02, min(0.35, self.config.active_margin_y))
        sens = max(0.2, min(5.0, self.config.sensitivity * sensitivity_multiplier))

        base_span_x = 1.0 - 2.0 * margin_x
        base_span_y = 1.0 - 2.0 * margin_y

        eff_span_x = max(0.10, base_span_x / sens)
        eff_span_y = max(0.10, base_span_y / sens)

        min_x = max(0.0, 0.5 - eff_span_x / 2.0)
        max_x = min(1.0, 0.5 + eff_span_x / 2.0)
        min_y = max(0.0, 0.5 - eff_span_y / 2.0)
        max_y = min(1.0, 0.5 + eff_span_y / 2.0)

        actual_span_x = max_x - min_x
        actual_span_y = max_y - min_y

        clamped_x = max(min_x, min(max_x, norm_x))
        clamped_y = max(min_y, min(max_y, norm_y))

        scaled_x = (clamped_x - min_x) / actual_span_x
        scaled_y = (clamped_y - min_y) / actual_span_y

        pixel_x = scaled_x * (self.screen_width - 1)
        pixel_y = scaled_y * (self.screen_height - 1)

        return pixel_x, pixel_y

    def smooth_coordinates(self, target_x: float, target_y: float) -> Tuple[int, int]:
        """
        Applies Adaptive Dual-Speed Kinematic Acceleration with Exponential Moving Average (EMA).
        - Micro-movements (< 6px): Dampens motion by precision factor (0.40x) for dental margin line carving.
        - Fast sweeps (> 35px): Accelerates motion dynamically (up to 1.75x) for multi-monitor desktop reach.
        """
        delta_x = target_x - self.curr_x
        delta_y = target_y - self.curr_y
        dist = math.hypot(delta_x, delta_y)

        # Micro-tremor deadzone (< 1.2px) when standing completely still
        if dist < 1.2:
            return int(round(self.curr_x)), int(round(self.curr_y))

        # Adaptive Dual-Speed Acceleration Curve
        if self.config.adaptive_acceleration_enabled:
            if dist < 6.0:
                # Sub-millimeter dental precision dampening
                damp = max(0.20, min(1.0, self.config.precision_dampening_factor))
                target_x = self.curr_x + delta_x * damp
                target_y = self.curr_y + delta_y * damp
            elif dist > 35.0:
                # Multi-monitor fast sweep acceleration
                max_boost = max(1.0, min(3.0, self.config.high_speed_boost_factor))
                boost = min(max_boost, 1.0 + ((dist - 35.0) / 70.0) * (max_boost - 1.0))
                target_x = self.curr_x + delta_x * boost
                target_y = self.curr_y + delta_y * boost

        # Dynamic EMA Smoothing
        base_smoothing = self.config.smoothing_factor
        if dist > 45.0:
            adaptive_smoothing = max(0.06, base_smoothing * 0.20)
        elif dist > 18.0:
            adaptive_smoothing = max(0.18, base_smoothing * 0.50)
        else:
            adaptive_smoothing = base_smoothing

        self.curr_x = self.curr_x * adaptive_smoothing + target_x * (1.0 - adaptive_smoothing)
        self.curr_y = self.curr_y * adaptive_smoothing + target_y * (1.0 - adaptive_smoothing)

        final_x = max(0, min(self.screen_width - 1, int(round(self.curr_x))))
        final_y = max(0, min(self.screen_height - 1, int(round(self.curr_y))))

        return final_x, final_y

    def move_to(self, norm_x: float, norm_y: float, sensitivity_multiplier: float = 1.0):
        """Move mouse cursor smoothly to mapped position with optional sniper sensitivity."""
        target_x, target_y = self.map_coordinates(norm_x, norm_y, sensitivity_multiplier)
        screen_x, screen_y = self.smooth_coordinates(target_x, target_y)

        if IS_MACOS and QUARTZ_AVAILABLE:
            try:
                point = CG.CGPoint(x=screen_x, y=screen_y)
                if self.is_right_down:
                    event = CG.CGEventCreateMouseEvent(None, CG.kCGEventRightMouseDragged, point, CG.kCGMouseButtonRight)
                elif self.is_left_down:
                    event = CG.CGEventCreateMouseEvent(None, CG.kCGEventLeftMouseDragged, point, CG.kCGMouseButtonLeft)
                elif self.is_middle_down:
                    event = CG.CGEventCreateMouseEvent(None, CG.kCGEventOtherMouseDragged, point, CG.kCGMouseButtonCenter)
                else:
                    event = CG.CGEventCreateMouseEvent(None, CG.kCGEventMouseMoved, point, CG.kCGMouseButtonLeft)
                CG.CGEventPost(CG.kCGHIDEventTap, event)
                return
            except Exception:
                pass

        try:
            pyautogui.moveTo(screen_x, screen_y)
        except Exception:
            pass

    def left_click(self):
        """Perform a crisp left click with acoustic feedback."""
        if self.config.audio_feedback_enabled:
            SoundEffects.click()

        if IS_MACOS and QUARTZ_AVAILABLE:
            try:
                point = CG.CGPoint(x=self.curr_x, y=self.curr_y)
                down = CG.CGEventCreateMouseEvent(None, CG.kCGEventLeftMouseDown, point, CG.kCGMouseButtonLeft)
                up = CG.CGEventCreateMouseEvent(None, CG.kCGEventLeftMouseUp, point, CG.kCGMouseButtonLeft)
                CG.CGEventPost(CG.kCGHIDEventTap, down)
                time.sleep(0.015)
                CG.CGEventPost(CG.kCGHIDEventTap, up)
                return
            except Exception:
                pass

        try:
            pyautogui.click(button="left")
        except Exception as e:
            print(f"[Mouse] Left click error: {e}")

    def double_click(self):
        """Perform a crisp double click."""
        if self.config.audio_feedback_enabled:
            SoundEffects.double_click()

        if IS_MACOS and QUARTZ_AVAILABLE:
            try:
                point = CG.CGPoint(x=self.curr_x, y=self.curr_y)
                down = CG.CGEventCreateMouseEvent(None, CG.kCGEventLeftMouseDown, point, CG.kCGMouseButtonLeft)
                up = CG.CGEventCreateMouseEvent(None, CG.kCGEventLeftMouseUp, point, CG.kCGMouseButtonLeft)
                CG.CGEventSetIntegerValueField(down, CG.kCGMouseEventClickState, 1)
                CG.CGEventPost(CG.kCGHIDEventTap, down)
                time.sleep(0.015)
                CG.CGEventPost(CG.kCGHIDEventTap, up)
                time.sleep(0.035)
                CG.CGEventSetIntegerValueField(down, CG.kCGMouseEventClickState, 2)
                CG.CGEventPost(CG.kCGHIDEventTap, down)
                time.sleep(0.015)
                CG.CGEventPost(CG.kCGHIDEventTap, up)
                return
            except Exception:
                pass

        try:
            pyautogui.doubleClick(button="left")
        except Exception as e:
            print(f"[Mouse] Double click error: {e}")

    def right_click(self):
        """Perform a right click."""
        if self.config.audio_feedback_enabled:
            SoundEffects.right_click()

        if IS_MACOS and QUARTZ_AVAILABLE:
            try:
                point = CG.CGPoint(x=self.curr_x, y=self.curr_y)
                down = CG.CGEventCreateMouseEvent(None, CG.kCGEventRightMouseDown, point, CG.kCGMouseButtonRight)
                up = CG.CGEventCreateMouseEvent(None, CG.kCGEventRightMouseUp, point, CG.kCGMouseButtonRight)
                CG.CGEventPost(CG.kCGHIDEventTap, down)
                time.sleep(0.015)
                CG.CGEventPost(CG.kCGHIDEventTap, up)
                return
            except Exception:
                pass

        try:
            pyautogui.click(button="right")
        except Exception as e:
            print(f"[Mouse] Right click error: {e}")

    def left_down(self):
        """Hold down left mouse button."""
        self.is_left_down = True
        if IS_MACOS and QUARTZ_AVAILABLE:
            try:
                point = CG.CGPoint(x=self.curr_x, y=self.curr_y)
                down = CG.CGEventCreateMouseEvent(None, CG.kCGEventLeftMouseDown, point, CG.kCGMouseButtonLeft)
                CG.CGEventPost(CG.kCGHIDEventTap, down)
                return
            except Exception:
                pass
        try:
            pyautogui.mouseDown(button="left")
        except Exception:
            pass

    def left_up(self):
        """Release left mouse button."""
        self.is_left_down = False
        if IS_MACOS and QUARTZ_AVAILABLE:
            try:
                point = CG.CGPoint(x=self.curr_x, y=self.curr_y)
                up = CG.CGEventCreateMouseEvent(None, CG.kCGEventLeftMouseUp, point, CG.kCGMouseButtonLeft)
                CG.CGEventPost(CG.kCGHIDEventTap, up)
                return
            except Exception:
                pass
        try:
            pyautogui.mouseUp(button="left")
        except Exception:
            pass

    def right_down(self):
        """Hold down right mouse button (for Medit 3D Model Rotate/Pan Drag)."""
        self.is_right_down = True
        if IS_MACOS and QUARTZ_AVAILABLE:
            try:
                point = CG.CGPoint(x=self.curr_x, y=self.curr_y)
                down = CG.CGEventCreateMouseEvent(None, CG.kCGEventRightMouseDown, point, CG.kCGMouseButtonRight)
                CG.CGEventPost(CG.kCGHIDEventTap, down)
                return
            except Exception:
                pass
        try:
            pyautogui.mouseDown(button="right")
        except Exception:
            pass

    def right_up(self):
        """Release right mouse button."""
        self.is_right_down = False
        if IS_MACOS and QUARTZ_AVAILABLE:
            try:
                point = CG.CGPoint(x=self.curr_x, y=self.curr_y)
                up = CG.CGEventCreateMouseEvent(None, CG.kCGEventRightMouseUp, point, CG.kCGMouseButtonRight)
                CG.CGEventPost(CG.kCGHIDEventTap, up)
                return
            except Exception:
                pass
        try:
            pyautogui.mouseUp(button="right")
        except Exception:
            pass

    def middle_down(self):
        """Hold down middle mouse button (for CAD 3D Orbit & Pan Drag)."""
        self.is_middle_down = True
        if IS_MACOS and QUARTZ_AVAILABLE:
            try:
                point = CG.CGPoint(x=self.curr_x, y=self.curr_y)
                down = CG.CGEventCreateMouseEvent(None, CG.kCGEventOtherMouseDown, point, CG.kCGMouseButtonCenter)
                CG.CGEventPost(CG.kCGHIDEventTap, down)
                return
            except Exception:
                pass
        try:
            pyautogui.mouseDown(button="middle")
        except Exception:
            pass

    def middle_up(self):
        """Release middle mouse button."""
        self.is_middle_down = False
        if IS_MACOS and QUARTZ_AVAILABLE:
            try:
                point = CG.CGPoint(x=self.curr_x, y=self.curr_y)
                up = CG.CGEventCreateMouseEvent(None, CG.kCGEventOtherMouseUp, point, CG.kCGMouseButtonCenter)
                CG.CGEventPost(CG.kCGHIDEventTap, up)
                return
            except Exception:
                pass
        try:
            pyautogui.mouseUp(button="middle")
        except Exception:
            pass

    def scroll(self, delta_y: float):
        """Perform continuous scroll wheel zoom / page scroll."""
        if abs(delta_y) < 0.1:
            return

        if IS_MACOS and QUARTZ_AVAILABLE:
            try:
                pixels = int(round(delta_y * 1.5))
                event = CG.CGEventCreateScrollWheelEvent2(None, CG.kCGScrollEventUnitPixel, 1, pixels)
                CG.CGEventPost(CG.kCGHIDEventTap, event)
                return
            except Exception:
                pass

        try:
            clicks = int(round(delta_y))
            pyautogui.scroll(clicks)
        except Exception as e:
            print(f"[Mouse] Scroll error: {e}")
