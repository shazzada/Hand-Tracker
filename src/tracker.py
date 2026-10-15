import logging
import math
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class HandLandmarksData:
    landmarks: list[tuple[float, float, float]]  # Normalized (x, y, z) 0.0 - 1.0
    pixel_landmarks: list[tuple[int, int]]  # Pixel coordinates (px, py)
    handedness: str  # 'Left' or 'Right'
    palm_center_norm: tuple[float, float]  # Normalized (x, y)
    index_mcp_norm: tuple[float, float]  # Normalized (x, y) - Stable tracking anchor
    index_tip_norm: tuple[float, float]  # Normalized (x, y) of Index Fingertip
    hand_scale: float  # Wrist to Middle MCP distance for normalization

    # Finger states (True if extended/open)
    thumb_extended: bool
    index_extended: bool
    middle_extended: bool
    ring_extended: bool
    pinky_extended: bool

    # Distance measurements (normalized by hand scale)
    pinch_index_thumb: float  # Distance between landmark 4 and 8
    pinch_middle_thumb: float  # Distance between landmark 4 and 12 (Medit 3D Pan/Rotate Drag)
    pinch_ring_thumb: float  # Distance between landmark 4 and 16
    pinch_pinky_thumb: float  # Distance between landmark 4 and 20 (Double-Click)

    # Special Poses
    is_fist: bool  # True if hand is closed into a fist
    is_index_pointing: bool  # True if Index is dominant (☝️) and other 3 fingers are shorter/curled

    @property
    def all_fingers_extended(self) -> bool:
        """Returns True if all 5 fingers are open/flexed."""
        return (
            self.thumb_extended
            and self.index_extended
            and self.middle_extended
            and self.ring_extended
            and self.pinky_extended
        )

    @property
    def four_fingers_extended(self) -> bool:
        """Returns True if at least 3-4 fingers are extended."""
        extended_count = sum(
            [self.index_extended, self.middle_extended, self.ring_extended, self.pinky_extended]
        )
        return extended_count >= 3


class HandTracker:
    def __init__(
        self,
        max_num_hands: int = 1,
        min_detection_confidence: float = 0.60,
        min_tracking_confidence: float = 0.60,
    ):
        import mediapipe as mp

        if not hasattr(mp, "solutions"):
            raise RuntimeError(
                "This tracker requires MediaPipe 0.10.14–0.10.21. Run the launcher to repair dependencies"
            )
        self.mp_hands = mp.solutions.hands

        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=max_num_hands,
            model_complexity=1,
            min_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )

    @staticmethod
    def _dist_2d(p1: tuple[float, float], p2: tuple[float, float]) -> float:
        return math.hypot(p1[0] - p2[0], p1[1] - p2[1])

    @staticmethod
    def _dist_3d(p1: tuple[float, float, float], p2: tuple[float, float, float]) -> float:
        return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2 + (p1[2] - p2[2]) ** 2)

    def process_frame(
        self, frame_bgr: np.ndarray, mirror: bool = True
    ) -> tuple[HandLandmarksData | None, np.ndarray]:
        """
        Process a single OpenCV BGR frame.
        Returns:
            HandLandmarksData (or None if no hand detected) and flipped/annotated frame_bgr.
        """
        if mirror:
            frame_bgr = cv2.flip(frame_bgr, 1)

        h, w, _ = frame_bgr.shape
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        frame_rgb.flags.writeable = False
        results = self.hands.process(frame_rgb)

        hand_data: HandLandmarksData | None = None

        if results.multi_hand_landmarks and len(results.multi_hand_landmarks) > 0:
            hand_landmarks = results.multi_hand_landmarks[0]

            # Handedness label
            handedness_label = "Right"
            if results.multi_handedness and len(results.multi_handedness) > 0:
                handedness_label = results.multi_handedness[0].classification[0].label

            raw_pts: list[tuple[float, float, float]] = [
                (float(lm.x), float(lm.y), float(lm.z)) for lm in hand_landmarks.landmark
            ]
            if len(raw_pts) != 21 or not all(math.isfinite(v) for point in raw_pts for v in point):
                return None, frame_bgr
            if not mirror:
                handedness_label = "Left" if handedness_label == "Right" else "Right"
            # MediaPipe x/z use image width, whereas y uses image height.
            # Measure in one coordinate system so wide cameras do not distort poses.
            metric_pts = [(x, y * h / w, z) for x, y, z in raw_pts]
            pixel_pts: list[tuple[int, int]] = [
                (int(lm.x * w), int(lm.y * h)) for lm in hand_landmarks.landmark
            ]

            # Scale estimation: Wrist #0 to Middle MCP #9
            wrist = metric_pts[0]
            middle_mcp = metric_pts[9]
            index_mcp = metric_pts[5]
            pinky_mcp = metric_pts[17]

            palm_width = self._dist_2d((index_mcp[0], index_mcp[1]), (pinky_mcp[0], pinky_mcp[1]))
            wrist_to_mid = self._dist_2d((wrist[0], wrist[1]), (middle_mcp[0], middle_mcp[1]))
            hand_scale = max(palm_width, wrist_to_mid)
            if hand_scale < 1e-4:
                hand_scale = 0.2

            # Palm center
            palm_x = (raw_pts[5][0] + raw_pts[9][0] + raw_pts[17][0] + raw_pts[0][0]) / 4.0
            palm_y = (raw_pts[5][1] + raw_pts[9][1] + raw_pts[17][1] + raw_pts[0][1]) / 4.0
            palm_center = (palm_x, palm_y)

            # Index MCP (#5): Stable anchor point
            anchor_norm = (raw_pts[5][0], raw_pts[5][1])
            index_tip_norm = (raw_pts[8][0], raw_pts[8][1])

            # Thumb extension
            dist_thumb_tip_mcp = self._dist_2d(
                (metric_pts[4][0], metric_pts[4][1]), (metric_pts[17][0], metric_pts[17][1])
            )
            dist_thumb_ip_mcp = self._dist_2d(
                (metric_pts[3][0], metric_pts[3][1]), (metric_pts[17][0], metric_pts[17][1])
            )
            thumb_open = dist_thumb_tip_mcp > dist_thumb_ip_mcp * 1.08

            # Finger extension lengths measured from each finger's own MCP knuckle joint
            len_index = self._dist_2d(
                (metric_pts[8][0], metric_pts[8][1]), (metric_pts[5][0], metric_pts[5][1])
            )
            len_middle = self._dist_2d(
                (metric_pts[12][0], metric_pts[12][1]), (metric_pts[9][0], metric_pts[9][1])
            )
            len_ring = self._dist_2d(
                (metric_pts[16][0], metric_pts[16][1]), (metric_pts[13][0], metric_pts[13][1])
            )
            len_pinky = self._dist_2d(
                (metric_pts[20][0], metric_pts[20][1]), (metric_pts[17][0], metric_pts[17][1])
            )

            index_open = len_index > (hand_scale * 0.70)
            middle_open = len_middle > (hand_scale * 0.70)
            ring_open = len_ring > (hand_scale * 0.70)
            pinky_open = len_pinky > (hand_scale * 0.70)

            # 1. Closed Fist: ALL 4 fingers are curled tight into their knuckles
            is_fist = (
                (len_index < hand_scale * 0.65)
                and (len_middle < hand_scale * 0.65)
                and (len_ring < hand_scale * 0.65)
                and (len_pinky < hand_scale * 0.65)
            )

            # 2. Index Pointing / Air Dial Zoom (☝️):
            # Index is long and significantly longer than Middle, Ring, and Pinky at ANY clock angle (12, 3, 6, 9)
            is_index_pointing = (
                (not is_fist)
                and (len_index > hand_scale * 0.65)
                and (len_index > len_middle * 1.25)
                and (len_index > len_ring * 1.25)
                and (len_index > len_pinky * 1.25)
            )

            # Normalized Pinch distances:
            if is_index_pointing or is_fist:
                # 100% SUPPRESS all pinches during index pointing and fist to prevent false triggers
                pinch_idx_thumb_norm = 1.0
                pinch_mid_thumb_norm = 1.0
                pinch_ring_thumb_norm = 1.0
                pinch_pinky_thumb_norm = 1.0
            else:
                pinch_idx_thumb_raw = self._dist_3d(metric_pts[4], metric_pts[8])
                pinch_idx_thumb_norm = pinch_idx_thumb_raw / (hand_scale * 3.2)

                pinch_mid_thumb_raw = self._dist_3d(metric_pts[4], metric_pts[12])
                pinch_mid_thumb_norm = pinch_mid_thumb_raw / (hand_scale * 3.2)

                pinch_ring_thumb_raw = self._dist_3d(metric_pts[4], metric_pts[16])
                pinch_ring_thumb_norm = pinch_ring_thumb_raw / (hand_scale * 3.2)

                pinch_pinky_thumb_raw = self._dist_3d(metric_pts[4], metric_pts[20])
                pinch_pinky_thumb_norm = pinch_pinky_thumb_raw / (hand_scale * 3.2)

            hand_data = HandLandmarksData(
                landmarks=raw_pts,
                pixel_landmarks=pixel_pts,
                handedness=handedness_label,
                palm_center_norm=palm_center,
                index_mcp_norm=anchor_norm,
                index_tip_norm=index_tip_norm,
                hand_scale=hand_scale,
                thumb_extended=thumb_open,
                index_extended=index_open,
                middle_extended=middle_open,
                ring_extended=ring_open,
                pinky_extended=pinky_open,
                pinch_index_thumb=pinch_idx_thumb_norm,
                pinch_middle_thumb=pinch_mid_thumb_norm,
                pinch_ring_thumb=pinch_ring_thumb_norm,
                pinch_pinky_thumb=pinch_pinky_thumb_norm,
                is_fist=is_fist,
                is_index_pointing=is_index_pointing,
            )

        return hand_data, frame_bgr

    def draw_hud(
        self,
        frame_bgr: np.ndarray,
        hand_data: HandLandmarksData | None,
        gesture_name: str,
        active_margin_x: float,
        active_margin_y: float,
        show_landmarks: bool = True,
        show_active_box: bool = True,
        is_tracking_enabled: bool = True,
        fist_progress: float = 0.0,
        trajectory_points: list[tuple[float, float]] | None = None,
        effective_margin_x: float | None = None,
        effective_margin_y: float | None = None,
    ) -> np.ndarray:
        """Renders cyber-dark aesthetic HUD with Rotational Circle Zoom indicators."""
        h, w, _ = frame_bgr.shape
        overlay = frame_bgr.copy()

        # 1. Active Boundary Box (calibrated to actual screen mapping)
        if show_active_box:
            eff_mx = effective_margin_x if effective_margin_x is not None else active_margin_x
            eff_my = effective_margin_y if effective_margin_y is not None else active_margin_y
            min_x = max(0, int(eff_mx * w))
            max_x = min(w - 1, int((1.0 - eff_mx) * w))
            min_y = max(0, int(eff_my * h))
            max_y = min(h - 1, int((1.0 - eff_my) * h))

            mask = np.zeros((h, w), dtype=np.uint8)
            cv2.rectangle(mask, (min_x, min_y), (max_x, max_y), 255, -1)
            overlay[mask == 0] = (overlay[mask == 0] * 0.78).astype(np.uint8)

            box_color = (0, 230, 118) if is_tracking_enabled else (80, 80, 220)
            cv2.rectangle(overlay, (min_x, min_y), (max_x, max_y), box_color, 1, cv2.LINE_AA)
            c_len = 20
            thick = 3
            cv2.line(overlay, (min_x, min_y), (min_x + c_len, min_y), box_color, thick)
            cv2.line(overlay, (min_x, min_y), (min_x, min_y + c_len), box_color, thick)
            cv2.line(overlay, (max_x, min_y), (max_x - c_len, min_y), box_color, thick)
            cv2.line(overlay, (max_x, min_y), (max_x, min_y + c_len), box_color, thick)
            cv2.line(overlay, (min_x, max_y), (min_x + c_len, max_y), box_color, thick)
            cv2.line(overlay, (min_x, max_y), (min_x, max_y - c_len), box_color, thick)
            cv2.line(overlay, (max_x, max_y), (max_x - c_len, max_y), box_color, thick)
            cv2.line(overlay, (max_x, max_y), (max_x, max_y - c_len), box_color, thick)

        # 2. Hand Landmark Skeleton & Glowing Joints
        if hand_data and show_landmarks:
            px = hand_data.pixel_landmarks

            connections = [
                # Thumb
                (0, 1),
                (1, 2),
                (2, 3),
                (3, 4),
                # Index
                (0, 5),
                (5, 6),
                (6, 7),
                (7, 8),
                # Middle
                (5, 9),
                (9, 10),
                (10, 11),
                (11, 12),
                # Ring
                (9, 13),
                (13, 14),
                (14, 15),
                (15, 16),
                # Pinky
                (13, 17),
                (17, 18),
                (18, 19),
                (19, 20),
                # Base
                (0, 17),
            ]
            for p1, p2 in connections:
                cv2.line(overlay, px[p1], px[p2], (210, 210, 210), 2, cv2.LINE_AA)

            # Draw joints
            for i, pt in enumerate(px):
                if i in (4, 8, 12, 16, 20):
                    cv2.circle(overlay, pt, 7, (255, 180, 0), -1, cv2.LINE_AA)
                    cv2.circle(overlay, pt, 10, (255, 255, 255), 1, cv2.LINE_AA)
                else:
                    cv2.circle(overlay, pt, 4, (0, 215, 255), -1, cv2.LINE_AA)

            # Highlight Rotational Circular Trail around Index Fingertip
            if hand_data.is_index_pointing or "ROTATING" in gesture_name or "DIAL" in gesture_name:
                tip_px = px[8]

                # Draw recent circular trail points
                if trajectory_points and len(trajectory_points) >= 2:
                    trail_pts = [(int(p[0] * w), int(p[1] * h)) for p in trajectory_points]
                    for idx in range(len(trail_pts) - 1):
                        alpha = (idx + 1) / len(trail_pts)
                        trail_color = (0, int(255 * alpha), int(200 * alpha))
                        cv2.line(
                            overlay, trail_pts[idx], trail_pts[idx + 1], trail_color, 3, cv2.LINE_AA
                        )

                dial_color = (
                    (0, 255, 120)
                    if gesture_name == "ROTATING_ZOOM_IN"
                    else ((255, 50, 150) if gesture_name == "ROTATING_ZOOM_OUT" else (0, 230, 255))
                )
                cv2.circle(overlay, tip_px, 26, dial_color, 2, cv2.LINE_AA)
                cv2.circle(overlay, tip_px, 8, (255, 255, 255), -1, cv2.LINE_AA)

                # Direction Arrow Banner
                if gesture_name == "ROTATING_ZOOM_IN":
                    cv2.putText(
                        overlay,
                        ">> CLOCKWISE: ZOOM IN (+)",
                        (max(20, tip_px[0] - 120), max(40, tip_px[1] - 35)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.60,
                        (0, 255, 120),
                        2,
                        cv2.LINE_AA,
                    )
                elif gesture_name == "ROTATING_ZOOM_OUT":
                    cv2.putText(
                        overlay,
                        "<< ANTICLOCKWISE: ZOOM OUT (-)",
                        (max(20, tip_px[0] - 140), max(40, tip_px[1] - 35)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.60,
                        (255, 50, 150),
                        2,
                        cv2.LINE_AA,
                    )
                else:
                    cv2.putText(
                        overlay,
                        "DRAW CIRCLES IN AIR TO ZOOM",
                        (max(20, tip_px[0] - 130), max(40, tip_px[1] - 35)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55,
                        (0, 230, 255),
                        2,
                        cv2.LINE_AA,
                    )

            elif "LEFT" in gesture_name or gesture_name in ("CLICKING", "LEFT_DRAG"):
                cv2.line(overlay, px[4], px[8], (0, 255, 0), 4, cv2.LINE_AA)
                cv2.circle(overlay, px[8], 12, (0, 255, 0), 2, cv2.LINE_AA)
            elif "PAN" in gesture_name or "ORBIT" in gesture_name or "RIGHT" in gesture_name:
                cv2.line(overlay, px[4], px[12], (0, 140, 255), 4, cv2.LINE_AA)
                cv2.circle(overlay, px[12], 12, (0, 140, 255), 2, cv2.LINE_AA)
            elif "DOUBLE" in gesture_name:
                cv2.line(overlay, px[4], px[20], (0, 230, 255), 4, cv2.LINE_AA)
                cv2.circle(overlay, px[20], 12, (0, 230, 255), 2, cv2.LINE_AA)

            # Tracking anchor target (Index MCP #5)
            anchor = px[5]
            cv2.circle(overlay, anchor, 5, (0, 0, 255), -1, cv2.LINE_AA)
            cv2.circle(overlay, anchor, 12, (0, 0, 255), 2, cv2.LINE_AA)

        # 3. Status Pill & Fist Progress Indicator
        if fist_progress > 0.0 and fist_progress < 1.0:
            pct = int(fist_progress * 100)
            target_state = "PAUSING" if is_tracking_enabled else "RESUMING"
            badge_text = f"FIST: {target_state} ({pct}%)"
            color = (0, 215, 255)
            pill_w = 280
        elif not is_tracking_enabled:
            badge_text = "PAUSED - Hold fist to resume"
            color = (50, 50, 220)
            pill_w = 300
        else:
            badge_text = {
                "IDLE": "Hand idle" if hand_data else "No hand in view",
                "MOVE": "Move cursor",
                "INDEX_DIAL_READY": "Dial ready - draw circles",
                "ROTATING_ZOOM_IN": "Clockwise - zoom in",
                "ROTATING_ZOOM_OUT": "Anticlockwise - zoom out",
                "CLICKING": "Pinch held",
                "MEDIT_PAN_DRAG": "CAD drag",
            }.get(gesture_name, gesture_name.replace("_", " ").title())
            pill_w = 290
            badge_colors = {
                "MOVE": (40, 190, 70),  # Green
                "ROTATING_ZOOM_IN": (0, 230, 100),  # Bright Neon Green
                "ROTATING_ZOOM_OUT": (255, 50, 150),  # Neon Pink
                "INDEX_DIAL_READY": (0, 230, 255),  # Cyan
                "CLICKING": (0, 220, 255),  # Cyan
                "LEFT_CLICK": (220, 120, 0),  # Blue
                "LEFT_DRAG": (200, 50, 200),  # Purple
                "MEDIT_PAN_DRAG": (0, 140, 255),  # Orange
                "DOUBLE_CLICK": (0, 230, 255),  # Gold
                "RIGHT_CLICK": (0, 150, 255),  # Orange
                "IDLE": (90, 90, 90),  # Gray
            }
            color = badge_colors.get(gesture_name, (120, 120, 120))

        # Fit the full status text, including on lower-resolution camera frames.
        text_width = cv2.getTextSize(badge_text, cv2.FONT_HERSHEY_SIMPLEX, 0.52, 2)[0][0]
        pill_w = min(w - 30, text_width + 48)
        text_scale = min(0.52, 0.52 * max(1, pill_w - 42) / max(1, text_width))
        # Badge pill at top left
        cv2.rectangle(overlay, (15, 15), (15 + pill_w, 55), (20, 20, 20), -1)
        cv2.rectangle(overlay, (15, 15), (15 + pill_w, 55), color, 2, cv2.LINE_AA)
        cv2.circle(overlay, (32, 35), 7, color, -1, cv2.LINE_AA)
        cv2.putText(
            overlay,
            badge_text,
            (48, 41),
            cv2.FONT_HERSHEY_SIMPLEX,
            text_scale,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )

        return overlay

    def release(self):
        """Cleanly releases MediaPipe resources."""
        if hasattr(self, "hands") and self.hands:
            try:
                self.hands.close()
            except Exception:
                logging.getLogger(__name__).exception("Could not close hand model")
