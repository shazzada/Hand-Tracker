"""Command-line entry point. Help and validation work without GUI imports."""

import argparse
import logging
import math
import sys
import warnings

from src.config import AppConfig


def bounded_number(name, integer=False):
    low, high = AppConfig.RANGES[name]

    def parse(value):
        try:
            number = int(value) if integer else float(value)
        except ValueError as error:
            raise argparse.ArgumentTypeError("Enter a valid number") from error
        if not low <= number <= high or not math.isfinite(number):
            raise argparse.ArgumentTypeError(f"Must be between {low} and {high}")
        return number

    return parse


def main():
    parser = argparse.ArgumentParser(
        description="HandTracker Pro · Webcam gesture mouse & CAD navigation"
    )
    parser.add_argument(
        "--camera", type=bounded_number("camera_index", True), help="Camera device index (0–99)"
    )
    parser.add_argument(
        "--sensitivity", type=bounded_number("sensitivity"), help="Cursor sensitivity (0.5–3.5)"
    )
    parser.add_argument(
        "--smoothing", type=bounded_number("smoothing_factor"), help="Cursor smoothing (0.1–0.9)"
    )
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="Check UI resources and model inference without camera or mouse output",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    warnings.filterwarnings("ignore", category=UserWarning, module="google.protobuf")
    if args.self_check:
        from src.diagnostics import run_self_check

        return run_self_check()
    config = AppConfig.load()
    for argument, field in (
        ("camera", "camera_index"),
        ("sensitivity", "sensitivity"),
        ("smoothing", "smoothing_factor"),
    ):
        if getattr(args, argument) is not None:
            setattr(config, field, getattr(args, argument))
    try:
        from src.gui import HandTrackerApp

        app = HandTrackerApp(config)
        app.mainloop()
    except (ImportError, OSError, RuntimeError) as error:
        print(
            f"HandTracker could not start: {error}\nRun the launcher to repair dependencies.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
