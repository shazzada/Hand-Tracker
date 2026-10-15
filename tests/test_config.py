import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config import AppConfig


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "settings" / "config.json"
        patcher = patch.object(AppConfig, "get_config_path", return_value=self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, data):
        self.path.parent.mkdir(exist_ok=True)
        self.path.write_text(json.dumps(data))

    def test_invalid_field_types_do_not_reach_runtime(self):
        self.write(
            {
                "sensitivity": "fast",
                "camera_index": True,
                "mirror_camera": "false",
                "cad_drag_button": [],
                "pinch_threshold_left": 0,
                "mini_hud_opacity": float("nan"),
            }
        )
        config = AppConfig.load()
        self.assertEqual(config.sensitivity, 2.0)
        self.assertEqual(config.camera_index, 0)
        self.assertTrue(config.mirror_camera)
        self.assertEqual(config.cad_drag_button, "right")
        self.assertEqual(config.pinch_threshold_left, 0.03)
        self.assertEqual(config.mini_hud_opacity, 0.88)

    def test_unknown_keys_cannot_overwrite_methods(self):
        self.write({"save": "invalid", "RANGES": None, "new_setting": True})
        config = AppConfig.load()
        self.assertTrue(callable(config.save))
        self.assertIsInstance(config.RANGES, dict)

    def test_corrupt_and_non_object_files_use_defaults(self):
        self.path.parent.mkdir()
        for content in ("{bad", "[]", "null", "123"):
            with self.subTest(content=content):
                self.path.write_text(content)
                self.assertEqual(AppConfig.load(), AppConfig())

    def test_read_does_not_create_directories(self):
        self.assertEqual(AppConfig.load(), AppConfig())
        self.assertFalse(self.path.parent.exists())

    def test_mouse_control_is_never_restored(self):
        self.write({"is_tracking_enabled": True, "sensitivity": 2.5})
        config = AppConfig.load()
        self.assertFalse(config.is_tracking_enabled)
        config.is_tracking_enabled = True
        config.save()
        self.assertNotIn("is_tracking_enabled", json.loads(self.path.read_text()))
        self.assertEqual(AppConfig.load().sensitivity, 2.5)

    def test_failed_atomic_replace_keeps_old_settings(self):
        config = AppConfig()
        config.save()
        old = self.path.read_text()
        config.sensitivity = 3.0
        with patch("src.config.os.replace", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                config.save()
        self.assertEqual(self.path.read_text(), old)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_very_large_integer_clamps_without_overflow(self):
        self.write({"sensitivity": 10**1000})
        self.assertEqual(AppConfig.load().sensitivity, 3.5)
