import argparse
import sys
import warnings

# Suppress harmless Protobuf symbol database deprecation warnings from MediaPipe
warnings.filterwarnings("ignore", category=UserWarning, module="google.protobuf")

from src.config import AppConfig
from src.gui import HandTrackerApp


def main():
    parser = argparse.ArgumentParser(
        description="HandTracker Pro - Hand gesture webcam mouse controller for macOS and Windows"
    )
    parser.add_argument(
        "--camera",
        type=int,
        default=None,
        help="Camera device index (default: from config, usually 0)",
    )
    parser.add_argument(
        "--sensitivity",
        type=float,
        default=None,
        help="Cursor speed sensitivity multiplier (e.g. 1.2)",
    )
    parser.add_argument(
        "--smoothing",
        type=float,
        default=None,
        help="Cursor smoothing factor between 0.1 and 0.95",
    )
    args = parser.parse_args()

    # Load persistent settings
    config = AppConfig.load()

    if args.camera is not None:
        config.camera_index = args.camera
    if args.sensitivity is not None:
        config.sensitivity = args.sensitivity
    if args.smoothing is not None:
        config.smoothing_factor = args.smoothing

    # Print startup banner
    print("=" * 60)
    print("  ✨ HandTracker Pro - AI Hand Gesture Mouse Controller")
    print("  Platform:", sys.platform)
    print("  Controls:")
    print("    🖐️  Open Palm (All fingers extended) -> Move Mouse")
    print("    🤏  Index Finger + Thumb Pinch       -> Left Click / Drag")
    print("    🤏  Middle Finger + Thumb Pinch      -> Right Click")
    print("=" * 60)

    # Launch GUI application
    app = HandTrackerApp(config)
    app.mainloop()


if __name__ == "__main__":
    main()
