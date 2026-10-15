import unittest
from unittest.mock import patch

from src.config import AppConfig
from src.mouse_controller import MouseController


class TestMouseController(unittest.TestCase):
    def setUp(self):
        patches = [
            patch("src.mouse_controller.pyautogui"),
            patch("src.mouse_controller.QUARTZ_AVAILABLE", False),
            patch.object(MouseController, "_load_displays"),
        ]
        for patcher in patches:
            self.addCleanup(patcher.stop)
            patcher.start()
        from src.mouse_controller import pyautogui

        pyautogui.size.return_value = (1920, 1080)
        pyautogui.position.return_value = (960, 540)
        self.config = AppConfig()
        self.config.active_margin_x = 0.15
        self.config.active_margin_y = 0.15
        self.config.smoothing_factor = 0.5
        self.config.sensitivity = 1.0
        self.config.adaptive_acceleration_enabled = True
        self.config.precision_dampening_factor = 0.40
        self.config.high_speed_boost_factor = 1.75
        self.controller = MouseController(self.config)
        self.controller.screen_width = 1920
        self.controller.screen_height = 1080
        self.controller.curr_x = 960.0
        self.controller.curr_y = 540.0

    def test_coordinate_mapping_center(self):
        """Center of camera frame (0.5, 0.5) maps to center of screen."""
        x, y = self.controller.map_coordinates(0.5, 0.5)
        self.assertAlmostEqual(x, (1920 - 1) / 2.0, delta=2.0)
        self.assertAlmostEqual(y, (1080 - 1) / 2.0, delta=2.0)

    def test_coordinate_mapping_margins(self):
        """Active margin (0.15) maps to edge of screen (0, 0)."""
        x, y = self.controller.map_coordinates(0.15, 0.15)
        self.assertAlmostEqual(x, 0.0, delta=0.5)
        self.assertAlmostEqual(y, 0.0, delta=0.5)

        # 1.0 - margin (0.85) maps to max screen bounds
        x_max, y_max = self.controller.map_coordinates(0.85, 0.85)
        self.assertAlmostEqual(x_max, 1919.0, delta=0.5)
        self.assertAlmostEqual(y_max, 1079.0, delta=0.5)

    def test_smoothing_filters_deadzone_jitter(self):
        """Small micro-tremors within deadzone (<1.2px) should stay pinned."""
        self.controller.curr_x = 500.0
        self.controller.curr_y = 500.0

        smooth_x, smooth_y = self.controller.smooth_coordinates(500.8, 500.8)
        self.assertEqual(smooth_x, 500)
        self.assertEqual(smooth_y, 500)

    def test_adaptive_precision_dampening(self):
        """Micro-movements (<6px) are dampened by precision factor for dental margin lines."""
        self.controller.curr_x = 500.0
        self.controller.curr_y = 500.0

        # Move by 3.0px
        smooth_x, _ = self.controller.smooth_coordinates(503.0, 500.0)
        # Expected displacement without acceleration: (503 - 500) * 0.5 = 1.5px -> 501.5
        # With 0.40 dampening: target is 500 + 3.0 * 0.40 = 501.2 -> smoothed is 500 + 1.2 * 0.5 = 500.6 -> round to 501
        self.assertEqual(smooth_x, 501)

    def test_adaptive_high_speed_boost(self):
        """Fast sweeps (>35px) are boosted dynamically for multi-monitor reach."""
        self.controller.curr_x = 500.0
        self.controller.curr_y = 500.0

        smooth_x, _ = self.controller.smooth_coordinates(600.0, 500.0)
        # Large sweep of 100px with dynamic boost reaches further than standard linear move
        self.assertTrue(smooth_x > 550)

    def test_mouse_controller_release_all(self):
        """release_all() should release left, right, and middle button hold states."""
        self.controller.is_left_down = True
        self.controller.is_right_down = True
        self.controller.is_middle_down = True

        self.controller.release_all()

        self.assertFalse(self.controller.is_left_down)
        self.assertFalse(self.controller.is_right_down)
        self.assertFalse(self.controller.is_middle_down)

    def test_effective_margins_with_sensitivity(self):
        """Effective margins should expand inwards as sensitivity increases."""
        # At sensitivity 1.0 with margin 0.15
        self.controller.config.sensitivity = 1.0
        self.controller.config.active_margin_x = 0.15
        self.controller.config.active_margin_y = 0.15
        eff_x1, eff_y1 = self.controller.get_effective_margins()
        self.assertAlmostEqual(eff_x1, 0.15, delta=0.01)

        # At sensitivity 2.0 with margin 0.15: span is halved, margins expand inwards
        self.controller.config.sensitivity = 2.0
        eff_x2, eff_y2 = self.controller.get_effective_margins()
        self.assertTrue(eff_x2 > eff_x1)
        self.assertAlmostEqual(eff_x2, 0.325, delta=0.01)

    def test_scroll_execution_no_error(self):
        """Calling scroll should execute cleanly without raising TypeError or exceptions."""
        try:
            self.controller.scroll(5.0)
            self.controller.scroll(-5.0)
        except Exception as e:
            self.fail(f"Scroll execution raised unexpected exception: {e}")


class TestMouseRegressions(unittest.TestCase):
    setUp = TestMouseController.setUp

    def test_fast_movement_does_not_overshoot_target(self):
        self.config.high_speed_boost_factor = 2.5
        self.controller.curr_x = 500.0
        positions = [self.controller.smooth_coordinates(1800.0, 540.0)[0] for _ in range(12)]
        self.assertTrue(all(500 <= x <= 1800 for x in positions))
        self.assertEqual(positions, sorted(positions))

    def test_internal_position_is_clamped(self):
        self.controller.smooth_coordinates(-1000, 10000)
        self.assertGreaterEqual(self.controller.curr_x, 0)
        self.assertLessEqual(self.controller.curr_y, 1079)

    def test_negative_monitor_coordinates(self):
        self.controller.screen_left = -1920
        self.controller.screen_width = 3840
        self.assertEqual(self.controller.map_coordinates(0, 0.5)[0], -1920)
        self.assertEqual(self.controller.map_coordinates(1, 0.5)[0], 1919)

    def test_fractional_scroll_is_accumulated(self):
        from src.mouse_controller import pyautogui

        for _ in range(5):
            self.controller.scroll(0.25)
        pyautogui.scroll.assert_called_once_with(1)
        self.assertAlmostEqual(self.controller._scroll_remainder, 0.25)

    def test_non_finite_input_rejected(self):
        for invalid in (float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                self.controller.map_coordinates(invalid, 0.5)
            with self.assertRaises(ValueError):
                self.controller.scroll(invalid)

    def test_release_attempts_every_button_after_one_fails(self):
        from src.mouse_controller import pyautogui

        self.controller.is_left_down = self.controller.is_right_down = (
            self.controller.is_middle_down
        ) = True
        pyautogui.mouseUp.side_effect = [OSError("left failed"), None, None]
        with self.assertRaises(RuntimeError):
            self.controller.release_all()
        self.assertEqual(pyautogui.mouseUp.call_count, 3)
        self.assertTrue(self.controller.is_left_down)
        self.assertFalse(self.controller.is_right_down)
        self.assertFalse(self.controller.is_middle_down)

    def test_click_failure_attempts_release(self):
        from src.mouse_controller import pyautogui

        self.config.audio_feedback_enabled = False
        pyautogui.mouseDown.side_effect = OSError("post failed")
        with self.assertRaises(OSError):
            self.controller.left_click()
        pyautogui.mouseUp.assert_called_once_with(button="left")
        self.assertFalse(self.controller.is_left_down)

    def test_double_click_posts_two_down_and_up_events(self):
        from src.mouse_controller import pyautogui

        self.config.audio_feedback_enabled = False
        with patch("src.mouse_controller.time.sleep"):
            self.controller.double_click()
        self.assertEqual(pyautogui.mouseDown.call_count, 2)
        self.assertEqual(pyautogui.mouseUp.call_count, 2)

    def test_display_gaps_snap_to_nearest_real_display(self):
        self.controller._display_bounds = [(0, 0, 1920, 1080), (1920, 0, 1280, 720)]
        self.controller.screen_width = 3200
        x, y = self.controller._clamp_position(2500, 1000)
        self.assertEqual((x, y), (2500, 719))


class TestQuartzEvents(unittest.TestCase):
    def test_double_click_sets_count_on_both_down_and_up(self):
        from unittest.mock import MagicMock

        from src import mouse_controller as module

        graphics = MagicMock()
        with (
            patch.object(module, "CG", graphics, create=True),
            patch.object(module, "IS_MACOS", True),
            patch.object(module, "QUARTZ_AVAILABLE", True),
            patch.object(module, "pyautogui") as mouse,
            patch.object(MouseController, "_load_displays"),
            patch.object(module.time, "sleep"),
        ):
            mouse.size.return_value = (1920, 1080)
            mouse.position.return_value = (500, 500)
            controller = MouseController(AppConfig(audio_feedback_enabled=False))
            controller.double_click()
        self.assertEqual(
            [call.args[2] for call in graphics.CGEventSetIntegerValueField.call_args_list],
            [1, 1, 2, 2],
        )
        self.assertEqual(graphics.CGEventPost.call_count, 4)

    def test_macos_scroll_uses_supported_quartz_function(self):
        from unittest.mock import MagicMock

        from src import mouse_controller as module

        graphics = MagicMock()
        with (
            patch.object(module, "CG", graphics, create=True),
            patch.object(module, "IS_MACOS", True),
            patch.object(module, "QUARTZ_AVAILABLE", True),
            patch.object(module, "pyautogui") as mouse,
            patch.object(MouseController, "_load_displays"),
        ):
            mouse.size.return_value = (1920, 1080)
            mouse.position.return_value = (500, 500)
            controller = MouseController(AppConfig())
            controller.scroll(2)
        graphics.CGEventCreateScrollWheelEvent.assert_called_once_with(
            None, graphics.kCGScrollEventUnitPixel, 1, 3
        )
        mouse.scroll.assert_not_called()


if __name__ == "__main__":
    unittest.main()
