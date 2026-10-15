@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Run run.bat first to install the environment.
    exit /b 1
)
echo Building HandTracker for Windows...
.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm HandTracker.spec
if errorlevel 1 (
    echo Build failed. See the error above.
    pause
    exit /b 1
)
echo Build complete: dist\HandTracker\HandTracker.exe
pause
