#!/bin/bash
# PyInstaller build script for macOS Application (.app bundle)
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "Building standalone macOS Application..."

.venv/bin/pyinstaller \
    --name="HandTracker" \
    --windowed \
    --onedir \
    --clean \
    --noconfirm \
    --collect-data mediapipe \
    --collect-data customtkinter \
    --hidden-import PIL._tkinter_finder \
    --hidden-import Quartz \
    --hidden-import screeninfo \
    main.py

echo "Build complete! Application bundle created at: dist/HandTracker.app"
