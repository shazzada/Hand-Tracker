# Build with: .venv/bin/python -m PyInstaller --clean --noconfirm HandTracker.spec
import sys
from PyInstaller.utils.hooks import collect_data_files

backend = "darwin" if sys.platform == "darwin" else "win32" if sys.platform == "win32" else "xorg"
datas = collect_data_files("mediapipe") + collect_data_files("customtkinter")
hiddenimports = ["PIL._tkinter_finder", f"pynput.keyboard._{backend}", f"pynput.mouse._{backend}"]
if sys.platform == "darwin":
    hiddenimports += ["Quartz", "Quartz.CoreGraphics"]
a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HandTracker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
collection = COLLECT(exe, a.binaries, a.datas, strip=False, upx=True, name="HandTracker")
if sys.platform == "darwin":
    app = BUNDLE(
        collection,
        name="HandTracker.app",
        bundle_identifier="com.handtracker.pro",
        info_plist={
            "CFBundleShortVersionString": "2.1.0",
            "CFBundleVersion": "2.1.0",
            "NSCameraUsageDescription": "HandTracker uses your camera to recognize hand gestures on this device.",
            "NSHighResolutionCapable": True,
        },
    )
