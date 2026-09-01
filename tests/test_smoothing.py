import unittest
from src.config import AppConfig
from src.mouse_controller import MouseController


class TestMouseController(unittest.TestCase):
    def setUp(self):
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


if __name__ == "__main__":
    unittest.main()
