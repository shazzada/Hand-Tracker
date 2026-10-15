"""Native control panel; Tk stays on the main thread and input has one owner."""

import dataclasses
import logging
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk

import customtkinter as ctk
import cv2
from PIL import Image

from src.config import AppConfig
from src.gestures import GestureEngine
from src.mouse_controller import MouseController, SoundEffects
from src.tracker import HandTracker

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")
IS_MACOS = sys.platform == "darwin"
IS_WINDOWS = sys.platform.startswith("win")
BG, PANEL, CARD = "#0C1220", "#141E30", "#1D2A40"
TEXT, MUTED, ACCENT = "#EDF3FC", "#AABBD2", "#38BDF8"
LOG = logging.getLogger(__name__)


def open_camera_capture(index: int) -> cv2.VideoCapture | None:
    backends = (
        [cv2.CAP_AVFOUNDATION, cv2.CAP_ANY]
        if IS_MACOS
        else [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY]
        if IS_WINDOWS
        else [cv2.CAP_V4L2, cv2.CAP_ANY]
    )
    for backend in backends:
        cap = None
        try:
            cap = cv2.VideoCapture(index, backend)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                cap.set(cv2.CAP_PROP_FPS, 30)
                success, frame = cap.read()
                if success and frame is not None and frame.size:
                    return cap
        except Exception:
            LOG.debug("Camera backend %s failed", backend, exc_info=True)
        if cap is not None:
            cap.release()
    return None


class HandTrackerApp(ctk.CTk):
    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config.validate()
        self.config.is_tracking_enabled = False
        self.title("HandTracker Pro · Gesture Mouse & CAD")
        self.configure(fg_color=BG)
        self.geometry("1120x760")
        self.minsize(860, 600)
        self._studio_geometry = "1120x760"
        self.frame_queue = queue.Queue(maxsize=1)
        self.status_queue = queue.SimpleQueue()
        self.command_queue = queue.SimpleQueue()
        self.stop_event = threading.Event()
        self.reconnect_event = threading.Event()
        self._control_lock = threading.RLock()
        self._generation = 0
        self.is_running = True
        self._closing = False
        self._camera_ready = False
        self._camera_state = "connecting"
        self._camera_message = "Connecting to camera…"
        self._last_frame_at = None
        self._hotkey_listener = None
        self._hotkeys_global = False
        self.camera_thread = None
        self.mouse_controller = None
        self.gesture_engine = None
        self.sliders = {}
        self.switches = {}
        self._last_image = None
        self._render_key = None
        self._create_layout()
        self._setup_hotkeys()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._update_status_badge()
        if self.config.mini_hud_mode:
            self.config.mini_hud_mode = False
            self._toggle_mini_hud()
        self.start_tracking()
        self.after(30, self._poll_queue)

    def _label(self, parent, text, size=12, color=MUTED, **kwargs):
        return ctk.CTkLabel(
            parent, text=text, text_color=color, font=ctk.CTkFont(size=size), **kwargs
        )

    def _card(self, parent, title, description=None):
        card = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=12)
        card.pack(fill="x", pady=(0, 12), padx=2)
        self._label(card, title, 14, TEXT, anchor="w").pack(fill="x", padx=16, pady=(14, 4))
        if description:
            self._label(card, description, wraplength=310, justify="left", anchor="w").pack(
                fill="x", padx=16, pady=(0, 8)
            )
        return card

    def _switch(self, parent, name, text, callback=None):
        switch = ctk.CTkSwitch(
            parent,
            text=text,
            font=ctk.CTkFont(size=12),
            command=callback or (lambda: self._set_switch(name)),
            progress_color="#0284C7",
            height=28,
        )
        switch.pack(anchor="w", padx=16, pady=(4, 9))
        if getattr(self.config, name):
            switch.select()
        self.switches[name] = switch
        return switch

    def _set_switch(self, name):
        with self._control_lock:
            setattr(self.config, name, bool(self.switches[name].get()))
            if name == "mirror_camera":
                self._reset_input_locked()

    def _slider(self, parent, name, title, formatter, steps=30):
        label = self._label(parent, "", color=TEXT, anchor="w")
        label.pack(fill="x", padx=16, pady=(9, 2))
        low, high = AppConfig.RANGES[name]
        slider = ctk.CTkSlider(
            parent,
            from_=low,
            to=high,
            number_of_steps=steps,
            height=22,
            command=lambda value: self._set_slider(name, value),
        )
        slider.pack(fill="x", padx=16, pady=(0, 12))
        self.sliders[name] = (slider, label, title, formatter)
        self._refresh_slider(name)

    def _refresh_slider(self, name):
        slider, label, title, formatter = self.sliders[name]
        value = getattr(self.config, name)
        slider.set(value)
        label.configure(text=f"{title}  ·  {formatter(value)}")

    def _set_slider(self, name, value):
        with self._control_lock:
            setattr(self.config, name, float(value))
            if name == "active_margin_x":
                self.config.active_margin_y = float(value)
            if name == "pinch_threshold_left":
                self.config.pinch_threshold_middle = self.config.pinch_threshold_pinky = float(
                    value
                )
            if name == "mini_hud_opacity" and self.config.mini_hud_mode:
                self.attributes("-alpha", value)
        self._refresh_slider(name)

    def _create_layout(self):
        self.grid_columnconfigure(0, weight=3, minsize=300)
        self.grid_columnconfigure(1, weight=0, minsize=380)
        self.grid_rowconfigure(2, weight=1)
        self.header = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=0)
        self.header.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.header.grid_columnconfigure(0, weight=1)
        self.title_label = self._label(self.header, "HandTracker Pro", 22, TEXT)
        self.title_label.grid(row=0, column=0, padx=20, pady=16, sticky="w")
        self.status_badge = self._label(self.header, "Paused", 12, "#FBBF24")
        self.status_badge.grid(row=0, column=1, padx=12)
        self.pause_btn = ctk.CTkButton(
            self.header,
            text="Resume control",
            command=self._toggle_hotkey,
            width=132,
            height=34,
            fg_color="#0284C7",
            hover_color="#0369A1",
        )
        self.pause_btn.grid(row=0, column=2, padx=6)
        self.pip_btn = ctk.CTkButton(
            self.header,
            text="Mini PiP",
            command=self._toggle_mini_hud,
            width=88,
            height=34,
            fg_color="#33445F",
            hover_color="#425674",
        )
        self.pip_btn.grid(row=0, column=3, padx=(6, 20))

        self.connection_bar = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.connection_bar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=20, pady=(12, 0))
        self.connection_bar.grid_columnconfigure(0, weight=1)
        self.connection_label = self._label(self.connection_bar, self._camera_message, anchor="w")
        self.connection_label.grid(row=0, column=0, sticky="ew")
        self.reconnect_btn = ctk.CTkButton(
            self.connection_bar,
            text="Reconnect camera",
            width=140,
            height=28,
            fg_color="#33445F",
            hover_color="#425674",
            command=self._on_reconnect_camera,
        )
        self.reconnect_btn.grid(row=0, column=1, padx=(12, 0))

        self.left_frame = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=14)
        self.left_frame.grid(row=2, column=0, sticky="nsew", padx=(20, 8), pady=16)
        self.left_frame.grid_rowconfigure(0, weight=1)
        self.left_frame.grid_columnconfigure(0, weight=1)
        self.video_container = ctk.CTkFrame(self.left_frame, fg_color="#070C15", corner_radius=10)
        self.video_container.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        # Placement prevents the preview's requested size from forcing the window to grow.
        self.video_label = self._label(self.video_container, "")
        self.video_message = self._label(
            self.video_container,
            "Connecting to camera…\nYour preview will appear here.",
            14,
            justify="center",
            wraplength=280,
        )
        self.video_message.place(relx=0.5, rely=0.5, anchor="center")
        self.video_container.bind(
            "<Configure>",
            lambda event: self.video_message.configure(wraplength=max(100, event.width - 20)),
        )
        self.video_message.bind("<Double-Button-1>", lambda event: self._toggle_mini_hud())
        self.video_label.bind("<Double-Button-1>", lambda event: self._toggle_mini_hud())
        self.video_container.bind("<Double-Button-1>", lambda event: self._toggle_mini_hud())
        self.video_toolbar = ctk.CTkFrame(self.left_frame, fg_color="transparent")
        self.video_toolbar.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 8))
        self.video_toolbar.grid_columnconfigure(0, weight=1)
        self.hand_label = self._label(self.video_toolbar, "Waiting for camera", color=TEXT)
        self.hand_label.grid(row=0, column=0, sticky="w")
        self.fps_label = self._label(self.video_toolbar, "-- fps", color=ACCENT)
        self.fps_label.grid(row=0, column=1, sticky="e")
        self.preview_hint = self._label(
            self.left_frame,
            "Start paused. Resume when you are ready.\nDouble-click the preview for Mini PiP.",
            12,
            justify="left",
            anchor="w",
        )
        self.preview_hint.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 14))

        self.right_frame = ctk.CTkFrame(self, fg_color=PANEL, width=380, corner_radius=14)
        self.right_frame.grid(row=2, column=1, sticky="nsew", padx=(8, 20), pady=16)
        self.right_frame.grid_propagate(False)
        self.right_frame.grid_columnconfigure(0, weight=1)
        self.right_frame.grid_rowconfigure(1, weight=1)
        self._label(self.right_frame, "Set up your workspace", 17, TEXT, anchor="w").grid(
            row=0, column=0, sticky="ew", padx=18, pady=(16, 4)
        )
        self.tabs = ctk.CTkTabview(
            self.right_frame, fg_color=PANEL, segmented_button_selected_color="#0369A1"
        )
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=8, pady=0)
        pages = {}
        for name in ("Controls", "Tuning", "Guide"):
            tab = self.tabs.add(name)
            tab.grid_columnconfigure(0, weight=1)
            tab.grid_rowconfigure(0, weight=1)
            pages[name] = ctk.CTkScrollableFrame(tab, fg_color="transparent")
            pages[name].grid(row=0, column=0, sticky="nsew")

        controls = pages["Controls"]
        camera = self._card(
            controls, "Camera & preview", "Use even lighting and keep your full hand in view."
        )
        self.cam_menu = ctk.CTkOptionMenu(
            camera,
            values=[f"Camera {i}" for i in sorted({0, 1, 2, 3, 4, self.config.camera_index})],
            command=self._on_camera_select,
            height=32,
        )
        self.cam_menu.set(f"Camera {self.config.camera_index}")
        self.cam_menu.pack(fill="x", padx=16, pady=(0, 10))
        self._switch(camera, "mirror_camera", "Mirror preview & movement")
        self._switch(camera, "show_landmarks", "Show hand landmarks")
        self._switch(camera, "show_active_box", "Show cursor reach boundary")
        cad = self._card(
            controls,
            "CAD navigation",
            "Middle-finger pinch: tap for right click, hold to drag with this button.",
        )
        self.cad_drag_menu = ctk.CTkOptionMenu(
            cad,
            values=["Right button · Orbit / pan", "Middle button · Orbit / pan"],
            command=self._on_cad_mode_select,
            height=32,
        )
        self.cad_drag_menu.pack(fill="x", padx=16, pady=(0, 14))
        self._refresh_cad_menu()
        feedback = self._card(controls, "Feedback & power")
        self._switch(feedback, "audio_feedback_enabled", "Click & pause sounds")
        self._switch(feedback, "eco_battery_saver_enabled", "Save power when hand is away")

        tuning = pages["Tuning"]
        presets = self._card(
            tuning,
            "Movement presets",
            "Changes apply immediately. Save settings to keep them for next time.",
        )
        row = ctk.CTkFrame(presets, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(0, 14))
        for i, (name, values) in enumerate(
            (
                ("Fast", (2.5, 0.35, 0.22)),
                ("Balanced", (2.0, 0.5, 0.18)),
                ("Smooth", (1.5, 0.7, 0.15)),
            )
        ):
            row.grid_columnconfigure(i, weight=1)
            ctk.CTkButton(
                row, text=name, width=80, height=32, command=lambda v=values: self._apply_preset(*v)
            ).grid(row=0, column=i, padx=3, sticky="ew")
        movement = self._card(tuning, "Cursor movement")
        self._slider(movement, "sensitivity", "Sensitivity", lambda v: f"{v:.1f}×")
        self._slider(movement, "smoothing_factor", "Smoothing", lambda v: f"{v:.2f}", 16)
        self._slider(movement, "active_margin_x", "Reach margin", lambda v: f"{v:.0%}")
        self._switch(movement, "adaptive_acceleration_enabled", "Adaptive movement speed")
        self._slider(
            movement, "precision_dampening_factor", "Fine movement speed", lambda v: f"{v:.0%}"
        )
        self._slider(movement, "high_speed_boost_factor", "Fast sweep boost", lambda v: f"{v:.2f}×")
        gestures = self._card(tuning, "Gesture response")
        self._slider(gestures, "scroll_speed", "Dial zoom speed", lambda v: f"{v:.1f}×", 25)
        self._slider(gestures, "pinch_threshold_left", "Pinch threshold", lambda v: f"{v:.3f}", 60)
        self._slider(gestures, "drag_hold_sec", "Hold to drag", lambda v: f"{v:.2f} s", 85)
        pip = self._card(tuning, "Floating preview")
        self._slider(pip, "mini_hud_opacity", "PiP opacity", lambda v: f"{v:.0%}", 80)

        guide = pages["Guide"]
        quick = self._card(
            guide,
            "Get started",
            "1. Grant Camera and Accessibility access.\n2. Hold an open palm inside the boundary.\n3. Resume control with the button above.\n4. Hold a fist to pause at any time.",
        )
        if IS_MACOS:
            ctk.CTkButton(
                quick, text="Open Accessibility settings", height=32, command=self._open_permissions
            ).pack(fill="x", padx=16, pady=(0, 14))
        reference = self._card(guide, "Gesture reference")
        for title, detail in (
            ("Open palm", "Move the cursor using the index knuckle as the anchor."),
            ("Index + thumb", "Tap and release to click. Hold to drag; separate to release."),
            ("Middle + thumb", "Tap and release for right click. Hold for CAD orbit / pan."),
            ("Pinky + thumb", "Pinch and release for a double click."),
            (
                "Point & draw circles",
                "Clockwise zooms in. Anticlockwise zooms out. Open your hand to leave zoom.",
            ),
            ("Closed fist", "Hold to pause or resume. Open your hand before toggling again."),
        ):
            self._label(reference, title, 12, TEXT, anchor="w").pack(fill="x", padx=16, pady=(8, 0))
            self._label(reference, detail, wraplength=300, justify="left", anchor="w").pack(
                fill="x", padx=16, pady=(0, 8)
            )
        shortcuts = self._card(guide, "Keyboard shortcuts")
        modifier = "Cmd" if IS_MACOS else "Ctrl"
        self.hotkey_hint = self._label(
            shortcuts,
            f"{modifier}+Shift+H  ·  Pause / resume\n{modifier}+Shift+M  ·  Mini PiP\n{modifier}+[ / ]  ·  PiP opacity",
            justify="left",
            anchor="w",
        )
        self.hotkey_hint.pack(fill="x", padx=16, pady=(4, 8))
        self.hotkey_status = self._label(shortcuts, "", wraplength=300, justify="left", anchor="w")
        self.hotkey_status.pack(fill="x", padx=16, pady=(0, 14))
        meters = self._card(
            guide, "Live pinch proximity", "Bars fill as fingertips approach the thumb."
        )
        self.meters = []
        for label, color in (
            ("Index · Left click", ACCENT),
            ("Middle · CAD drag", "#FB923C"),
            ("Pinky · Double click", "#34D399"),
        ):
            self._label(meters, label, anchor="w").pack(fill="x", padx=16)
            bar = ctk.CTkProgressBar(meters, height=6, progress_color=color)
            bar.pack(fill="x", padx=16, pady=(4, 12))
            bar.set(0)
            self.meters.append(bar)

        footer = ctk.CTkFrame(self.right_frame, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=16, pady=(8, 6))
        footer.grid_columnconfigure(0, weight=1)
        footer.grid_columnconfigure(1, weight=1)
        self.save_btn = ctk.CTkButton(
            footer, text="Save settings", command=self._on_save_config, height=34
        )
        self.save_btn.grid(row=0, column=0, padx=(0, 4), sticky="ew")
        ctk.CTkButton(
            footer,
            text="Reset settings",
            command=self._on_reset_defaults,
            fg_color="#33445F",
            hover_color="#425674",
            height=34,
        ).grid(row=0, column=1, padx=(4, 0), sticky="ew")
        self.feedback_label = self._label(
            self.right_frame, "Changes apply immediately", wraplength=330
        )
        self.feedback_label.grid(row=3, column=0, padx=16, pady=(0, 12), sticky="ew")

    def _open_permissions(self):
        subprocess.Popen(
            [
                "open",
                "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
            ]
        )

    def _setup_hotkeys(self):
        modifier = "Command" if IS_MACOS else "Control"
        # Fallback bindings are suppressed while a global listener is active.
        bindings = {
            f"<{modifier}-Shift-H>": "toggle",
            f"<{modifier}-Shift-h>": "toggle",
            f"<{modifier}-Shift-M>": "pip",
            f"<{modifier}-Shift-m>": "pip",
            f"<{modifier}-bracketleft>": "opacity_down",
            f"<{modifier}-bracketright>": "opacity_up",
        }
        for sequence, action in bindings.items():
            self.bind(sequence, lambda event, a=action: self._local_shortcut(a))
        self.bind("<Escape>", lambda event: self._set_tracking(False))
        try:
            from pynput import keyboard

            key = "<cmd>" if IS_MACOS else "<ctrl>"
            listener = keyboard.GlobalHotKeys(
                {
                    f"{key}+<shift>+h": lambda: self.command_queue.put("toggle"),
                    f"{key}+<shift>+m": lambda: self.command_queue.put("pip"),
                    f"{key}+[": lambda: self.command_queue.put("opacity_down"),
                    f"{key}+]": lambda: self.command_queue.put("opacity_up"),
                }
            )
            if getattr(listener, "IS_TRUSTED", True):
                listener.start()
                self._hotkey_listener = listener
                self._hotkeys_global = True
        except Exception:
            LOG.info("Global shortcuts unavailable; using window shortcuts", exc_info=True)
        self._refresh_hotkey_status()

    def _refresh_hotkey_status(self):
        text = (
            "Global shortcuts enabled. Esc pauses while this window is focused."
            if self._hotkeys_global
            else "Shortcuts work while this window is focused. Enable Accessibility / Input Monitoring and restart for global shortcuts."
        )
        self.hotkey_status.configure(text=text)

    def _local_shortcut(self, action):
        if not self._hotkeys_global:
            self.command_queue.put(action)
        return "break"

    def _reset_input_locked(self):
        self._generation += 1
        if self.gesture_engine:
            self.gesture_engine.reset()
        if self.mouse_controller:
            self.mouse_controller.release_all()

    def _set_tracking(self, enabled):
        changed = False
        try:
            with self._control_lock:
                enabled = bool(enabled and self._camera_ready and not self._closing)
                changed = enabled != self.config.is_tracking_enabled
                self.config.is_tracking_enabled = enabled
                self._reset_input_locked()
                if enabled and self.mouse_controller:
                    self.mouse_controller.ensure_access()
                    self.mouse_controller.sync_position()
        except Exception as error:
            self.config.is_tracking_enabled = False
            self.feedback_label.configure(text=f"Input unavailable: {error}", text_color="#FCA5A5")
            LOG.exception("Could not change input state")
            # A failed resume must also attempt to release any partially posted input.
            try:
                with self._control_lock:
                    self._reset_input_locked()
            except Exception:
                LOG.exception("Mouse release retry failed")
        if changed and self.config.audio_feedback_enabled:
            SoundEffects.toggle()
        self._update_status_badge()

    def _toggle_hotkey(self):
        self._set_tracking(not self.config.is_tracking_enabled)

    def _update_status_badge(self):
        enabled = self.config.is_tracking_enabled
        key = (enabled, self.config.mini_hud_mode, self._camera_ready)
        if key == getattr(self, "_status_key", None):
            return
        self._status_key = key
        self.status_badge.configure(
            text="Control active" if enabled else "Control paused",
            text_color="#34D399" if enabled else "#FBBF24",
        )
        self.pause_btn.configure(
            text=("Pause" if enabled else "Resume")
            if self.config.mini_hud_mode
            else ("Pause control" if enabled else "Resume control"),
            fg_color="#9F3440" if enabled else "#0284C7",
            hover_color="#B5414E" if enabled else "#0369A1",
            state="normal" if self._camera_ready or enabled else "disabled",
        )

    def _adjust_opacity(self, delta):
        value = max(0.2, min(1.0, self.config.mini_hud_opacity + delta))
        self._set_slider("mini_hud_opacity", value)

    def _toggle_mini_hud(self):
        compact = not self.config.mini_hud_mode
        self.config.mini_hud_mode = compact
        if compact:
            self._studio_geometry = self.geometry()
            self.right_frame.grid_remove()
            self.connection_bar.grid_remove()
            self.status_badge.grid_remove()
            self.title_label.grid_remove()
            self.preview_hint.grid_remove()
            self.video_toolbar.grid_remove()
            self.grid_columnconfigure(0, minsize=0, weight=1)
            self.grid_columnconfigure(1, minsize=0, weight=0)
            self.header.grid_columnconfigure(0, weight=1)
            self.pause_btn.grid_configure(padx=4, pady=4)
            self.pause_btn.configure(width=70, height=28)
            self.pip_btn.grid_configure(padx=(4, 8), pady=4)
            self.pip_btn.configure(text="Expand", width=70, height=28)
            self.left_frame.grid_configure(padx=4, pady=4, columnspan=2)
            self.video_container.grid_configure(padx=3, pady=3)
            self.minsize(180, 140)
            self.geometry("320x260")
        else:
            self.grid_columnconfigure(0, minsize=300, weight=3)
            self.grid_columnconfigure(1, minsize=380, weight=0)
            self.minsize(860, 600)
            self.geometry(self._studio_geometry)
            self.title_label.grid()
            self.status_badge.grid()
            self.connection_bar.grid()
            self.right_frame.grid()
            self.preview_hint.grid()
            self.video_toolbar.grid()
            self.pause_btn.configure(width=132, height=34)
            self.pause_btn.grid_configure(padx=6, pady=0)
            self.pip_btn.configure(text="Mini PiP", width=88, height=34)
            self.pip_btn.grid_configure(padx=(6, 20), pady=0)
            self.left_frame.grid_configure(padx=(20, 8), pady=16, columnspan=1)
            self.video_container.grid_configure(padx=10, pady=10)
        self.attributes("-topmost", compact)
        try:
            self.attributes("-alpha", self.config.mini_hud_opacity if compact else 1.0)
        except tk.TclError:
            LOG.info("Window opacity unavailable")
        self._render_key = None
        self._update_status_badge()

    def _refresh_cad_menu(self):
        self.cad_drag_menu.set(
            "Right button · Orbit / pan"
            if self.config.cad_drag_button == "right"
            else "Middle button · Orbit / pan"
        )

    def _on_cad_mode_select(self, choice):
        with self._control_lock:
            if self.mouse_controller:
                self.mouse_controller.release_all()
            self.config.cad_drag_button = "right" if choice.startswith("Right") else "middle"

    def _on_camera_select(self, choice):
        with self._control_lock:
            self.config.camera_index = int(choice.split()[1])
        self._on_reconnect_camera()

    def _on_reconnect_camera(self):
        self._set_tracking(False)
        self._camera_ready = False
        self._show_camera_state("connecting", f"Connecting to camera {self.config.camera_index}…")
        self.reconnect_event.set()
        if not self.camera_thread or not self.camera_thread.is_alive():
            self.start_tracking()

    def _apply_preset(self, sensitivity, smoothing, margin):
        with self._control_lock:
            self.config.sensitivity, self.config.smoothing_factor = sensitivity, smoothing
            self.config.active_margin_x = self.config.active_margin_y = margin
        for name in ("sensitivity", "smoothing_factor", "active_margin_x"):
            self._refresh_slider(name)
        self.feedback_label.configure(text="Preset applied · Save to keep", text_color=MUTED)

    def _on_save_config(self):
        try:
            with self._control_lock:
                self.config.save()
            self.feedback_label.configure(text="Settings saved", text_color="#34D399")
        except OSError as error:
            self.feedback_label.configure(
                text=f"Could not save settings: {error}", text_color="#FCA5A5"
            )

    def _on_reset_defaults(self):
        self._set_tracking(False)
        defaults = AppConfig()
        with self._control_lock:
            for field in dataclasses.fields(defaults):
                if field.name not in ("camera_index", "mini_hud_mode", "is_tracking_enabled"):
                    setattr(self.config, field.name, getattr(defaults, field.name))
        for name in self.sliders:
            self._refresh_slider(name)
        for name, switch in self.switches.items():
            switch.select() if getattr(self.config, name) else switch.deselect()
        self._refresh_cad_menu()
        if self.config.mini_hud_mode:
            self.attributes("-alpha", defaults.mini_hud_opacity)
        self.feedback_label.configure(
            text="Defaults restored · Control paused · Save to keep", text_color=MUTED
        )

    def start_tracking(self):
        if self._closing or (self.camera_thread and self.camera_thread.is_alive()):
            return
        self.camera_thread = threading.Thread(
            target=self._tracking_worker, daemon=True, name="hand-tracking"
        )
        self.camera_thread.start()

    def _tracking_worker(self):
        tracker = cap = None
        last_frame_time = last_hand_time = time.monotonic()
        next_connect = 0.0
        fps = 0.0
        try:
            tracker = HandTracker()
            with self._control_lock:
                self.gesture_engine = GestureEngine(self.config)
                self.mouse_controller = MouseController(self.config)
            while not self.stop_event.is_set():
                if self.reconnect_event.is_set():
                    self.reconnect_event.clear()
                    with self._control_lock:
                        self._reset_input_locked()
                    if cap is not None:
                        cap.release()
                    cap = None
                    next_connect = 0.0
                if cap is None or not cap.isOpened():
                    with self._control_lock:
                        self.config.is_tracking_enabled = False
                        self._reset_input_locked()
                    if cap is not None:
                        cap.release()
                        cap = None
                    now = time.monotonic()
                    if now < next_connect:
                        self.stop_event.wait(0.1)
                        continue
                    index = self.config.camera_index
                    self.status_queue.put(("connecting", f"Connecting to camera {index}…"))
                    cap = open_camera_capture(index)
                    next_connect = time.monotonic() + 2.0
                    if cap is None:
                        self.status_queue.put(
                            (
                                "offline",
                                f"Camera {index} unavailable. Check Camera permission, close other camera apps, or choose another device.",
                            )
                        )
                        continue
                    if (
                        self.stop_event.is_set()
                        or self.reconnect_event.is_set()
                        or index != self.config.camera_index
                    ):
                        cap.release()
                        cap = None
                        continue
                    with self._control_lock:
                        self.config.is_tracking_enabled = False
                    # Explicit device selection must never silently use a different camera.
                    self.status_queue.put(
                        ("ready", f"Camera {index} connected · Processing on this device")
                    )
                    last_frame_time = time.monotonic()
                    fps = 0.0
                with self._control_lock:
                    generation = self._generation
                    mirror = self.config.mirror_camera
                success, frame = cap.read()
                if not success or frame is None or not frame.size:
                    with self._control_lock:
                        self.config.is_tracking_enabled = False
                        self._reset_input_locked()
                    self.status_queue.put(
                        ("offline", "Camera disconnected. Control paused; reconnecting…")
                    )
                    cap.release()
                    cap = None
                    continue
                hand, frame = tracker.process_frame(frame, mirror=mirror)
                now = time.monotonic()
                elapsed = now - last_frame_time
                last_frame_time = now
                if elapsed > 0:
                    fps = 1 / elapsed if fps == 0 else 0.9 * fps + 0.1 / elapsed
                with self._control_lock:
                    if self.stop_event.is_set() or generation != self._generation:
                        continue
                    event = self.gesture_engine.update(hand)
                    mouse = self.mouse_controller
                    for button in ("left", "right", "middle"):
                        if getattr(event, f"is_{button}_up"):
                            getattr(mouse, f"{button}_up")()
                    if event.is_fist_toggle:
                        mouse.release_all()
                        if self.config.is_tracking_enabled:
                            mouse.ensure_access()
                        mouse.sync_position()
                        if self.config.audio_feedback_enabled:
                            SoundEffects.toggle()
                    if self.config.is_tracking_enabled and hand is not None:
                        # Press at the stable click anchor before moving a drag.
                        for button in ("left", "right", "middle"):
                            if getattr(event, f"is_{button}_down"):
                                getattr(mouse, f"{button}_down")()
                        if event.allow_cursor_move and event.cursor_point_norm is not None:
                            mouse.move_to(
                                *event.cursor_point_norm,
                                sensitivity_multiplier=event.sensitivity_multiplier,
                            )
                        if event.scroll_delta:
                            mouse.scroll(event.scroll_delta)
                        for action in ("left_click", "right_click", "double_click"):
                            if getattr(event, f"is_{action}_trigger"):
                                getattr(mouse, action)()
                    else:
                        mouse.release_all()
                    snapshot = dataclasses.replace(self.config)
                    margins = mouse.get_effective_margins(event.sensitivity_multiplier)
                hud = tracker.draw_hud(
                    frame,
                    hand,
                    event.gesture.value,
                    snapshot.active_margin_x,
                    snapshot.active_margin_y,
                    show_landmarks=snapshot.show_landmarks,
                    show_active_box=snapshot.show_active_box,
                    is_tracking_enabled=snapshot.is_tracking_enabled,
                    fist_progress=event.fist_progress,
                    trajectory_points=event.trajectory_points,
                    effective_margin_x=margins[0],
                    effective_margin_y=margins[1],
                )
                image = Image.fromarray(cv2.cvtColor(hud, cv2.COLOR_BGR2RGB))
                payload = (image, fps, hand is not None, event)
                try:
                    self.frame_queue.get_nowait()
                except queue.Empty:
                    pass
                self.frame_queue.put_nowait(payload)
                if hand is not None:
                    last_hand_time = now
                delay = (
                    0.075
                    if snapshot.eco_battery_saver_enabled and now - last_hand_time > 4
                    else 0.004
                )
                self.stop_event.wait(delay)
        except Exception as error:
            LOG.exception("Tracking worker stopped")
            self.status_queue.put(
                ("error", f"Tracking stopped: {error}. Fix the issue and click Reconnect camera.")
            )
        finally:
            with self._control_lock:
                self.config.is_tracking_enabled = False
                try:
                    self._reset_input_locked()
                except Exception:
                    LOG.exception("Mouse release failed during cleanup")
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    LOG.exception("Camera release failed during cleanup")
            if tracker is not None:
                tracker.release()

    def _show_camera_state(self, state, message):
        self._camera_state, self._camera_message = state, message
        self._camera_ready = state == "ready"
        if self._camera_ready:
            self._last_frame_at = time.monotonic()
        self.connection_label.configure(
            text=message, text_color=MUTED if self._camera_ready else "#FBBF24"
        )
        self.connection_label.configure(
            wraplength=max(260, self.connection_bar.winfo_width() - 180)
        )
        if not self._camera_ready:
            self._last_image = None
            self._last_frame_at = None
            self.video_label.place_forget()
            self.video_message.configure(
                text=(
                    "Connecting to camera…"
                    if state == "connecting"
                    else "Camera unavailable\nCheck permissions or choose another device."
                    if state == "offline"
                    else "Tracking stopped\nExpand for details and reconnect."
                )
            )
            self.video_message.place(relx=0.5, rely=0.5, anchor="center")
            self._render_key = None
            self.hand_label.configure(
                text="Camera unavailable" if state == "offline" else "Waiting for camera"
            )
            self.fps_label.configure(text="-- fps")
            for meter in self.meters:
                meter.set(0)
        self._update_status_badge()

    def _render_preview(self):
        if self._last_image is None:
            return
        width, height = (
            max(1, self.video_container.winfo_width() - 6),
            max(1, self.video_container.winfo_height() - 6),
        )
        iw, ih = self._last_image.size
        scale = min(width / iw, height / ih)
        size = (max(1, int(iw * scale)), max(1, int(ih * scale)))
        key = (id(self._last_image), size)
        if key == self._render_key:
            return
        image = self._last_image.resize(size, Image.Resampling.BILINEAR)
        preview = ctk.CTkImage(light_image=image, dark_image=image, size=size)
        self.video_label.configure(image=preview)
        self.video_message.place_forget()
        self.video_label.place(relx=0.5, rely=0.5, anchor="center")
        self.video_label.image = preview
        self._render_key = key

    def _poll_queue(self):
        if self._closing:
            return
        try:
            self._poll_updates()
        finally:
            if not self._closing:
                self.after(30, self._poll_queue)

    def _poll_updates(self):
        if self._hotkey_listener and not self._hotkey_listener.is_alive():
            self._hotkeys_global = False
            self._hotkey_listener = None
            self._refresh_hotkey_status()
        try:
            while True:
                command = self.command_queue.get_nowait()
                if command == "toggle":
                    self._toggle_hotkey()
                elif command == "pip":
                    self._toggle_mini_hud()
                elif command in ("opacity_down", "opacity_up"):
                    self._adjust_opacity(-0.1 if command == "opacity_down" else 0.1)
        except queue.Empty:
            pass
        try:
            while True:
                self._show_camera_state(*self.status_queue.get_nowait())
        except queue.Empty:
            pass
        try:
            image, fps, hand_present, event = self.frame_queue.get_nowait()
            if self._camera_ready:
                self._last_image = image
                self._last_frame_at = time.monotonic()
                self.fps_label.configure(text=f"{fps:.0f} fps")
                self.hand_label.configure(
                    text=(
                        event.gesture.value.replace("_", " ").title()
                        if hand_present
                        else "No hand in view"
                    )
                )
                for meter, distance, threshold in zip(
                    self.meters,
                    (event.raw_index_pinch, event.raw_middle_pinch, event.raw_pinky_pinch),
                    (
                        self.config.pinch_threshold_left,
                        self.config.pinch_threshold_middle,
                        self.config.pinch_threshold_pinky,
                    ),
                    strict=True,
                ):
                    meter.set(max(0.0, min(1.0, 1 - distance / (threshold * 2.2))))
        except queue.Empty:
            pass
        # If capture or inference blocks, release input independently on the UI thread.
        if (
            self._camera_ready
            and self._last_frame_at is not None
            and time.monotonic() - self._last_frame_at > 2.5
        ):
            self._set_tracking(False)
            self._show_camera_state(
                "offline", "Camera preview stalled. Control paused; reconnecting…"
            )
            self.reconnect_event.set()
        self._update_status_badge()
        self._render_preview()

    def report_callback_exception(self, error_type, error, traceback):
        LOG.error("UI action failed", exc_info=(error_type, error, traceback))
        self.config.is_tracking_enabled = False
        with self._control_lock:
            try:
                self._reset_input_locked()
            except Exception:
                LOG.exception("Mouse release failed after UI error")
        if not self._closing:
            self.feedback_label.configure(text=f"Action failed: {error}", text_color="#FCA5A5")
            self._update_status_badge()

    def on_close(self):
        if self._closing:
            return
        self._closing = True
        self.is_running = False
        self.stop_event.set()
        with self._control_lock:
            self.config.is_tracking_enabled = False
            try:
                self._reset_input_locked()
            except Exception:
                LOG.exception("Mouse release failed while closing")
        if self._hotkey_listener:
            self._hotkey_listener.stop()
        self._close_deadline = time.monotonic() + 2.0
        self._finish_close()

    def _finish_close(self):
        if (
            self.camera_thread
            and self.camera_thread.is_alive()
            and time.monotonic() < self._close_deadline
        ):
            self.after(30, self._finish_close)
        else:
            self.destroy()
