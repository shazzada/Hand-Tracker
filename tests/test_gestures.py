import unittest

from src.config import AppConfig
from src.gestures import GestureEngine, GestureType
from src.tracker import HandLandmarksData


def create_dummy_hand_data(
    thumb_extended: bool = True,
    index_extended: bool = True,
    middle_extended: bool = True,
    ring_extended: bool = True,
    pinky_extended: bool = True,
    pinch_index_thumb: float = 0.2,
    pinch_middle_thumb: float = 0.2,
    pinch_ring_thumb: float = 0.2,
    pinch_pinky_thumb: float = 0.2,
    index_mcp_norm: tuple = (0.5, 0.5),
    index_tip_norm: tuple = (0.5, 0.3),
    is_fist: bool = False,
    is_index_pointing: bool = False,
) -> HandLandmarksData:
    """Helper to generate dummy HandLandmarksData for unit testing."""
    landmarks = [(0.5, 0.5, 0.0)] * 21
    return HandLandmarksData(
        landmarks=landmarks,
        pixel_landmarks=[(320, 240)] * 21,
        handedness="Right",
        palm_center_norm=(0.5, 0.5),
        index_mcp_norm=index_mcp_norm,
        index_tip_norm=index_tip_norm,
        hand_scale=0.2,
        thumb_extended=thumb_extended,
        index_extended=index_extended,
        middle_extended=middle_extended,
        ring_extended=ring_extended,
        pinky_extended=pinky_extended,
        pinch_index_thumb=pinch_index_thumb,
        pinch_middle_thumb=pinch_middle_thumb,
        pinch_ring_thumb=pinch_ring_thumb,
        pinch_pinky_thumb=pinch_pinky_thumb,
        is_fist=is_fist,
        is_index_pointing=is_index_pointing,
    )


class TestGestureEngine(unittest.TestCase):
    def setUp(self):
        self.config = AppConfig()
        self.config.pinch_threshold_left = 0.05
        self.config.pinch_threshold_middle = 0.05
        self.config.pinch_threshold_ring = 0.05
        self.config.pinch_threshold_pinky = 0.05
        self.config.cad_drag_button = "right"
        self.config.fist_toggle_hold_sec = 0.30
        self.config.is_tracking_enabled = True
        self.engine = GestureEngine(self.config)

    def test_open_hand_move_gesture(self):
        """All fingers extended with no pinch triggers MOVE."""
        hand = create_dummy_hand_data()
        event = self.engine.update(hand)
        self.assertEqual(event.gesture, GestureType.MOVE)
        self.assertTrue(event.allow_cursor_move)

    def test_sliding_circle_dial_zoom(self):
        """Drawing clockwise circles in the air triggers ROTATING_ZOOM_IN, counter-clockwise triggers ROTATING_ZOOM_OUT."""
        # Clockwise circular path points
        cw_pts = [
            (0.50, 0.30),
            (0.57, 0.33),
            (0.60, 0.40),
            (0.57, 0.47),
            (0.50, 0.50),
            (0.43, 0.47),
            (0.40, 0.40),
            (0.43, 0.33),
            (0.50, 0.30),
            (0.57, 0.33),
            (0.60, 0.40),
        ]

        last_event = None
        for pt in cw_pts:
            hand = create_dummy_hand_data(is_index_pointing=True, index_tip_norm=pt)
            last_event = self.engine.update(hand)

        self.assertEqual(last_event.gesture, GestureType.ROTATING_ZOOM_IN)
        self.assertTrue(last_event.scroll_delta > 0.0)
        self.assertFalse(last_event.allow_cursor_move)

    def test_open_palm_left_click(self):
        """Open palm with Index + Thumb touch triggers LEFT_CLICK, not zoom."""
        hand_pinched = create_dummy_hand_data(
            thumb_extended=True,
            index_extended=True,
            middle_extended=True,
            ring_extended=True,
            pinky_extended=True,
            pinch_index_thumb=0.03,
            is_index_pointing=False,
        )
        self.engine.update(hand_pinched)

        hand_released = create_dummy_hand_data(pinch_index_thumb=0.20, is_index_pointing=False)
        event = self.engine.update(hand_released)
        self.assertTrue(event.is_left_click_trigger)
        self.assertEqual(event.gesture, GestureType.LEFT_CLICK)

    def test_pinky_double_click(self):
        """Pinky and thumb pinch tap fires DOUBLE_CLICK."""
        hand_pinched = create_dummy_hand_data(pinch_pinky_thumb=0.03)
        self.engine.update(hand_pinched)

        hand_released = create_dummy_hand_data(pinch_pinky_thumb=0.2)
        event = self.engine.update(hand_released)
        self.assertTrue(event.is_double_click_trigger)
        self.assertEqual(event.gesture, GestureType.DOUBLE_CLICK)

    def test_medit_pan_drag_right_mouse(self):
        """Holding Middle + Thumb longer than drag_hold_sec triggers MEDIT_PAN_DRAG with is_right_down=True."""
        hand_pinched = create_dummy_hand_data(pinch_middle_thumb=0.03)
        self.engine.update(hand_pinched)

        self.engine.middle_pinch_start_time -= 0.4
        event = self.engine.update(hand_pinched)
        self.assertEqual(event.gesture, GestureType.MEDIT_PAN_DRAG)
        self.assertTrue(event.is_right_down)

    def test_fist_pause_and_resume_toggle(self):
        """Closed fist held pauses tracking, and another fist resumes."""
        fist_hand = create_dummy_hand_data(
            thumb_extended=False,
            index_extended=False,
            middle_extended=False,
            ring_extended=False,
            pinky_extended=False,
            is_fist=True,
        )

        self.assertTrue(self.config.is_tracking_enabled)

        # Fist hold -> triggers PAUSE
        self.engine.update(fist_hand)
        self.engine.fist_start_time -= 0.4
        event1 = self.engine.update(fist_hand)
        self.assertTrue(event1.is_fist_toggle)
        self.assertFalse(self.config.is_tracking_enabled)

        # Open hand (resets toggle flag)
        open_hand = create_dummy_hand_data(is_fist=False)
        self.engine.update(open_hand)

        # Second fist hold -> triggers RESUME
        self.engine.update(fist_hand)
        self.engine.fist_start_time -= 0.4
        event2 = self.engine.update(fist_hand)
        self.assertTrue(event2.is_fist_toggle)
        self.assertTrue(self.config.is_tracking_enabled)

    def test_fist_breaks_out_of_zoom_mode(self):
        """Closed fist should immediately break out of an active zoom lock and allow pausing."""
        # Enter zoom mode
        hand_pointing = create_dummy_hand_data(is_index_pointing=True)
        self.engine.update(hand_pointing)
        self.engine.update(hand_pointing)
        self.assertTrue(self.engine.is_zoom_locked)

        # Make closed fist
        fist_hand = create_dummy_hand_data(is_fist=True)
        self.engine.update(fist_hand)
        self.assertFalse(
            self.engine.is_zoom_locked, "Zoom lock must be cleared when a fist is made"
        )

        # Hold fist to trigger pause
        self.engine.fist_start_time -= 0.4
        event = self.engine.update(fist_hand)
        self.assertTrue(event.is_fist_toggle)
        self.assertFalse(self.config.is_tracking_enabled)

    def test_hand_loss_releases_active_drags(self):
        """When hand data is lost (None), active left and right drags must release."""
        # Start left drag
        hand_pinched = create_dummy_hand_data(pinch_index_thumb=0.03)
        self.engine.update(hand_pinched)
        self.engine.left_pinch_start_time -= 0.4
        event_drag = self.engine.update(hand_pinched)
        self.assertTrue(event_drag.is_left_down)
        self.assertTrue(self.engine.is_left_dragging)

        # Hand leaves camera
        event_lost = self.engine.update(None)
        self.assertTrue(event_lost.is_left_up, "Must emit left mouse up when hand leaves view")
        self.assertFalse(self.engine.is_left_dragging)

        # Start middle/right drag
        mid_pinched = create_dummy_hand_data(pinch_middle_thumb=0.03)
        self.engine.update(mid_pinched)
        self.engine.middle_pinch_start_time -= 0.4
        self.engine.update(mid_pinched)
        self.assertTrue(self.engine.is_middle_dragging)

        # Hand leaves camera
        event_lost2 = self.engine.update(None)
        self.assertTrue(
            event_lost2.is_right_up,
            "Must emit right mouse up when hand leaves view in right-CAD mode",
        )
        self.assertFalse(self.engine.is_middle_dragging)

    def test_pinky_pinch_with_curled_pinky(self):
        """Pinky pinch should trigger even if the pinky finger is curled during the pinch."""
        # Pinky is curled towards thumb
        hand_pinched = create_dummy_hand_data(
            pinky_extended=False,
            pinch_pinky_thumb=0.03,
            is_index_pointing=False,
        )
        self.engine.update(hand_pinched)
        self.assertTrue(self.engine.is_pinky_pinched)

        # Release pinky
        hand_released = create_dummy_hand_data(pinky_extended=True, pinch_pinky_thumb=0.2)
        event = self.engine.update(hand_released)
        self.assertTrue(event.is_double_click_trigger)
        self.assertEqual(event.gesture, GestureType.DOUBLE_CLICK)

    def test_middle_drag_middle_button_mode(self):
        """When cad_drag_button is 'middle', middle pinch drag emits is_middle_down and is_middle_up."""
        self.config.cad_drag_button = "middle"
        hand_pinched = create_dummy_hand_data(pinch_middle_thumb=0.03)
        self.engine.update(hand_pinched)
        self.engine.middle_pinch_start_time -= 0.4
        event = self.engine.update(hand_pinched)
        self.assertEqual(event.gesture, GestureType.MEDIT_PAN_DRAG)
        self.assertTrue(event.is_middle_down)
        self.assertFalse(event.is_right_down)

        # Release drag
        hand_open = create_dummy_hand_data(pinch_middle_thumb=0.20)
        event_release = self.engine.update(hand_open)
        self.assertTrue(event_release.is_middle_up)


class TestGestureRegressions(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch

        self.clock = patch("src.gestures.time.monotonic", return_value=0.0).start()
        self.addCleanup(patch.stopall)
        self.config = AppConfig(is_tracking_enabled=True)
        self.engine = GestureEngine(self.config)

    def update(self, seconds, **pose):
        self.clock.return_value = seconds
        return self.engine.update(create_dummy_hand_data(**pose))

    def test_time_zero_is_a_valid_pinch_start(self):
        self.update(0, pinch_index_thumb=0.01)
        event = self.update(0.1)
        self.assertTrue(event.is_left_click_trigger)
        self.assertFalse(event.allow_cursor_move)

    def test_hand_loss_cancels_pending_tap(self):
        self.update(10, pinch_index_thumb=0.01)
        self.clock.return_value = 10.05
        self.engine.update(None)
        event = self.update(10.1)
        self.assertFalse(event.is_left_click_trigger)

    def test_pause_cancels_pending_tap(self):
        self.update(10, pinch_index_thumb=0.01)
        self.config.is_tracking_enabled = False
        self.update(10.05)
        self.config.is_tracking_enabled = True
        self.assertFalse(self.update(10.1).is_left_click_trigger)

    def test_fist_cancels_pending_tap(self):
        self.update(10, pinch_index_thumb=0.01)
        self.update(10.05, is_fist=True)
        self.assertFalse(self.update(10.1).is_left_click_trigger)

    def test_zoom_entry_cancels_pending_tap_on_first_frame(self):
        self.update(10, pinch_index_thumb=0.01)
        self.update(10.05, is_index_pointing=True)
        self.assertFalse(self.update(10.1).is_left_click_trigger)

    def test_drag_changes_button_releases_original_and_waits_for_release(self):
        self.update(10, pinch_middle_thumb=0.01)
        self.assertTrue(self.update(10.4, pinch_middle_thumb=0.01).is_right_down)
        self.config.cad_drag_button = "middle"
        event = self.update(10.5, pinch_middle_thumb=0.01)
        self.assertTrue(event.is_right_up)
        self.assertFalse(event.is_middle_up)
        self.assertFalse(self.update(10.6, pinch_middle_thumb=0.01).is_middle_down)
        self.assertFalse(self.update(10.7).is_right_click_trigger)
        self.update(10.8, pinch_middle_thumb=0.01)
        self.assertTrue(self.update(11.2, pinch_middle_thumb=0.01).is_middle_down)

    def test_direct_pinch_switch_releases_drag_before_another_action(self):
        self.update(10, pinch_index_thumb=0.01)
        self.update(10.4, pinch_index_thumb=0.01)
        event = self.update(10.5, pinch_middle_thumb=0.01)
        self.assertTrue(event.is_left_up)
        self.assertFalse(event.is_right_down)
        self.assertFalse(event.is_left_click_trigger)
        self.update(10.6, pinch_middle_thumb=0.01)
        self.assertTrue(self.update(11, pinch_middle_thumb=0.01).is_right_down)

    def test_hysteresis_keeps_pinch_until_release_margin(self):
        self.update(10, pinch_index_thumb=0.05)
        self.update(10.05, pinch_index_thumb=0.06)
        self.assertTrue(self.engine.is_left_pinched)
        self.assertTrue(self.update(10.1, pinch_index_thumb=0.08).is_left_click_trigger)

    def test_closest_pinch_wins_and_only_one_action_fires(self):
        self.update(10, pinch_index_thumb=0.04, pinch_middle_thumb=0.01, pinch_pinky_thumb=0.03)
        self.assertTrue(self.engine.is_middle_pinched)
        self.assertFalse(self.engine.is_left_pinched)
        self.assertFalse(self.engine.is_pinky_pinched)
        event = self.update(10.1)
        self.assertTrue(event.is_right_click_trigger)
        self.assertFalse(event.is_double_click_trigger)
        self.assertFalse(event.is_left_click_trigger)

    def test_pinky_long_hold_still_double_clicks(self):
        self.update(10, pinch_pinky_thumb=0.01)
        event = self.update(11)
        self.assertTrue(event.is_double_click_trigger)
        self.assertEqual(event.gesture, GestureType.DOUBLE_CLICK)

    def test_fist_toggles_once_per_hold_starting_at_zero(self):
        self.update(0, is_fist=True)
        self.assertTrue(self.update(0.4, is_fist=True).is_fist_toggle)
        self.assertFalse(self.update(1, is_fist=True).is_fist_toggle)
        self.assertFalse(self.config.is_tracking_enabled)

    def test_click_gesture_is_preserved_on_curled_release(self):
        self.update(10, pinch_index_thumb=0.01)
        event = self.update(10.1, index_extended=False, middle_extended=False, ring_extended=False)
        self.assertTrue(event.is_left_click_trigger)
        self.assertEqual(event.gesture, GestureType.LEFT_CLICK)

    def test_straight_line_and_reversal_do_not_zoom(self):
        for i, point in enumerate(
            [(0.2, 0.4), (0.3, 0.4), (0.4, 0.4), (0.5, 0.4), (0.4, 0.4), (0.3, 0.4)]
        ):
            self.assertEqual(
                self.update(10 + i / 30, is_index_pointing=True, index_tip_norm=point).scroll_delta,
                0,
            )

    def test_counterclockwise_circle_zooms_out(self):
        import math

        for i in range(20):
            angle = -i * math.pi / 6
            event = self.update(
                10 + i / 30,
                is_index_pointing=True,
                index_tip_norm=(0.5 + 0.1 * math.cos(angle), 0.5 + 0.1 * math.sin(angle)),
            )
        self.assertLess(event.scroll_delta, 0)
        self.assertEqual(event.gesture, GestureType.ROTATING_ZOOM_OUT)
        event = self.update(11, is_index_pointing=True, index_tip_norm=event.trajectory_points[-1])
        self.assertEqual(event.scroll_delta, 0)

    def test_leaving_zoom_stops_scroll_immediately(self):
        self.update(10, is_index_pointing=True)
        self.update(10.1, is_index_pointing=True)
        self.engine.smoothed_zoom_rate = 15
        event = self.update(10.2)
        self.assertEqual(event.scroll_delta, 0)
        self.assertFalse(event.allow_cursor_move)
        self.assertEqual(self.update(10.3).gesture, GestureType.MOVE)


if __name__ == "__main__":
    unittest.main()
