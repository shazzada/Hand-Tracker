#!/bin/bash
set -euo pipefail
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"
if [ "$(uname -s)" != "Darwin" ]; then
    echo "Build the macOS app on macOS."
    exit 1
fi
if [ ! -x .venv/bin/python ]; then
    echo "Run ./run.sh first to install the environment."
    exit 1
fi
echo "Building HandTracker.app..."
.venv/bin/python -m PyInstaller --clean --noconfirm HandTracker.spec
echo "Build complete: dist/HandTracker.app (local ad hoc-signed build)"
