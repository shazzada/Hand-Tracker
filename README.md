# HandTracker Pro

A native desktop gesture mouse and CAD navigation controller by **Dr Clark G. Michael**, built with MediaPipe, OpenCV, PyAutoGUI, and CustomTkinter. Camera frames are processed locally.

The app starts **paused**. Connect a camera, position an open hand inside the reach boundary, then choose **Resume control**. Hold a closed fist to pause or use the keyboard shortcut. Control stays paused after a camera disconnect or tracking error.

## Getting started

Use Python **3.10–3.12**, preferably **3.11**, and a webcam. The interface needs a display at least 860×600 logical pixels. On Linux, mouse control requires an X11 session; native Wayland control is not supported by this backend.

On macOS or Linux:

```bash
./run.sh
```

On Windows, run `run.bat`. A new Windows installation uses the Python launcher's `py -3.11` command; install Python 3.11 with the launcher first.

The launchers create `.venv`, install compatible dependencies, and report installation errors before attempting to launch. The macOS/Linux launcher also repairs incomplete installs or changed requirements. Optional arguments:

```bash
./run.sh --camera 1 --sensitivity 1.5 --smoothing 0.7
```

For a manual install:

```bash
python3.11 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
python main.py
```

Install only `opencv-contrib-python`, which MediaPipe also uses. If an older environment contains `opencv-python` too, remove both OpenCV distributions before reinstalling the requirements. Both packages provide the same `cv2` module.

MediaPipe 0.10.21 has a [known Apple Silicon wheel metadata issue](https://github.com/google-ai-edge/mediapipe/issues/6112) that can make `uv pip check` report the wrong architecture. The audit confirmed an arm64 slice and successful inference on this Mac. Use `--self-check` to verify runtime imports and inference on your machine; leave third-party wheel metadata untouched.

This version deliberately constrains MediaPipe to 0.10.14–0.10.21 because it uses `mp.solutions`. MediaPipe removed that API in 0.10.31. See the [upstream explanation](https://github.com/google-ai-edge/mediapipe/issues/6204).

## Camera and permissions

On macOS, grant **Camera** access to the application that launches Python (usually Terminal or your IDE), and enable that application under **System Settings → Privacy & Security → Accessibility**. Global keyboard shortcuts may also need **Input Monitoring**. Restart after changing permissions. The Guide tab links to Accessibility settings.

The app checks Accessibility before enabling mouse control. If camera access fails, the connection message explains recovery. Close other camera apps, choose the correct device in **Controls**, or click **Reconnect camera**. Selecting a device never silently switches to a different camera.

Windows users may need to enable camera access for desktop applications in Privacy settings. Linux users need permission to open the selected video device.

## Gestures

| Pose | Action |
| --- | --- |
| Open palm | Move the cursor, anchored to the index knuckle. |
| Index + thumb pinch | Tap and release for left click. Hold for the configured delay to drag; separate to release. |
| Middle + thumb pinch | Tap and release for right click. Hold for CAD drag using the selected right or middle button. |
| Pinky + thumb pinch | Pinch and release for double click. |
| Point with index and draw circles | Clockwise zooms in; anticlockwise zooms out. Open your hand to leave dial mode. |
| Closed fist | Hold to pause or resume. Open the hand before toggling again. |

Camera or hand loss cancels pending clicks and releases held buttons. Pointing and fist poses take priority over pinches. Separate fingers fully before starting another pinch.

CAD gestures send mouse events; the receiving application's own navigation settings determine whether a drag or wheel movement rotates, pans, or zooms. Recognition depends on lighting, camera angle, hand position, and calibration. No physical precision or clinical accuracy measurement is implied.

## Interface and tuning

- **Controls**: camera selection, preview overlays, CAD button, sound, and power saving.
- **Tuning**: movement presets, sensitivity, smoothing, reach, fine movement speed, sweep boost, pinch threshold, hold duration, zoom speed, and PiP opacity.
- **Guide**: setup, gesture instructions, shortcut availability, and live pinch meters.

Changes apply immediately. Use **Save settings** to keep them in `~/.handtracker/config.json`. Save errors are shown in the interface. **Reset settings** restores tuning and pauses control while keeping the chosen camera and current window mode. Whether mouse control is active is never saved.

Movement maps across the bounding rectangle of detected displays, including displays with negative coordinates. Positions in desktop gaps snap to the nearest display. Display layout is read when the tracking worker starts; reconnect after changing monitor arrangements. Check alignment and scaling on your actual displays before precision work.

**Mini PiP** stays above other windows, keeps pause/resume accessible, and supports resizing down to 180×140. Expanding restores the prior studio window size and position. Double-click the preview to switch modes. Adjust opacity in Tuning or with the shortcuts below. Always-on-top behavior over exclusive full-screen applications depends on the operating system.

## Keyboard shortcuts

Use `Cmd` on macOS and `Ctrl` elsewhere:

| Shortcut | Action |
| --- | --- |
| `Cmd/Ctrl+Shift+H` | Pause or resume control. |
| `Cmd/Ctrl+Shift+M` | Toggle Mini PiP. |
| `Cmd/Ctrl+[` | Reduce PiP opacity. |
| `Cmd/Ctrl+]` | Increase PiP opacity. |
| `Esc` while focused | Pause control. |

The Guide tab reports whether global shortcuts are available. If the global listener cannot start, shortcuts work while the HandTracker window is focused. After granting keyboard permissions, restart the app.

## Checks

```bash
.venv/bin/python -m unittest discover -v tests
.venv/bin/python -m compileall -q src tests main.py
uvx ruff check src main.py tests
uvx ruff format --check src main.py tests HandTracker.spec
```

Run `.venv/bin/python main.py --self-check` to check real Tk resources, input backend imports, and MediaPipe inference without opening the camera or sending mouse events. The same flag works on the packaged executable.

The test suite mocks camera capture, global listeners, and mouse output. GUI tests create real Tk windows and need a desktop session (or Xvfb on Linux). They do not move or click the system mouse. See [the audit report](audit/AUDIT.md) for coverage and manual verification still needed.

## Standalone builds

Build on the target operating system after installing the requirements:

```bash
./build_macos.sh  # dist/HandTracker.app
```

On Windows, run `build_windows.bat`; output is `dist\HandTracker\HandTracker.exe`. Both use `HandTracker.spec`, which collects MediaPipe model data, the CustomTkinter theme, and platform keyboard backends. The macOS bundle includes its camera usage description. These scripts create local builds; signing and notarization for distribution are separate release steps.

## License

Created by **Dr Clark G. Michael**. MIT License; see [LICENSE](LICENSE).
