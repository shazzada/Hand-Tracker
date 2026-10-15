"""Validated preferences with atomic persistence; mouse control is session-only."""

import json
import math
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import ClassVar


@dataclass
class AppConfig:
    sensitivity: float = 2.0
    smoothing_factor: float = 0.50
    active_margin_x: float = 0.18
    active_margin_y: float = 0.18
    pinch_threshold_left: float = 0.055
    pinch_threshold_middle: float = 0.055
    pinch_threshold_ring: float = 0.055  # Read older configuration files.
    pinch_threshold_pinky: float = 0.055
    pinch_hysteresis: float = 0.020
    cad_drag_button: str = "right"
    sniper_mode_scale: float = 0.30  # Reserved; no gesture currently activates it.
    audio_feedback_enabled: bool = True
    eco_battery_saver_enabled: bool = True
    scroll_speed: float = 1.2
    click_freeze_sec: float = 0.14
    click_debounce_sec: float = 0.28
    drag_hold_sec: float = 0.28
    fist_toggle_hold_sec: float = 0.30
    camera_index: int = 0
    mirror_camera: bool = True
    show_landmarks: bool = True
    show_active_box: bool = True
    adaptive_acceleration_enabled: bool = True
    precision_dampening_factor: float = 0.40
    high_speed_boost_factor: float = 1.75
    mini_hud_mode: bool = False
    mini_hud_opacity: float = 0.88
    is_tracking_enabled: bool = False

    RANGES: ClassVar[dict] = {
        "sensitivity": (0.5, 3.5),
        "smoothing_factor": (0.1, 0.9),
        "active_margin_x": (0.05, 0.35),
        "active_margin_y": (0.05, 0.35),
        "pinch_threshold_left": (0.03, 0.09),
        "pinch_threshold_middle": (0.03, 0.09),
        "pinch_threshold_ring": (0.03, 0.09),
        "pinch_threshold_pinky": (0.03, 0.09),
        "pinch_hysteresis": (0.005, 0.06),
        "sniper_mode_scale": (0.15, 0.60),
        "scroll_speed": (0.5, 3.0),
        "click_freeze_sec": (0.0, 0.5),
        "click_debounce_sec": (0.1, 1.0),
        "drag_hold_sec": (0.15, 1.0),
        "fist_toggle_hold_sec": (0.1, 2.0),
        "camera_index": (0, 99),
        "precision_dampening_factor": (0.2, 0.8),
        "high_speed_boost_factor": (1.0, 2.5),
        "mini_hud_opacity": (0.2, 1.0),
    }

    def validate(self):
        defaults = type(self)()
        for field in fields(self):
            name = field.name
            value, default = getattr(self, name), getattr(defaults, name)
            if isinstance(default, bool):
                if not isinstance(value, bool):
                    setattr(self, name, default)
            elif name in self.RANGES:
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or (isinstance(value, float) and not math.isfinite(value))
                    or (name == "camera_index" and not isinstance(value, int))
                ):
                    value = default
                low, high = self.RANGES[name]
                setattr(self, name, max(low, min(high, value)))
            elif name == "cad_drag_button" and value not in ("right", "middle"):
                self.cad_drag_button = default
        return self

    @classmethod
    def get_config_path(cls) -> Path:
        return Path.home() / ".handtracker" / "config.json"

    def save(self):
        """Raise on failure so the UI never reports a failed write as saved."""
        self.validate()
        path = self.get_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        data.pop("is_tracking_enabled")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=".config-",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = stream.name
                json.dump(data, stream, indent=2, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    @classmethod
    def load(cls) -> "AppConfig":
        config = cls()
        try:
            data = json.loads(cls.get_config_path().read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Settings must be a JSON object")
            allowed = {field.name for field in fields(cls)} - {"is_tracking_enabled"}
            for name in allowed & data.keys():
                setattr(config, name, data[name])
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError) as error:
            print(f"[Config] Using defaults for unreadable settings: {error}")
        return config.validate()
