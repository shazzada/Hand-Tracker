import math
import os
import queue
import sys
import threading
import time
import tkinter as tk
from typing import Callable, List, Optional, Tuple

import cv2
import customtkinter as ctk
from PIL import Image, ImageTk
from src.config import AppConfig
from src.gestures import GestureEngine, GestureEvent, GestureType
from src.mouse_controller import MouseController, SoundEffects
from src.tracker import HandLandmarksData, HandTracker

# Set CustomTkinter theme
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

IS_MACOS = sys.platform == "darwin"
IS_WINDOWS = sys.platform.startswith("win")


def open_camera_capture(index: int) -> Optional[cv2.VideoCapture]:
    """Tries opening camera with platform-preferred backends."""
    backends = []
    if IS_MACOS:
        backends = [cv2.CAP_AVFOUNDATION, cv2.CAP_ANY]
    elif IS_WINDOWS:
        backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY]
    else:
        backends = [cv2.CAP_V4L2, cv2.CAP_ANY]

    for backend in backends:
        try:
            cap = cv2.VideoCapture(index, backend)
            if cap is not None and cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                cap.set(cv2.CAP_PROP_FPS, 60)
                ret, frame = cap.read()
                if ret and frame is not None:
                    return cap
                cap.release()
        except Exception:
            pass

    return None


class HandTrackerApp(ctk.CTk):
    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config

        # Window properties
        self.title("HandTracker Pro V2.0 - AI Gesture Mouse & 3D CAD Controller by Dr Clark G. Michael")
        self.geometry("1180x850")
        self.minsize(1000, 720)

        # Thread-safe communication queue from worker thread to main Tkinter thread
        self.frame_queue: queue.Queue = queue.Queue(maxsize=2)
        
        # State & control flags
        self.is_running = True
        self.camera_thread: Optional[threading.Thread] = None
        self.reconnect_requested = False

        # Build UI layout on main thread
        self._create_layout()

        # Bind Global Keyboard Hotkeys
        self._setup_hotkeys()

        # Start background tracking worker
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.start_tracking()

        # Start main-thread polling loop (100% thread-safe)
        self.after(50, self._poll_queue)

    def _setup_hotkeys(self):
        """Sets up keyboard shortcuts."""
        # Cmd+Shift+H / Ctrl+Shift+H: Pause/Resume Toggle
        self.bind("<Command-Shift-H>", lambda e: self._toggle_hotkey())
        self.bind("<Command-Shift-h>", lambda e: self._toggle_hotkey())
        self.bind("<Control-Shift-H>", lambda e: self._toggle_hotkey())
        self.bind("<Control-Shift-h>", lambda e: self._toggle_hotkey())
        
        # Cmd+Shift+M / Ctrl+Shift+M: Clinical Mini Floating PiP Toggle
        self.bind("<Command-Shift-M>", lambda e: self._toggle_mini_hud())
        self.bind("<Command-Shift-m>", lambda e: self._toggle_mini_hud())
        self.bind("<Control-Shift-M>", lambda e: self._toggle_mini_hud())
        self.bind("<Control-Shift-m>", lambda e: self._toggle_mini_hud())

        # Cmd+[ / Cmd+]: Translucency / Opacity adjust shortcuts
        self.bind("<Command-bracketleft>", lambda e: self._adjust_opacity(-0.10))
        self.bind("<Control-bracketleft>", lambda e: self._adjust_opacity(-0.10))
        self.bind("<Command-bracketright>", lambda e: self._adjust_opacity(+0.10))
        self.bind("<Control-bracketright>", lambda e: self._adjust_opacity(+0.10))

    def _toggle_hotkey(self):
        self.config.is_tracking_enabled = not self.config.is_tracking_enabled
        if self.config.audio_feedback_enabled:
            SoundEffects.toggle()
        self._update_status_badge(self.config.is_tracking_enabled)

    def _adjust_opacity(self, delta: float):
        """Adjusts PiP window opacity between 0.20 (see-through) and 1.0 (solid)."""
        new_alpha = max(0.20, min(1.0, self.config.mini_hud_opacity + delta))
        self.config.mini_hud_opacity = new_alpha
        pct = int(new_alpha * 100)
        self.opacity_label.configure(text=f"👁️ {pct}%")
        if hasattr(self, "pip_opacity_label"):
            self.pip_opacity_label.configure(text=f"PiP Opacity: {pct}%")
            self.pip_opacity_slider.set(new_alpha)
        if self.config.mini_hud_mode:
            try:
                self.attributes("-alpha", new_alpha)
            except Exception:
                pass

    def _toggle_mini_hud(self):
        """Toggles between Full Studio Control and Resizable Clinical Floating Mini-HUD (PiP)."""
        self.config.mini_hud_mode = not self.config.mini_hud_mode
        if self.config.mini_hud_mode:
            # Switch to resizable compact floating PiP mode
            self.resizable(True, True)
            self.minsize(180, 140)
            self.grid_columnconfigure(0, weight=1)
            self.grid_columnconfigure(1, weight=0)
            self.right_frame.grid_remove()
            self.subtitle_label.grid_remove()
            self.status_badge.grid_remove()
            self.title_label.configure(text="✨ PiP", font=ctk.CTkFont(size=12, weight="bold"))
            self.btn_mini_hud.configure(text="⤢ Expand", fg_color="#0284C7", hover_color="#0369A1", width=70)
            self.opacity_frame.grid(row=0, column=2, padx=4, sticky="e")
            self.btn_mini_hud.grid(row=0, column=3, padx=(2, 6), pady=6, sticky="e")
            self.video_toolbar.grid_remove()
            self.header_frame.configure(height=36)
            self.left_frame.grid_configure(padx=3, pady=3)
            self.video_container.grid_configure(padx=3, pady=3)
            self.geometry("320x240")
            self.attributes("-topmost", True)
            try:
                self.attributes("-alpha", self.config.mini_hud_opacity)
            except Exception:
                pass
        else:
            # Switch to Full Studio Mode
            self.resizable(True, True)
            self.minsize(800, 550)
            self.grid_columnconfigure(0, weight=3)
            self.grid_columnconfigure(1, weight=2)
            self.opacity_frame.grid_remove()
            self.geometry("960x640")
            self.attributes("-topmost", False)
            try:
                self.attributes("-alpha", 1.0)
            except Exception:
                pass
            self.title_label.configure(text="✨ HandTracker Pro V2.0", font=ctk.CTkFont(size=20, weight="bold"))
            self.subtitle_label.grid(row=0, column=1, padx=5, pady=14, sticky="w")
            self.btn_mini_hud.configure(text="🏥 Mini PiP", fg_color="#1E293B", hover_color="#334155", width=85)
            self.btn_mini_hud.grid(row=0, column=2, padx=(5, 10), pady=14, sticky="e")
            self.status_badge.grid(row=0, column=3, padx=(0, 20), pady=14, sticky="e")
            self.video_toolbar.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
            self.header_frame.configure(height=64)
            self.left_frame.grid_configure(padx=(16, 8), pady=16)
            self.video_container.grid_configure(padx=12, pady=12)
            self.right_frame.grid(row=1, column=1, sticky="nsew", padx=(8, 16), pady=16)

    def _create_layout(self):
        self.grid_columnconfigure(0, weight=3)  # Camera feed
        self.grid_columnconfigure(1, weight=2)  # Control panel
        self.grid_rowconfigure(0, weight=0)     # Header
        self.grid_rowconfigure(1, weight=1)     # Main content

        # ----------------- HEADER -----------------
        self.header_frame = ctk.CTkFrame(self, fg_color="#13131e", corner_radius=0, height=64)
        self.header_frame.grid(row=0, column=0, columnspan=2, sticky="ew", padx=0, pady=0)
        self.header_frame.grid_columnconfigure(1, weight=1)

        self.title_label = ctk.CTkLabel(
            self.header_frame,
            text="✨ HandTracker Pro V2.0",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#00E5FF",
        )
        self.title_label.grid(row=0, column=0, padx=(20, 10), pady=14, sticky="w")

        self.subtitle_label = ctk.CTkLabel(
            self.header_frame,
            text="AI Gesture Mouse & 3D CAD Controller | by Dr Clark G. Michael [Cmd+Shift+H]",
            font=ctk.CTkFont(size=12),
            text_color="#8892B0",
        )
        self.subtitle_label.grid(row=0, column=1, padx=5, pady=14, sticky="w")

        # Mini PiP Translucency Control Frame (visible in PiP mode)
        self.opacity_frame = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        
        self.btn_opacity_down = ctk.CTkButton(
            self.opacity_frame,
            text="−",
            width=22,
            height=22,
            command=lambda: self._adjust_opacity(-0.10),
            fg_color="#1E293B",
            hover_color="#334155",
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.btn_opacity_down.pack(side="left", padx=1)

        pct = int(self.config.mini_hud_opacity * 100)
        self.opacity_label = ctk.CTkLabel(
            self.opacity_frame,
            text=f"👁️ {pct}%",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#00E5FF",
        )
        self.opacity_label.pack(side="left", padx=3)

        self.btn_opacity_up = ctk.CTkButton(
            self.opacity_frame,
            text="+",
            width=22,
            height=22,
            command=lambda: self._adjust_opacity(+0.10),
            fg_color="#1E293B",
            hover_color="#334155",
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.btn_opacity_up.pack(side="left", padx=1)

        self.btn_mini_hud = ctk.CTkButton(
            self.header_frame,
            text="🏥 Mini PiP",
            command=self._toggle_mini_hud,
            width=85,
            height=28,
            fg_color="#1E293B",
            hover_color="#334155",
            font=ctk.CTkFont(size=11, weight="bold"),
        )
        self.btn_mini_hud.grid(row=0, column=2, padx=(5, 10), pady=14, sticky="e")

        self.status_badge = ctk.CTkLabel(
            self.header_frame,
            text="● ACTIVE",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#00E676",
            fg_color="#103322",
            corner_radius=12,
            padx=14,
            pady=4,
        )
        self.status_badge.grid(row=0, column=3, padx=(0, 20), pady=14, sticky="e")

        # ----------------- LEFT: CAMERA FEED & HUD -----------------
        self.left_frame = ctk.CTkFrame(self, fg_color="#0e0e17", corner_radius=12)
        self.left_frame.grid(row=1, column=0, sticky="nsew", padx=(16, 8), pady=16)
        self.left_frame.grid_rowconfigure(0, weight=1)
        self.left_frame.grid_columnconfigure(0, weight=1)

        # Video Canvas Container
        self.video_container = ctk.CTkFrame(self.left_frame, fg_color="#08080f", corner_radius=10)
        self.video_container.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        self.video_container.grid_rowconfigure(0, weight=1)
        self.video_container.grid_columnconfigure(0, weight=1)

        self.video_label = ctk.CTkLabel(
            self.video_container,
            text="Connecting to Camera...\nPlease ensure Camera permission is granted.",
            font=ctk.CTkFont(size=14),
            text_color="#94A3B8",
        )
        self.video_label.grid(row=0, column=0, sticky="nsew")
        self.video_label.bind("<Double-Button-1>", lambda e: self._toggle_mini_hud())

        # Video Toolbar
        self.video_toolbar = ctk.CTkFrame(self.left_frame, fg_color="transparent")
        self.video_toolbar.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        self.video_toolbar.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.mirror_btn = ctk.CTkSwitch(
            self.video_toolbar,
            text="Mirror Video",
            command=self._on_toggle_mirror,
            font=ctk.CTkFont(size=12),
        )
        if self.config.mirror_camera:
            self.mirror_btn.select()
        self.mirror_btn.grid(row=0, column=0, padx=4)

        self.landmarks_btn = ctk.CTkSwitch(
            self.video_toolbar,
            text="Show Skeleton",
            command=self._on_toggle_landmarks,
            font=ctk.CTkFont(size=12),
        )
        if self.config.show_landmarks:
            self.landmarks_btn.select()
        self.landmarks_btn.grid(row=0, column=1, padx=4)

        self.box_btn = ctk.CTkSwitch(
            self.video_toolbar,
            text="Active Area",
            command=self._on_toggle_active_box,
            font=ctk.CTkFont(size=12),
        )
        if self.config.show_active_box:
            self.box_btn.select()
        self.box_btn.grid(row=0, column=2, padx=4)

        self.fps_label = ctk.CTkLabel(
            self.video_toolbar,
            text="FPS: --",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#00E5FF",
        )
        self.fps_label.grid(row=0, column=3, padx=4)

        # ----------------- RIGHT: SETTINGS & TUNING PANEL -----------------
        self.right_frame = ctk.CTkScrollableFrame(self, fg_color="#141422", corner_radius=12)
        self.right_frame.grid(row=1, column=1, sticky="nsew", padx=(8, 16), pady=16)

        # 1. Master Toggle, Audio, Eco-Sleep & CAD Mode Selectors
        self.top_control_frame = ctk.CTkFrame(self.right_frame, fg_color="#1c1c2e", corner_radius=10)
        self.top_control_frame.pack(fill="x", padx=8, pady=6)

        self.master_switch = ctk.CTkSwitch(
            self.top_control_frame,
            text="Mouse Control Active",
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._on_toggle_master,
            progress_color="#00E676",
        )
        if self.config.is_tracking_enabled:
            self.master_switch.select()
        self.master_switch.pack(padx=14, pady=(12, 6), anchor="w")

        # Toggles row (Audio + Eco Sleep)
        toggles_row = ctk.CTkFrame(self.top_control_frame, fg_color="transparent")
        toggles_row.pack(fill="x", padx=14, pady=4)
        
        self.audio_switch = ctk.CTkSwitch(
            toggles_row,
            text="🔊 Acoustic Click Audio",
            font=ctk.CTkFont(size=11),
            command=self._on_toggle_audio,
        )
        if self.config.audio_feedback_enabled:
            self.audio_switch.select()
        self.audio_switch.pack(side="left")

        self.eco_switch = ctk.CTkSwitch(
            toggles_row,
            text="🔋 Eco Sleep",
            font=ctk.CTkFont(size=11),
            command=self._on_toggle_eco,
        )
        if self.config.eco_battery_saver_enabled:
            self.eco_switch.select()
        self.eco_switch.pack(side="right")

        # Adaptive Dual-Speed Cursor Acceleration Row
        accel_row = ctk.CTkFrame(self.top_control_frame, fg_color="transparent")
        accel_row.pack(fill="x", padx=14, pady=(4, 4))
        self.accel_switch = ctk.CTkSwitch(
            accel_row,
            text="⚡ Adaptive Dual-Speed Acceleration",
            font=ctk.CTkFont(size=11),
            command=self._on_toggle_accel,
            progress_color="#00E5FF",
        )
        if self.config.adaptive_acceleration_enabled:
            self.accel_switch.select()
        self.accel_switch.pack(anchor="w")

        # CAD Drag Mode Row
        cad_row = ctk.CTkFrame(self.top_control_frame, fg_color="transparent")
        cad_row.pack(fill="x", padx=14, pady=(6, 4))
        ctk.CTkLabel(cad_row, text="CAD 3D Drag Mode:", font=ctk.CTkFont(size=11), text_color="#CBD5E1").pack(side="left")
        self.cad_drag_menu = ctk.CTkOptionMenu(
            cad_row,
            values=["Right Drag (3D CAD Orbit / Pan)", "Middle Drag (Fusion/SolidWorks/Blender)"],
            command=self._on_cad_mode_select,
            width=190,
            height=26,
            font=ctk.CTkFont(size=11),
        )
        if self.config.cad_drag_button == "right":
            self.cad_drag_menu.set("Right Drag (3D CAD Orbit / Pan)")
        else:
            self.cad_drag_menu.set("Middle Drag (Fusion/SolidWorks/Blender)")
        self.cad_drag_menu.pack(side="right")

        # Camera selection dropdown row
        cam_row = ctk.CTkFrame(self.top_control_frame, fg_color="transparent")
        cam_row.pack(fill="x", padx=14, pady=(4, 12))
        ctk.CTkLabel(cam_row, text="Camera Device:", font=ctk.CTkFont(size=11), text_color="#CBD5E1").pack(side="left")
        self.cam_menu = ctk.CTkOptionMenu(
            cam_row,
            values=["Camera 0 (Default)", "Camera 1", "Camera 2"],
            command=self._on_camera_select,
            width=180,
            height=26,
            font=ctk.CTkFont(size=11),
        )
        self.cam_menu.set(f"Camera {self.config.camera_index}" + (" (Default)" if self.config.camera_index == 0 else ""))
        self.cam_menu.pack(side="right")

        # 2. Speed Presets Bar
        preset_frame = ctk.CTkFrame(self.right_frame, fg_color="#1c1c2e", corner_radius=10)
        preset_frame.pack(fill="x", padx=8, pady=6)

        ctk.CTkLabel(
            preset_frame,
            text="🚀 Speed & Physics Presets",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#94A3B8",
        ).pack(anchor="w", padx=12, pady=(8, 4))

        preset_btns = ctk.CTkFrame(preset_frame, fg_color="transparent")
        preset_btns.pack(fill="x", padx=10, pady=(0, 10))
        preset_btns.grid_columnconfigure((0, 1, 2), weight=1)

        self.btn_preset_fast = ctk.CTkButton(
            preset_btns,
            text="⚡ Fast",
            command=lambda: self._apply_preset(2.5, 0.35, 0.22),
            fg_color="#0284C7",
            hover_color="#0369A1",
            height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
        )
        self.btn_preset_fast.grid(row=0, column=0, padx=2, sticky="ew")

        self.btn_preset_bal = ctk.CTkButton(
            preset_btns,
            text="⚖️ Balanced",
            command=lambda: self._apply_preset(2.0, 0.50, 0.18),
            fg_color="#334155",
            hover_color="#475569",
            height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
        )
        self.btn_preset_bal.grid(row=0, column=1, padx=2, sticky="ew")

        self.btn_preset_smooth = ctk.CTkButton(
            preset_btns,
            text="🧈 Smooth",
            command=lambda: self._apply_preset(1.5, 0.70, 0.15),
            fg_color="#334155",
            hover_color="#475569",
            height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
        )
        self.btn_preset_smooth.grid(row=0, column=2, padx=2, sticky="ew")

        # 3. 3D CAD & Gesture Reference Card
        self.guide_frame = ctk.CTkFrame(self.right_frame, fg_color="#1c1c2e", corner_radius=10)
        self.guide_frame.pack(fill="x", padx=8, pady=6)

        guide_title = ctk.CTkLabel(
            self.guide_frame,
            text="📐 3D CAD & V2.0 Gesture Guide",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#94A3B8",
        )
        guide_title.pack(anchor="w", padx=12, pady=(10, 4))

        gestures_info = [
            ("🖐️ Open Palm", "Smooth Mouse Movement"),
            ("☝️ Index Rotating", "↻ Clockwise = Zoom In, ↺ Anticlockwise = Zoom Out"),
            ("🤏 Index + Thumb", "Left Click / Select Drag"),
            ("🤏 Middle + Thumb", "3D CAD Pan / Rotate (Right-Drag)"),
            ("🤏 Pinky + Thumb", "Double-Click (Open Cases / Reset View)"),
            ("✊ Closed Fist", "Toggle Pause / Resume Tracking"),
        ]
        for g_icon, g_desc in gestures_info:
            row = ctk.CTkFrame(self.guide_frame, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=2)
            ctk.CTkLabel(row, text=g_icon, font=ctk.CTkFont(size=12, weight="bold"), text_color="#E2E8F0").pack(side="left")
            ctk.CTkLabel(row, text=f": {g_desc}", font=ctk.CTkFont(size=11), text_color="#94A3B8").pack(side="left")

        ctk.CTkLabel(self.guide_frame, text="", height=4).pack()

        # 4. Real-Time Pinch Proximity Meters
        self.meters_frame = ctk.CTkFrame(self.right_frame, fg_color="#1c1c2e", corner_radius=10)
        self.meters_frame.pack(fill="x", padx=8, pady=6)

        ctk.CTkLabel(
            self.meters_frame,
            text="📊 Real-Time Pinch Proximity",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#94A3B8",
        ).pack(anchor="w", padx=12, pady=(10, 4))

        # Index Pinch Bar
        idx_row = ctk.CTkFrame(self.meters_frame, fg_color="transparent")
        idx_row.pack(fill="x", padx=12, pady=(4, 2))
        ctk.CTkLabel(idx_row, text="Index (Left Click / Drag)", font=ctk.CTkFont(size=11), text_color="#CBD5E1").pack(side="left")
        self.idx_pinch_progress = ctk.CTkProgressBar(self.meters_frame, orientation="horizontal", height=7, progress_color="#00E5FF")
        self.idx_pinch_progress.pack(fill="x", padx=12, pady=(0, 4))
        self.idx_pinch_progress.set(0.0)

        # Middle Pinch Bar
        mid_row = ctk.CTkFrame(self.meters_frame, fg_color="transparent")
        mid_row.pack(fill="x", padx=12, pady=(4, 2))
        ctk.CTkLabel(mid_row, text="Middle (3D CAD Pan / Rotate Drag)", font=ctk.CTkFont(size=11), text_color="#CBD5E1").pack(side="left")
        self.mid_pinch_progress = ctk.CTkProgressBar(self.meters_frame, orientation="horizontal", height=7, progress_color="#FF9100")
        self.mid_pinch_progress.pack(fill="x", padx=12, pady=(0, 4))
        self.mid_pinch_progress.set(0.0)

        # Pinky Pinch Bar
        pinky_row = ctk.CTkFrame(self.meters_frame, fg_color="transparent")
        pinky_row.pack(fill="x", padx=12, pady=(4, 2))
        ctk.CTkLabel(pinky_row, text="Pinky (Double-Click)", font=ctk.CTkFont(size=11), text_color="#CBD5E1").pack(side="left")
        self.pinky_pinch_progress = ctk.CTkProgressBar(self.meters_frame, orientation="horizontal", height=7, progress_color="#00E676")
        self.pinky_pinch_progress.pack(fill="x", padx=12, pady=(0, 10))
        self.pinky_pinch_progress.set(0.0)

        # 5. Sensitivity & Tuning Sliders
        self.sliders_frame = ctk.CTkFrame(self.right_frame, fg_color="#1c1c2e", corner_radius=10)
        self.sliders_frame.pack(fill="x", padx=8, pady=6)

        # Speed Sensitivity (0.5x to 3.5x)
        self.sens_label = ctk.CTkLabel(
            self.sliders_frame,
            text=f"Speed Sensitivity: {self.config.sensitivity:.1f}x",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#E2E8F0",
        )
        self.sens_label.pack(anchor="w", padx=12, pady=(10, 2))
        self.sens_slider = ctk.CTkSlider(
            self.sliders_frame,
            from_=0.5,
            to=3.5,
            number_of_steps=30,
            command=self._on_sens_change,
        )
        self.sens_slider.set(self.config.sensitivity)
        self.sens_slider.pack(fill="x", padx=12, pady=(0, 10))

        # Sniper Mode Scale Slider
        self.sniper_label = ctk.CTkLabel(
            self.sliders_frame,
            text=f"Sniper Precision Speed: {int(self.config.sniper_mode_scale * 100)}%",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#00E5FF",
        )
        self.sniper_label.pack(anchor="w", padx=12, pady=(6, 2))
        self.sniper_slider = ctk.CTkSlider(
            self.sliders_frame,
            from_=0.15,
            to=0.60,
            number_of_steps=18,
            command=self._on_sniper_change,
        )
        self.sniper_slider.set(self.config.sniper_mode_scale)
        self.sniper_slider.pack(fill="x", padx=12, pady=(0, 10))

        # Smoothing Factor
        self.smooth_label = ctk.CTkLabel(
            self.sliders_frame,
            text=f"Cursor Smoothing: {self.config.smoothing_factor:.2f}",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#E2E8F0",
        )
        self.smooth_label.pack(anchor="w", padx=12, pady=(6, 2))
        self.smooth_slider = ctk.CTkSlider(
            self.sliders_frame,
            from_=0.1,
            to=0.9,
            number_of_steps=16,
            command=self._on_smooth_change,
        )
        self.smooth_slider.set(self.config.smoothing_factor)
        self.smooth_slider.pack(fill="x", padx=12, pady=(0, 10))

        # Active Screen Margin (Reach Boundary)
        self.margin_label = ctk.CTkLabel(
            self.sliders_frame,
            text=f"Reach Boundary Margin: {int(self.config.active_margin_x * 100)}%",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#E2E8F0",
        )
        self.margin_label.pack(anchor="w", padx=12, pady=(6, 2))
        self.margin_slider = ctk.CTkSlider(
            self.sliders_frame,
            from_=0.05,
            to=0.35,
            number_of_steps=30,
            command=self._on_margin_change,
        )
        self.margin_slider.set(self.config.active_margin_x)
        self.margin_slider.pack(fill="x", padx=12, pady=(0, 10))

        # Adaptive Precision Dampening Slider (Micro-movements)
        self.damp_label = ctk.CTkLabel(
            self.sliders_frame,
            text=f"Margin Precision Dampening: {int(self.config.precision_dampening_factor * 100)}%",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#00E5FF",
        )
        self.damp_label.pack(anchor="w", padx=12, pady=(6, 2))
        self.damp_slider = ctk.CTkSlider(
            self.sliders_frame,
            from_=0.20,
            to=0.80,
            number_of_steps=15,
            command=self._on_damp_change,
        )
        self.damp_slider.set(self.config.precision_dampening_factor)
        self.damp_slider.pack(fill="x", padx=12, pady=(0, 10))

        # Multi-Monitor High Speed Boost Slider (Fast Sweeps)
        self.boost_label = ctk.CTkLabel(
            self.sliders_frame,
            text=f"Multi-Monitor Boost Factor: {self.config.high_speed_boost_factor:.2f}x",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#E2E8F0",
        )
        self.boost_label.pack(anchor="w", padx=12, pady=(6, 2))
        self.boost_slider = ctk.CTkSlider(
            self.sliders_frame,
            from_=1.0,
            to=2.5,
            number_of_steps=15,
            command=self._on_boost_change,
        )
        self.boost_slider.set(self.config.high_speed_boost_factor)
        self.boost_slider.pack(fill="x", padx=12, pady=(0, 10))

        # CAD Zoom & Scroll Speed
        self.scroll_label = ctk.CTkLabel(
            self.sliders_frame,
            text=f"CAD Zoom / Scroll Speed: {self.config.scroll_speed:.1f}x",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#E2E8F0",
        )
        self.scroll_label.pack(anchor="w", padx=12, pady=(6, 2))
        self.scroll_slider = ctk.CTkSlider(
            self.sliders_frame,
            from_=0.5,
            to=3.0,
            number_of_steps=25,
            command=self._on_scroll_change,
        )
        self.scroll_slider.set(self.config.scroll_speed)
        self.scroll_slider.pack(fill="x", padx=12, pady=(0, 10))

        # Pinch Threshold
        self.pinch_label = ctk.CTkLabel(
            self.sliders_frame,
            text=f"Pinch Trigger Threshold: {self.config.pinch_threshold_left:.3f}",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#E2E8F0",
        )
        self.pinch_label.pack(anchor="w", padx=12, pady=(6, 2))
        self.pinch_slider = ctk.CTkSlider(
            self.sliders_frame,
            from_=0.03,
            to=0.09,
            number_of_steps=20,
            command=self._on_pinch_change,
        )
        self.pinch_slider.set(self.config.pinch_threshold_left)
        self.pinch_slider.pack(fill="x", padx=12, pady=(0, 10))

        # Clinical PiP Opacity Slider
        self.pip_opacity_label = ctk.CTkLabel(
            self.sliders_frame,
            text=f"PiP Window Opacity: {int(self.config.mini_hud_opacity * 100)}%",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#00E5FF",
        )
        self.pip_opacity_label.pack(anchor="w", padx=12, pady=(6, 2))
        self.pip_opacity_slider = ctk.CTkSlider(
            self.sliders_frame,
            from_=0.20,
            to=1.00,
            number_of_steps=16,
            command=self._on_pip_opacity_change,
        )
        self.pip_opacity_slider.set(self.config.mini_hud_opacity)
        self.pip_opacity_slider.pack(fill="x", padx=12, pady=(0, 14))

        # 6. Action Buttons (Save / Reset / Reconnect)
        self.btn_row = ctk.CTkFrame(self.right_frame, fg_color="transparent")
        self.btn_row.pack(fill="x", padx=8, pady=8)
        self.btn_row.grid_columnconfigure((0, 1, 2), weight=1)

        self.save_btn = ctk.CTkButton(
            self.btn_row,
            text="💾 Save",
            command=self._on_save_config,
            fg_color="#0284C7",
            hover_color="#0369A1",
            height=32,
        )
        self.save_btn.grid(row=0, column=0, padx=2, sticky="ew")

        self.reset_btn = ctk.CTkButton(
            self.btn_row,
            text="↺ Defaults",
            command=self._on_reset_defaults,
            fg_color="#334155",
            hover_color="#475569",
            height=32,
        )
        self.reset_btn.grid(row=0, column=1, padx=2, sticky="ew")

        self.reconnect_btn = ctk.CTkButton(
            self.btn_row,
            text="🔄 Reconnect",
            command=self._on_reconnect_camera,
            fg_color="#1e293b",
            hover_color="#334155",
            height=32,
        )
        self.reconnect_btn.grid(row=0, column=2, padx=2, sticky="ew")

    # ----------------- CALLBACKS & TUNING -----------------
    def _apply_preset(self, sens: float, smooth: float, margin: float):
        self.config.sensitivity = sens
        self.config.smoothing_factor = smooth
        self.config.active_margin_x = margin
        self.config.active_margin_y = margin

        self.sens_slider.set(sens)
        self.smooth_slider.set(smooth)
        self.margin_slider.set(margin)

        self.sens_label.configure(text=f"Speed Sensitivity: {sens:.1f}x")
        self.smooth_label.configure(text=f"Cursor Smoothing: {smooth:.2f}")
        self.margin_label.configure(text=f"Reach Boundary Margin: {int(margin * 100)}%")

    def _on_toggle_master(self):
        enabled = bool(self.master_switch.get())
        self.config.is_tracking_enabled = enabled
        if self.config.audio_feedback_enabled:
            SoundEffects.toggle()
        self._update_status_badge(enabled)

    def _on_toggle_audio(self):
        self.config.audio_feedback_enabled = bool(self.audio_switch.get())

    def _on_toggle_eco(self):
        self.config.eco_battery_saver_enabled = bool(self.eco_switch.get())

    def _update_status_badge(self, enabled: bool):
        if enabled:
            self.status_badge.configure(text="● ACTIVE", text_color="#00E676", fg_color="#103322")
            if not self.master_switch.get():
                self.master_switch.select()
        else:
            self.status_badge.configure(text="🔒 PAUSED (Fist to Resume)", text_color="#FFD600", fg_color="#332B10")
            if self.master_switch.get():
                self.master_switch.deselect()

    def _on_cad_mode_select(self, choice: str):
        if "Right" in choice:
            self.config.cad_drag_button = "right"
        else:
            self.config.cad_drag_button = "middle"

    def _on_camera_select(self, choice: str):
        try:
            idx = int(choice.split()[1])
            self.config.camera_index = idx
            self._on_reconnect_camera()
        except Exception:
            pass

    def _on_reconnect_camera(self):
        self.reconnect_requested = True

    def _on_toggle_mirror(self):
        self.config.mirror_camera = bool(self.mirror_btn.get())

    def _on_toggle_landmarks(self):
        self.config.show_landmarks = bool(self.landmarks_btn.get())

    def _on_toggle_active_box(self):
        self.config.show_active_box = bool(self.box_btn.get())

    def _on_toggle_accel(self):
        self.config.adaptive_acceleration_enabled = bool(self.accel_switch.get())

    def _on_damp_change(self, val: float):
        self.config.precision_dampening_factor = float(val)
        self.damp_label.configure(text=f"Margin Precision Dampening: {int(val * 100)}%")

    def _on_boost_change(self, val: float):
        self.config.high_speed_boost_factor = float(val)
        self.boost_label.configure(text=f"Multi-Monitor Boost Factor: {val:.2f}x")

    def _on_sens_change(self, val: float):
        self.config.sensitivity = float(val)
        self.sens_label.configure(text=f"Speed Sensitivity: {val:.1f}x")

    def _on_sniper_change(self, val: float):
        self.config.sniper_mode_scale = float(val)
        self.sniper_label.configure(text=f"Sniper Precision Speed: {int(val * 100)}%")

    def _on_smooth_change(self, val: float):
        self.config.smoothing_factor = float(val)
        self.smooth_label.configure(text=f"Cursor Smoothing: {val:.2f}")

    def _on_margin_change(self, val: float):
        self.config.active_margin_x = float(val)
        self.config.active_margin_y = float(val)
        self.margin_label.configure(text=f"Reach Boundary Margin: {int(val * 100)}%")

    def _on_scroll_change(self, val: float):
        self.config.scroll_speed = float(val)
        self.scroll_label.configure(text=f"CAD Zoom / Scroll Speed: {val:.1f}x")

    def _on_pinch_change(self, val: float):
        self.config.pinch_threshold_left = float(val)
        self.config.pinch_threshold_middle = float(val)
        self.config.pinch_threshold_ring = float(val)
        self.config.pinch_threshold_pinky = float(val)
        self.pinch_label.configure(text=f"Pinch Trigger Threshold: {val:.3f}")

    def _on_pip_opacity_change(self, val: float):
        alpha = float(val)
        self.config.mini_hud_opacity = alpha
        pct = int(alpha * 100)
        self.pip_opacity_label.configure(text=f"PiP Window Opacity: {pct}%")
        self.opacity_label.configure(text=f"👁️ {pct}%")
        if self.config.mini_hud_mode:
            try:
                self.attributes("-alpha", alpha)
            except Exception:
                pass

    def _on_save_config(self):
        self.config.save()
        self.save_btn.configure(text="✓ Saved!", fg_color="#10B981")
        self.after(1500, lambda: self.save_btn.configure(text="💾 Save", fg_color="#0284C7"))

    def _on_reset_defaults(self):
        default = AppConfig()
        self.config.sensitivity = default.sensitivity
        self.config.smoothing_factor = default.smoothing_factor
        self.config.active_margin_x = default.active_margin_x
        self.config.active_margin_y = default.active_margin_y
        self.config.pinch_threshold_left = default.pinch_threshold_left
        self.config.pinch_threshold_middle = default.pinch_threshold_middle
        self.config.pinch_threshold_ring = default.pinch_threshold_ring
        self.config.pinch_threshold_pinky = default.pinch_threshold_pinky
        self.config.scroll_speed = default.scroll_speed
        self.config.cad_drag_button = default.cad_drag_button
        self.config.sniper_mode_scale = default.sniper_mode_scale
        self.config.audio_feedback_enabled = default.audio_feedback_enabled
        self.config.eco_battery_saver_enabled = default.eco_battery_saver_enabled
        
        self.sens_slider.set(default.sensitivity)
        self.smooth_slider.set(default.smoothing_factor)
        self.margin_slider.set(default.active_margin_x)
        self.scroll_slider.set(default.scroll_speed)
        self.pinch_slider.set(default.pinch_threshold_left)
        self.sniper_slider.set(default.sniper_mode_scale)
        
        self.sens_label.configure(text=f"Speed Sensitivity: {default.sensitivity:.1f}x")
        self.smooth_label.configure(text=f"Cursor Smoothing: {default.smoothing_factor:.2f}")
        self.margin_label.configure(text=f"Reach Boundary Margin: {int(default.active_margin_x * 100)}%")
        self.scroll_label.configure(text=f"CAD Zoom / Scroll Speed: {default.scroll_speed:.1f}x")
        self.pinch_label.configure(text=f"Pinch Trigger Threshold: {default.pinch_threshold_left:.3f}")
        self.sniper_label.configure(text=f"Sniper Precision Speed: {int(default.sniper_mode_scale * 100)}%")

    # ----------------- BACKGROUND TRACKING THREAD -----------------
    def start_tracking(self):
        self.camera_thread = threading.Thread(target=self._tracking_worker, daemon=True)
        self.camera_thread.start()

    def _tracking_worker(self):
        """Worker thread handling camera capture, MediaPipe inference, and mouse events."""
        tracker = HandTracker()
        gesture_engine = GestureEngine(self.config)
        mouse_controller = MouseController(self.config)

        cap: Optional[cv2.VideoCapture] = None
        last_reconnect_time = 0.0
        last_frame_time = time.time()
        last_hand_seen_time = time.time()
        fps = 0.0

        while self.is_running:
            if self.reconnect_requested:
                self.reconnect_requested = False
                if cap and cap.isOpened():
                    cap.release()
                cap = None

            # Ensure camera connection
            if cap is None or not cap.isOpened():
                now = time.time()
                if (now - last_reconnect_time) > 1.2:
                    last_reconnect_time = now
                    cap = open_camera_capture(self.config.camera_index)
                    if cap is None and self.config.camera_index != 0:
                        cap = open_camera_capture(0)

                if cap is None or not cap.isOpened():
                    time.sleep(0.1)
                    continue

            # Read frame
            success, frame = cap.read()
            if not success or frame is None:
                if cap:
                    cap.release()
                cap = None
                time.sleep(0.05)
                continue

            # FPS calculation
            now = time.time()
            dt = now - last_frame_time
            last_frame_time = now
            if dt > 0:
                fps = 0.9 * fps + 0.1 * (1.0 / dt)

            # Process frame with MediaPipe
            hand_data, frame = tracker.process_frame(
                frame, mirror=self.config.mirror_camera
            )

            # Eco Battery-Saver: sleep longer if hand has been away for > 4 seconds
            if hand_data is not None:
                last_hand_seen_time = now
            elif self.config.eco_battery_saver_enabled and (now - last_hand_seen_time) > 4.0:
                time.sleep(0.075)  # Drop to ~10 FPS to save CPU and battery

            # Gesture classification & Fist toggle
            event: GestureEvent = gesture_engine.update(hand_data)

            # Audio sound on fist toggle
            if event.is_fist_toggle and self.config.audio_feedback_enabled:
                SoundEffects.toggle()

            # Execute Mouse Actions
            if self.config.is_tracking_enabled and hand_data is not None:
                # 1. Cursor Movement with dynamic sensitivity (e.g. Sniper mode)
                if event.allow_cursor_move and event.cursor_point_norm:
                    mouse_controller.move_to(
                        event.cursor_point_norm[0],
                        event.cursor_point_norm[1],
                        sensitivity_multiplier=event.sensitivity_multiplier,
                    )

                # 2. Left Drag Events (Index Hold)
                if event.is_left_down:
                    mouse_controller.left_down()
                elif event.is_left_up:
                    mouse_controller.left_up()

                # 3. Medit Right-Mouse Drag Events (Middle Hold -> Rotate / Pan)
                if event.is_right_down:
                    mouse_controller.right_down()
                elif event.is_right_up:
                    mouse_controller.right_up()

                # 4. Middle Mouse Drag Events (if middle mode selected)
                if event.is_middle_down:
                    mouse_controller.middle_down()
                elif event.is_middle_up:
                    mouse_controller.middle_up()

                # 5. Medit Continuous Zoom / Scroll Wheel (Ring Hold)
                if abs(event.scroll_delta) > 0.0:
                    mouse_controller.scroll(event.scroll_delta)

                # 6. Discrete Clicks & Double-Click
                if event.is_left_click_trigger:
                    mouse_controller.left_click()
                elif event.is_double_click_trigger:
                    mouse_controller.double_click()
                elif event.is_right_click_trigger:
                    mouse_controller.right_click()

            # Render HUD overlay
            hud_frame = tracker.draw_hud(
                frame_bgr=frame,
                hand_data=hand_data,
                gesture_name=event.gesture.value,
                active_margin_x=self.config.active_margin_x,
                active_margin_y=self.config.active_margin_y,
                show_landmarks=self.config.show_landmarks,
                show_active_box=self.config.show_active_box,
                is_tracking_enabled=self.config.is_tracking_enabled,
                fist_progress=event.fist_progress,
                trajectory_points=event.trajectory_points,
            )

            # Convert to RGB image
            rgb_frame = cv2.cvtColor(hud_frame, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb_frame)

            # Push to queue
            payload = (
                pil_img,
                fps,
                event.raw_index_pinch,
                event.raw_middle_pinch,
                event.raw_ring_pinch,
                event.raw_pinky_pinch,
                self.config.is_tracking_enabled,
            )
            try:
                if self.frame_queue.full():
                    try:
                        self.frame_queue.get_nowait()
                    except queue.Empty:
                        pass
                self.frame_queue.put_nowait(payload)
            except Exception:
                pass

            time.sleep(0.004)

        # Cleanup
        if cap and cap.isOpened():
            cap.release()
        tracker.release()

    # ----------------- MAIN THREAD UI POLLING -----------------
    def _poll_queue(self):
        """Polls the queue on the main thread for thread-safe UI updates."""
        if not self.is_running:
            return

        payload = None
        while not self.frame_queue.empty():
            try:
                payload = self.frame_queue.get_nowait()
            except queue.Empty:
                break

        if payload is not None:
            pil_img, fps, idx_p, mid_p, ring_p, pinky_p, is_tracking_enabled = payload
            try:
                # Update status badge / switch if toggled by fist
                self._update_status_badge(is_tracking_enabled)

                container_w = self.video_container.winfo_width()
                container_h = self.video_container.winfo_height()
                if container_w < 50 or container_h < 50:
                    container_w = 320 if self.config.mini_hud_mode else 640
                    container_h = 240 if self.config.mini_hud_mode else 480

                img_w, img_h = pil_img.size
                scale = max(0.1, min((container_w - 4) / img_w, (container_h - 4) / img_h))
                new_w = max(120, int(img_w * scale))
                new_h = max(90, int(img_h * scale))

                resized_img = pil_img.resize((new_w, new_h), Image.Resampling.BILINEAR)
                ctk_img = ctk.CTkImage(light_image=resized_img, dark_image=resized_img, size=(new_w, new_h))

                self.video_label.configure(image=ctk_img, text="")
                self.video_label.image = ctk_img

                # Update FPS
                self.fps_label.configure(text=f"FPS: {int(fps)}")

                # Update pinch progress meters (4 meters)
                idx_val = max(0.0, min(1.0, 1.0 - (idx_p / (self.config.pinch_threshold_left * 2.2))))
                mid_val = max(0.0, min(1.0, 1.0 - (mid_p / (self.config.pinch_threshold_middle * 2.2))))
                ring_val = max(0.0, min(1.0, 1.0 - (ring_p / (self.config.pinch_threshold_ring * 2.2))))
                pinky_val = max(0.0, min(1.0, 1.0 - (pinky_p / (self.config.pinch_threshold_pinky * 2.2))))
                
                self.idx_pinch_progress.set(idx_val)
                self.mid_pinch_progress.set(mid_val)
                self.ring_pinch_progress.set(ring_val)
                self.pinky_pinch_progress.set(pinky_val)

            except Exception:
                pass

        if self.is_running:
            self.after(16, self._poll_queue)

    def on_close(self):
        """Clean teardown on exit."""
        self.is_running = False
        self.destroy()
