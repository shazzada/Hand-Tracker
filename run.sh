#!/bin/bash
# One-click launcher for macOS / Linux
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

# Check if .venv exists
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    if command -v uv &> /dev/null; then
        uv venv --python 3.11 .venv || uv venv .venv
        uv pip install -r requirements.txt
    else
        python3 -m venv .venv
        .venv/bin/pip install -r requirements.txt
    fi
fi

# Run application
echo "Starting HandTracker Pro..."
exec .venv/bin/python main.py "$@"
