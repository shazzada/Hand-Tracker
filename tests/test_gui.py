"""Real Tk layout tests with camera, global listeners and OS input disabled."""

import unittest
from unittest.mock import MagicMock, patch

from PIL import Image

from src.config import AppConfig
from src.gestures import GestureEngine, GestureEvent, GestureType
from src.gui import HandTrackerApp, open_camera_capture


class TestCameraOpen(unittest.TestCase):
    def test_every_failed_backend_is_released(self):
        with patch("src.gui.cv2.VideoCapture") as capture:
            capture.return_value.isOpened.return_value = False
            self.assertIsNone(open_camera_capture(2))
            self.assertEqual(capture.return_value.release.call_count, capture.call_count)

    def test_successful_capture_is_owned_by_caller(self):
        with patch("src.gui.cv2.VideoCapture") as capture:
            capture.return_value.read.return_value = (True, MagicMock(size=10))
            self.assertIs(open_camera_capture(2), capture.return_value)
            capture.return_value.release.assert_not_called()


class TestDesktopUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.start_patch = patch.object(HandTrackerApp, "start_tracking")
        cls.hotkey_patch = patch.object(HandTrackerApp, "_setup_hotkeys")
        cls.start_patch.start()
        cls.hotkey_patch.start()
        try:
            cls.app = HandTrackerApp(AppConfig(audio_feedback_enabled=False))
        except Exception:
            cls.start_patch.stop()
            cls.hotkey_patch.stop()
            raise
        cls.callback_errors = []
        cls.app.report_callback_exception = lambda *error: cls.callback_errors.append(error)
        cls.app.update()

    @classmethod
    def tearDownClass(cls):
        cls.app.on_close()
        cls.start_patch.stop()
        cls.hotkey_patch.stop()
        if cls.callback_errors:
            raise AssertionError(cls.callback_errors)

    def setUp(self):
        app = self.app
        if app.config.mini_hud_mode:
            app._toggle_mini_hud()
        app.config.is_tracking_enabled = False
        app.config.audio_feedback_enabled = False
        app.mouse_controller = MagicMock()
        app.gesture_engine = GestureEngine(app.config)
        app._show_camera_state("ready", "Camera connected")
        app.tabs.set("Controls")
        app.update()

    def test_initial_layout_fits_supported_small_window(self):
        self.app.geometry("860x600")
        self.app.update()
        for widget in (
            self.app.right_frame,
            self.app.pause_btn,
            self.app.pip_btn,
            self.app.left_frame,
        ):
            self.assertGreaterEqual(widget.winfo_rootx(), self.app.winfo_rootx())
            self.assertLessEqual(
                widget.winfo_rootx() + widget.winfo_width(), self.app.winfo_rootx() + 860
            )
        self.assertTrue(self.app.save_btn.winfo_viewable())

    def test_pause_releases_actual_worker_controller(self):
        self.app._set_tracking(True)
        self.assertTrue(self.app.config.is_tracking_enabled)
        self.app.mouse_controller.reset_mock()
        self.app._set_tracking(False)
        self.app.mouse_controller.release_all.assert_called_once()
        self.assertFalse(self.app.config.is_tracking_enabled)

    def test_cannot_resume_without_camera(self):
        self.app._show_camera_state("offline", "Camera missing")
        self.app._set_tracking(True)
        self.assertFalse(self.app.config.is_tracking_enabled)
        self.assertEqual(self.app.pause_btn.cget("state"), "disabled")

    def test_compact_window_fits_and_restores_geometry(self):
        app = self.app
        app.geometry("1000x700+40+40")
        app.update()
        original = app.geometry()
        app._toggle_mini_hud()
        app.geometry("180x140")
        app.update()
        self.assertTrue(app.pause_btn.winfo_viewable())
        self.assertTrue(app.pip_btn.winfo_viewable())
        self.assertFalse(app.right_frame.winfo_viewable())
        self.assertLessEqual(
            app.pip_btn.winfo_rootx() + app.pip_btn.winfo_width(), app.winfo_rootx() + 180
        )
        app._toggle_mini_hud()
        app.update()
        self.assertEqual(app.geometry(), original)
        self.assertTrue(app.right_frame.winfo_viewable())

    def test_preview_preserves_aspect_ratio_and_shrinks_to_pip(self):
        app = self.app
        app._last_image = Image.new("RGB", (640, 480), "#123456")
        app._toggle_mini_hud()
        app.geometry("180x140")
        app.update()
        app._render_preview()
        app.update()
        width, height = app.video_label.image.cget("size")
        self.assertLessEqual(width, app.video_container.winfo_width())
        self.assertLessEqual(height, app.video_container.winfo_height())
        self.assertAlmostEqual(width / height, 4 / 3, delta=0.03)

    def test_camera_error_clears_stale_preview(self):
        app = self.app
        app._last_image = Image.new("RGB", (640, 480))
        app._render_preview()
        app._show_camera_state("offline", "Camera missing")
        self.assertIsNone(app._last_image)
        self.assertFalse(app.video_label.winfo_ismapped())
        self.assertIn("unavailable", app.video_message.cget("text"))

    def test_save_failure_is_visible(self):
        with patch.object(self.app.config, "save", side_effect=OSError("read-only disk")):
            self.app._on_save_config()
        self.assertIn("Could not save", self.app.feedback_label.cget("text"))

    def test_reset_pauses_and_refreshes_switches(self):
        self.app._set_tracking(True)
        self.app.config.show_landmarks = False
        self.app._on_reset_defaults()
        self.assertFalse(self.app.config.is_tracking_enabled)
        self.assertEqual(self.app.switches["show_landmarks"].get(), 1)
        self.assertEqual(self.app.sliders["sensitivity"][0].get(), 2.0)
        self.app.config.audio_feedback_enabled = False

    def test_global_callbacks_are_consumed_on_ui_thread(self):
        self.app.command_queue.put("toggle")
        self.app._poll_queue()
        self.assertTrue(self.app.config.is_tracking_enabled)
        self.app.command_queue.put("toggle")
        self.app._poll_queue()
        self.assertFalse(self.app.config.is_tracking_enabled)

    def test_reconnect_pauses_and_requests_worker_restart(self):
        self.app._set_tracking(True)
        self.app._on_reconnect_camera()
        self.assertFalse(self.app.config.is_tracking_enabled)
        self.assertTrue(self.app.reconnect_event.is_set())
        self.app.reconnect_event.clear()

    def test_polling_is_rescheduled_after_a_preview_error(self):
        with (
            patch.object(self.app, "_render_preview", side_effect=RuntimeError("preview failed")),
            patch.object(self.app, "after") as schedule,
        ):
            with self.assertRaises(RuntimeError):
                self.app._poll_queue()
        schedule.assert_called_once_with(30, self.app._poll_queue)

    def test_preview_watchdog_releases_input(self):
        self.app._set_tracking(True)
        self.app._last_frame_at = -100
        self.app._poll_queue()
        self.assertFalse(self.app.config.is_tracking_enabled)
        self.assertFalse(self.app._camera_ready)
        self.app.mouse_controller.release_all.assert_called()
        self.app.reconnect_event.clear()

    def test_worker_initialization_failure_is_reported_and_cleaned_up(self):
        with (
            patch("src.gui.HandTracker", side_effect=RuntimeError("model unavailable")),
            self.assertLogs("src.gui", level="ERROR"),
        ):
            self.app._tracking_worker()
        self.assertFalse(self.app.config.is_tracking_enabled)
        state, message = self.app.status_queue.get_nowait()
        self.assertEqual(state, "error")
        self.assertIn("model unavailable", message)
        self.app.mouse_controller.release_all.assert_called()

    def test_worker_camera_read_failure_releases_before_retry(self):
        import numpy as np

        app = self.app
        app.config.is_tracking_enabled = True
        tracker = MagicMock()
        hand = MagicMock()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        tracker.process_frame.return_value = (hand, frame)
        tracker.draw_hud.return_value = frame
        capture = MagicMock()
        reads = []

        def read_capture():
            reads.append(True)
            if len(reads) == 1:
                # Simulate the user resuming after a new connection starts paused.
                app.config.is_tracking_enabled = True
                return True, frame
            return False, None

        capture.read.side_effect = read_capture
        engine = MagicMock()
        engine.update.return_value = GestureEvent(GestureType.MEDIT_PAN_DRAG, is_right_down=True)
        controller = MagicMock()
        controller.get_effective_margins.return_value = (0.18, 0.18)
        calls = []

        def open_capture(index):
            calls.append(index)
            if len(calls) == 1:
                return capture
            controller.release_all.assert_called()
            self.assertFalse(app.config.is_tracking_enabled)
            app.stop_event.set()
            return None

        with (
            patch("src.gui.HandTracker", return_value=tracker),
            patch("src.gui.MouseController", return_value=controller),
            patch("src.gui.GestureEngine", return_value=engine),
            patch("src.gui.open_camera_capture", side_effect=open_capture),
            patch.object(app.stop_event, "wait"),
        ):
            # Skip the reconnect delay in this deterministic failure-path test.
            with patch("src.gui.time.monotonic", side_effect=range(100, 1000)):
                app._tracking_worker()
        app.stop_event.clear()
        self.assertEqual(calls, [0, 0])
        capture.release.assert_called()
        tracker.release.assert_called_once()
        controller.right_down.assert_called_once()
        while not app.status_queue.empty():
            app.status_queue.get_nowait()
        while not app.frame_queue.empty():
            app.frame_queue.get_nowait()

    def test_resume_permission_failure_stays_paused_and_releases(self):
        self.app.mouse_controller.ensure_access.side_effect = PermissionError(
            "Accessibility required"
        )
        with self.assertLogs("src.gui", level="ERROR"):
            self.app._set_tracking(True)
        self.assertFalse(self.app.config.is_tracking_enabled)
        self.assertIn("Input unavailable", self.app.feedback_label.cget("text"))
        self.app.mouse_controller.release_all.assert_called()

    def test_zz_shutdown_releases_controller_and_stops_listener(self):
        app = self.app
        app._hotkey_listener = MagicMock()
        controller = app.mouse_controller
        app.config.is_tracking_enabled = True
        app.on_close()
        self.assertTrue(app.stop_event.is_set())
        self.assertFalse(app.config.is_tracking_enabled)
        controller.release_all.assert_called_once()
        app._hotkey_listener.stop.assert_called_once()
