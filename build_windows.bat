@echo off
REM PyInstaller build script for Windows Standalone Executable
cd /d "%~dp0"

echo Building HandTracker for Windows...

call .venv\Scripts\activate.bat

pyinstaller ^
    --name="HandTracker" ^
    --windowed ^
    --onedir ^
    --clean ^
    --noconfirm ^
    --collect-data mediapipe ^
    --collect-data customtkinter ^
    --hidden-import PIL._tkinter_finder ^
    --hidden-import screeninfo ^
    main.py

echo Build complete! Windows executable created in dist\HandTracker\
pause
