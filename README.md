# ✨ HandTracker Pro V2.0
### AI Hand Gesture Mouse & 3D CAD Controller
**Author:** Dr Clark G. Michael

A high-performance, cross-platform AI gesture mouse controller and 3D CAD navigation system designed for precision computer control and clinical/dental CAD workflows. Built with Google MediaPipe, OpenCV, PyAutoGUI, and CustomTkinter.

---

## 🖐️ Gesture Reference & Control Scheme

| Gesture | Action | Description |
| :--- | :--- | :--- |
| **🖐️ Open Palm** | **Smooth Mouse Movement** | Sub-millimeter cursor tracking anchored to the index MCP knuckle with One-Euro deadzone filtering. |
| **☝️ Index Circular Air Dial** | **Continuous CAD Zoom (In / Out)** | Point index finger and draw in-air circles (↻ Clockwise = Zoom In, ↺ Anticlockwise = Zoom Out). Features 100% gesture lockout during zoom. |
| **🤏 Index + Thumb Pinch** | **Left Click & Drag** | Touch index tip to thumb tip for left click. Hold to drag and select. |
| **🤏 Middle + Thumb Pinch** | **3D CAD Orbit / Pan (Right-Drag)** | Touch middle tip to thumb tip to orbit/rotate 3D dental and CAD models. |
| **🤏 Pinky + Thumb Pinch** | **Double-Click** | Touch pinky tip to thumb tip to open cases, reset 3D viewports, or launch files. |
| **✊ Closed Fist** | **Toggle Pause / Resume** | Hold closed fist for 0.3s to toggle tracking on/off with visual radial charging progress. |

---

## 🏥 Clinical Floating PiP Mode (Picture-in-Picture)

Designed for distraction-free clinical and CAD work:
- **Always-on-Top Floating Widget**: Stays pinned in the corner of your screen over full-screen CAD applications.
- **Freely Resizable**: Drag any corner or edge to resize from ultra-compact ($180 \times 140$ px) up to large preview.
- **Glassmorphism Translucency**: Adjust opacity in real-time from 20% (see-through) to 100% (solid).

### ⌨️ Global Keyboard Shortcuts

| Shortcut | Action |
| :--- | :--- |
| **`Cmd+Shift+H`** / **`Ctrl+Shift+H`** | Toggle Tracking Pause / Resume |
| **`Cmd+Shift+M`** / **`Ctrl+Shift+M`** | Toggle Clinical Floating Mini PiP Mode |
| **`Cmd+[`** / **`Ctrl+[`** | Increase PiP Translucency (More see-through) |
| **`Cmd+]`** / **`Ctrl+]`** | Decrease PiP Translucency (More solid) |
| **Double-Click Video** | Toggle Mini PiP / Full Studio Mode |

---

## ⚡ Adaptive Dual-Speed Cursor Acceleration

- **Margin Line Precision**: Dampens micro-movements by $40\%$ speed for drawing fine dental margins and placing implants with zero hand jitter.
- **Multi-Monitor Fast Sweeps**: Accelerates sweeps dynamically up to $1.75\times$ for effortless navigation across dual 4K monitors without arm fatigue.

---

## 🚀 Getting Started

### Prerequisites
- Python 3.10, 3.11, or 3.12 (Python 3.11 recommended)
- Built-in webcam or USB camera

### Quick Start (macOS & Linux)
```bash
# Clone the repository
git clone https://github.com/shazzada/Hand-Tracker.git
cd Hand-Tracker

# Run automated launcher
./run.sh
```

### Quick Start (Windows)
Double-click `run.bat` or run in Command Prompt:
```cmd
run.bat
```

### Manual Installation
```bash
# 1. Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate    # On Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Launch HandTracker Pro
python main.py
```

---

## 🔒 macOS Permissions Guide

On macOS, controlling the cursor requires Accessibility permissions:
1. Open **System Settings** → **Privacy & Security** → **Accessibility**.
2. Enable your **Terminal** / **IDE** (or compiled application).
3. Allow **Camera** access when prompted.

---

## 🧪 Running Automated Unit Tests
```bash
source .venv/bin/activate
python -m unittest discover tests
```

---

## 📦 Building Standalone Executables

### macOS (.app bundle)
```bash
./build_macos.sh
# Output: dist/HandTracker.app
```

### Windows (.exe)
```cmd
build_windows.bat
# Output: dist\HandTracker\HandTracker.exe
```

---

## 📜 License
Created by **Dr Clark G. Michael**. Released under the MIT License.
