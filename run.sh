#!/bin/bash
# One-click launcher for macOS / Linux. Repair incomplete installations on rerun.
set -euo pipefail
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"
if [ ! -x .venv/bin/python ]; then
    echo "Creating Python 3.11 environment..."
    if command -v uv >/dev/null 2>&1; then
        uv venv --python 3.11 .venv
    else
        python3 -m venv .venv
    fi
fi
.venv/bin/python -c 'import sys; assert (3, 10) <= sys.version_info[:2] <= (3, 12), "Use Python 3.10–3.12 (3.11 recommended)"'
# Install when requirements changed, dependencies are missing, or the last install failed.
if [ ! -f .venv/.requirements-installed ] || ! cmp -s requirements.txt .venv/.requirements-installed || ! .venv/bin/python -c 'import cv2, mediapipe, pyautogui, pynput, customtkinter, PIL, numpy, screeninfo; assert hasattr(mediapipe, "solutions")' >/dev/null 2>&1; then
    echo "Installing compatible dependencies..."
    if command -v uv >/dev/null 2>&1; then
        if .venv/bin/python -c 'import importlib.metadata as m; m.version("opencv-python")' >/dev/null 2>&1; then
            uv pip uninstall --python .venv/bin/python opencv-python opencv-contrib-python
        fi
        uv pip install --python .venv/bin/python -r requirements.txt
    else
        .venv/bin/python -m ensurepip --upgrade
        if .venv/bin/python -c 'import importlib.metadata as m; m.version("opencv-python")' >/dev/null 2>&1; then
            .venv/bin/python -m pip uninstall -y opencv-python opencv-contrib-python
        fi
        .venv/bin/python -m pip install -r requirements.txt
    fi
    cp requirements.txt .venv/.requirements-installed
fi
echo "Starting HandTracker Pro..."
exec .venv/bin/python main.py "$@"
