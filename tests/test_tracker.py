import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

from src.tracker import HandTracker


class TestTracker(unittest.TestCase):
    def setUp(self):
        self.tracker = HandTracker.__new__(HandTracker)
        self.tracker.hands = MagicMock()

    def result(self, points):
        landmarks = [SimpleNamespace(x=x, y=y, z=z) for x, y, z in points]
        self.tracker.hands.process.return_value = SimpleNamespace(
            multi_hand_landmarks=[SimpleNamespace(landmark=landmarks)],
            multi_handedness=[SimpleNamespace(classification=[SimpleNamespace(label="Right")])],
        )

    @staticmethod
    def physical_points():
        points = [(0.5, 0.4, 0.0)] * 21
        points[0] = (0.5, 0.6, 0.0)
        for mcp, x in ((5, 0.4), (9, 0.5), (13, 0.6), (17, 0.7)):
            points[mcp] = (x, 0.4, 0.0)
            points[mcp + 1] = (x, 0.3, 0.0)
            points[mcp + 2] = (x, 0.2, 0.0)
            points[mcp + 3] = (x, 0.1, 0.0)
        points[3] = (0.3, 0.35, 0.0)
        points[4] = (0.25, 0.3, 0.0)
        return points

    def test_measurements_are_invariant_to_camera_aspect_ratio(self):
        hands = []
        for height in (480, 360):
            points = [(x, y * 640 / height, z) for x, y, z in self.physical_points()]
            self.result(points)
            hand, _ = self.tracker.process_frame(
                np.zeros((height, 640, 3), dtype=np.uint8), mirror=False
            )
            hands.append(hand)
        self.assertAlmostEqual(hands[0].hand_scale, hands[1].hand_scale)
        self.assertAlmostEqual(hands[0].pinch_index_thumb, hands[1].pinch_index_thumb)
        self.assertEqual(hands[0].all_fingers_extended, hands[1].all_fingers_extended)
        self.assertFalse(hands[0].is_fist)

    def test_invalid_landmarks_do_not_generate_input(self):
        for points in ([(0.5, 0.5, 0.0)] * 20, [(float("nan"), 0.5, 0.0)] * 21):
            self.result(points)
            hand, _ = self.tracker.process_frame(np.zeros((480, 640, 3), dtype=np.uint8))
            self.assertIsNone(hand)

    def test_handedness_is_corrected_for_unmirrored_frame(self):
        self.result(self.physical_points())
        hand, _ = self.tracker.process_frame(np.zeros((480, 640, 3), dtype=np.uint8), mirror=False)
        self.assertEqual(hand.handedness, "Left")

    def test_dial_ready_hud_does_not_claim_zoom_in(self):
        self.result(self.physical_points())
        hand, frame = self.tracker.process_frame(np.zeros((480, 640, 3), dtype=np.uint8))
        with patch("src.tracker.cv2.putText") as text:
            self.tracker.draw_hud(frame, hand, "INDEX_DIAL_READY", 0.18, 0.18)
        labels = [call.args[1] for call in text.call_args_list]
        self.assertIn("DRAW CIRCLES IN AIR TO ZOOM", labels)
        self.assertFalse(any("ZOOM IN" in label for label in labels))

    def test_paused_hud_uses_supported_characters(self):
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        with patch("src.tracker.cv2.putText") as text:
            output = self.tracker.draw_hud(
                frame, None, "IDLE", 0.18, 0.18, is_tracking_enabled=False
            )
        self.assertTrue(all(call.args[1].isascii() for call in text.call_args_list))
        self.assertEqual(output.shape, frame.shape)
