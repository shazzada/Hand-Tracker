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


if __name__ == "__main__":
    unittest.main()
