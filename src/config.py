import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class AppConfig:
    # Cursor speed & physics
    sensitivity: float = 2.0         # Speed multiplier (0.5x to 4.0x)
    acceleration: float = 1.35       # Velocity curve power (>1.0 accelerates fast sweeps)
    smoothing_factor: float = 0.50   # 0.1 (instant) to 0.9 (heavy smoothing)
    
    # Active mapping bounding box (percentage margin from camera edge)
    active_margin_x: float = 0.18    # Comfortable reach for full horizontal span
    active_margin_y: float = 0.18    # Comfortable reach for full vertical span
    
    # Pinch trigger thresholds (normalized by hand scale)
    pinch_threshold_left: float = 0.055    # Index (8) + Thumb (4) -> Left Click / Select Drag
    pinch_threshold_middle: float = 0.055  # Middle (12) + Thumb (4) -> Medit CAD 3D Pan/Rotate Drag
    pinch_threshold_ring: float = 0.055    # Ring (16) + Thumb (4) -> Medit CAD Zoom In/Out Scroll
    pinch_threshold_pinky: float = 0.055   # Pinky (20) + Thumb (4) -> Double-Click
    pinch_hysteresis: float = 0.020        # Extra margin required to release pinch (prevents jitter)
    
    # CAD Drag button setting ("right" for Medit / Dental CAD, "middle" for Fusion/SolidWorks/Blender)
    cad_drag_button: str = "right"
    
    # Sniper Precision Mode
    sniper_mode_scale: float = 0.30        # Speed multiplier in sniper mode (0.15x to 0.60x)
    
    # Audio Feedback (Acoustic Haptic Click Sounds)
    audio_feedback_enabled: bool = True
    
    # Eco Battery-Saver
    eco_battery_saver_enabled: bool = True
    
    # Scroll & CAD Zoom parameters
    scroll_speed: float = 1.2             # Velocity multiplier for continuous zoom/scroll
    
    # Click stabilization
    click_freeze_sec: float = 0.14        # Dampens cursor motion when pinching so click lands accurately
    click_debounce_sec: float = 0.28      # Debounce to prevent unintentional double clicks
    drag_hold_sec: float = 0.28           # Hold pinch longer than this to enter Drag mode
    
    # Fist pause/resume hold time
    fist_toggle_hold_sec: float = 0.30    # Hold closed fist to toggle Pause / Resume
    
    # Camera & visual display
    camera_index: int = 0
    mirror_camera: bool = True
    show_landmarks: bool = True
    show_active_box: bool = True
    
    # Adaptive Dual-Speed Cursor Acceleration (Sub-millimeter margin trimming & fast sweeps)
    adaptive_acceleration_enabled: bool = True
    precision_dampening_factor: float = 0.40  # Speed multiplier for micro-movements
    high_speed_boost_factor: float = 1.75     # Speed multiplier for fast sweeps
    
    # Clinical Floating Mini-HUD (PiP Widget)
    mini_hud_mode: bool = False               # Compact floating picture-in-picture mode
    mini_hud_opacity: float = 0.88            # Translucent glassmorphism opacity
    
    # Master control
    is_tracking_enabled: bool = True

    @classmethod
    def get_config_path(cls) -> Path:
        """Returns path to user configuration file."""
        config_dir = Path.home() / ".handtracker"
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / "config.json"

    def save(self):
        """Save settings to disk."""
        try:
            path = self.get_config_path()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, indent=2)
        except Exception as e:
            print(f"[Config] Error saving config: {e}")

    @classmethod
    def load(cls) -> "AppConfig":
        """Load settings from disk or return defaults."""
        config = cls()
        try:
            path = cls.get_config_path()
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for k, v in data.items():
                        if hasattr(config, k):
                            setattr(config, k, v)
        except Exception as e:
            print(f"[Config] Error loading config: {e}")
        return config
