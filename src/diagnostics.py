"""Exercise packaged imports, UI resources and model data without opening a camera."""

import json
import sys


def run_self_check():
    root = tracker = None
    try:
        import customtkinter as ctk
        import cv2
        import mediapipe as mp
        import numpy as np
        from PIL import Image
        from pynput.keyboard import GlobalHotKeys

        from src.mouse_controller import MouseController
        from src.tracker import HandTracker

        root = ctk.CTk()
        root.withdraw()
        preview = ctk.CTkImage(light_image=Image.new("RGB", (32, 24)), size=(32, 24))
        label = ctk.CTkLabel(root, text="HandTracker diagnostic", image=preview)
        label.pack()
        root.update_idletasks()
        tracker = HandTracker()
        hand, frame = tracker.process_frame(np.zeros((480, 640, 3), dtype=np.uint8))
        if hand is not None or frame.shape != (480, 640, 3):
            raise RuntimeError("Unexpected blank-frame inference result")
        # Verify that the OS backend imported, without posting input or starting a listener.
        if not callable(GlobalHotKeys) or not callable(MouseController):
            raise RuntimeError("Input backend unavailable")
        print(
            json.dumps(
                {
                    "status": "ok",
                    "platform": sys.platform,
                    "mediapipe": mp.__version__,
                    "opencv": cv2.__version__,
                    "numpy": np.__version__,
                    "customtkinter": ctk.__version__,
                    "checks": [
                        "Tk resources",
                        "image preview",
                        "input backend import",
                        "model inference",
                    ],
                }
            )
        )
        return 0
    except Exception as error:
        print(f"HandTracker self-check failed: {error}", file=sys.stderr)
        return 1
    finally:
        if tracker is not None:
            tracker.release()
        if root is not None:
            root.destroy()
