@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    py -3.11 -m venv .venv
    if errorlevel 1 goto :failure
)
.venv\Scripts\python.exe -c "import sys; assert (3,10) <= sys.version_info[:2] <= (3,12), 'Use Python 3.10-3.12'"
if errorlevel 1 goto :failure
.venv\Scripts\python.exe -m ensurepip --upgrade
if errorlevel 1 goto :failure
.venv\Scripts\python.exe -c "import importlib.metadata as m; m.version('opencv-python')" >nul 2>&1
if not errorlevel 1 (
    .venv\Scripts\python.exe -m pip uninstall -y opencv-python opencv-contrib-python
    if errorlevel 1 goto :failure
)
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :failure
echo Starting HandTracker Pro...
.venv\Scripts\python.exe main.py %*
if errorlevel 1 goto :failure
exit /b 0
:failure
echo HandTracker could not start. See the error above.
pause
exit /b 1
