@echo off
REM One-click launcher for Windows
cd /d "%~dp0"

IF NOT EXIST ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    pip install -r requirements.txt
) ELSE (
    call .venv\Scripts\activate.bat
)

echo Starting HandTracker Pro...
python main.py %*
pause
