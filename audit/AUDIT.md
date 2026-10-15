# HandTracker code and interface audit

The source review covers every tracked Python source, original test, launcher, build script, requirements file, README, and ignore rule present at the start of the audit. The changes address input ownership, gesture transitions, camera recovery, configuration integrity, installation compatibility, and the desktop interface. Automated checks verify specific paths; hands-on camera, CAD, and visual review remain necessary before treating the application as ready for precision work.

The working tree already contained changes in seven files. A local copy of that starting diff is in `pre-existing-changes.patch`, excluded from version control. Existing gesture fixes and their regression tests were carried forward into the revised implementation. The existing virtual environment was repaired to match the revised requirements.

## High priority findings and fixes

| Finding | Resulting behavior | Verification |
| --- | --- | --- |
| Camera read failures and reconnects skipped gesture updates, leaving a held drag active. | Every disconnect cancels gesture state, releases input, and pauses control before retrying. | Worker camera read failure test. |
| Shutdown created a new controller with empty button flags, so it could not release the real controller's drag. | One controller owns input; shutdown releases that instance, signals the worker, stops the keyboard listener, and waits briefly for cleanup. | Shutdown ownership test. |
| Worker initialization or inference failures had no guaranteed cleanup or visible recovery state. | A `try/finally` boundary releases camera, model, and mouse resources; errors appear in the connection area with reconnect instructions. | Initialization failure test; model smoke check. |
| Camera capture or inference could stall while input remained held. | The UI watches preview progress and releases input after a 2.5-second stall, independently of camera I/O. | Preview watchdog test. |
| Cancelled pinches retained timestamps and could generate clicks after hand loss, pause, fist, or zoom entry. | All interruption paths discard pending clicks and release active drags. | Separate regression tests for each interruption. |
| Switching pinch types or CAD buttons could overlap actions or release a different button from the one pressed. | Pinches are exclusive; release finishes before another pinch starts. The engine remembers the pressed CAD button, and changing it cancels the current drag. | Direct transition and CAD button tests. |
| Settings accepted invalid types, non-finite numbers, and attributes such as `save`. | Only dataclass preference fields load; booleans and enums are validated, numeric values are checked and bounded. | Corrupt file, invalid types, unknown keys, and large integer tests. |
| Fresh installs could select a MediaPipe release without `mp.solutions`; requirements also installed two competing `cv2` providers. | MediaPipe and OpenCV are constrained to a compatible API generation. Launchers repair incomplete installs and remove duplicate OpenCV distributions. | Dependency installation and import checks; upstream API reference below. |
| Accessibility-denied input could appear enabled even though macOS ignored events. | Resume checks event-posting access without opening a permission prompt, stays paused on failure, and shows recovery text. | Permission failure test. |

## Gesture and cursor findings and fixes

| Finding | Fix | Verification |
| --- | --- | --- |
| Large acceleration steps could overshoot the absolute target and leave the internal cursor outside display bounds. | Cap convergence at the target and clamp the stored coordinates as well as the emitted coordinates. | Monotonic convergence and internal bounds tests. |
| Cursor mapping only covered the primary display despite multi-monitor claims. | Read display bounds, include negative origins, and project positions out of gaps between displays. | Negative origin and display gap tests; actual macOS display enumeration. |
| Small wheel deltas rounded to zero independently every frame. | Accumulate fractional wheel units across frames. | Fractional scroll test. |
| macOS double-click updated the count only on mouse-down events. | Set click counts on both down and up events. | Mocked Quartz event sequence test. |
| Pending click timing used wall time and zero as an unset sentinel. | Use monotonic time with explicit unset timestamps. | Pinch and fist tests beginning at time zero. |
| A long pinky pinch had no action. | Every completed pinky pinch emits one double click, subject to debounce. | Long pinky hold test. |
| Click labels could be overwritten by idle pose handling on release. | Preserve discrete click events and their displayed gesture. | Curled release test. |
| The moving-center dial calculation could convert straight strokes or reversals into zoom. | Use successive path directions to measure curvature, reject straight motion and reversals, and stop immediately on stationary or non-pointing input. | Clockwise, anticlockwise, stationary, straight stroke, reversal, and zoom exit tests. |
| Landmark distances combined coordinates normalized against different image dimensions. | Convert y into width-based units before measuring hand geometry. | Equal physical geometry at 4:3 and 16:9 tests. |
| Invalid landmarks could reach input calculations. | Reject incomplete and non-finite landmark sets. | Invalid landmark tests. |
| Input failures were swallowed by the mouse backend. | Let failures reach the worker's cleanup boundary; try releasing every owned button even if another release fails. UI callback failures also pause input, and preview polling reschedules even if a render callback fails. | Failed click and partial release tests. |

## Interface findings and fixes

The Controls, Tuning, and Guide tabs replace a single long settings column. Pause/resume remains in the header in both studio and PiP. Save and reset remain outside the scrollable settings, and camera reconnect stays beside the connection message.

- Start paused on every launch; do not restore an active mouse-control state from disk.
- Show connecting, unavailable, ready, and failed states with actionable messages. Clear stale previews and meters when the camera fails.
- Use a separate preview message widget to avoid a Tk image-reference crash when clearing a camera error.
- Preserve preview aspect ratio while shrinking to PiP, without allowing the image's requested size to enlarge the window.
- Restore the exact previous studio geometry after PiP instead of switching to a different hard-coded size.
- Keep the pause and expand buttons within the 180×140 PiP window.
- Wrap guide descriptions and remove long single-line header copy that clipped at smaller sizes.
- Remove the inactive sniper slider from the interface; retain the old preference only for compatibility.
- Implement global hotkeys through a queued listener, with no Tk calls from listener threads. Report focused-window fallback when global shortcuts are unavailable.
- Display failed saves instead of reporting success. Save by atomic replacement so an interrupted write does not truncate the previous settings file.
- Use supported ASCII text in the OpenCV HUD, fit the status label to the frame, and distinguish `INDEX_DIAL_READY` from actual zoom-in events.

Real Tk tests exercise studio layout at 860×600, PiP at 180×140, geometry restoration, aspect ratio, pause behavior, error recovery, queued commands, save failure, reset, and shutdown. These tests check geometry and behavior; they do not substitute for a visual inspection.

## Launch and packaging findings and fixes

Command-line parsing now works before GUI imports and rejects NaN, infinity, invalid camera indexes, and values outside the slider ranges. The launchers check Python compatibility, propagate installation failures, and can repair an interrupted installation. Windows build failures no longer print a success message.

Both build scripts use one reviewed `HandTracker.spec`. It includes model/theme assets, platform-specific pynput backends, and the macOS camera usage description. The declared MIT license now has a matching license file. Documentation describes measured behavior and operational constraints without claiming sub-millimeter accuracy, a One Euro filter, or guaranteed full-screen PiP behavior.

## Verification

The original 18 tests passed before changes. The expanded suite currently has **76 passing tests**, with camera capture, global listeners, and mouse output mocked. Tk layout tests create actual desktop windows. A real MediaPipe model also initialized and processed a synthetic blank 640×480 frame successfully, then closed cleanly.

Additional checks include Python compilation, Ruff linting and formatting, Bash syntax, command-line validation, native display enumeration, and repository whitespace checks. The repaired environment uses Python 3.11.15, MediaPipe 0.10.21, OpenCV contrib 4.11.0.86, NumPy 1.26.4, and CustomTkinter 5.2.2. The competing `opencv-python` package was removed. Both source and packaged `--self-check` runs pass; the command exercises actual Tk/image resources, input backend imports, and model inference without opening a camera or posting mouse events.

`uv pip check` reports one architecture warning for MediaPipe. Its wheel metadata claims x86_64, while the installed binding is a Mach-O universal binary containing both x86_64 and arm64. Actual arm64 inference passed. This matches [upstream issue 6112](https://github.com/google-ai-edge/mediapipe/issues/6112); third-party metadata was left untouched.

The local arm64 macOS build completed successfully at `dist/HandTracker.app`. The packaged self-check passes, the bundle contains `NSCameraUsageDescription`, and `codesign --verify --deep --strict` passes for its local ad hoc signature. This is not a Developer ID signed or notarized distribution. The build emits static-analysis warnings for dynamically exposed Quartz symbols and platform-specific ctypes libraries; the packaged backend import and model/UI resource checks pass.

Detailed test output is in `test-results.txt`; source and packaged diagnostic output is in `self-check.txt` and `packaged-self-check.txt`.

## Manual acceptance still required

1. Grant camera and Accessibility permissions on the target machine; confirm that a denied permission produces a useful recovery message.
2. Test all gestures with both hands, varied lighting, camera distances, and wrist angles. Confirm that ordinary hand transitions do not trigger unwanted clicks or pauses.
3. Exercise left drag, both CAD drag buttons, double-click, and circular zoom in the actual CAD applications and their configured navigation modes.
4. Disconnect/reconnect the camera during a drag. Confirm release, paused recovery, the selected camera, and usable preview feedback.
5. Check movement, reach, and cursor alignment across the actual mixed-DPI monitor arrangement. Reconnect after changing the display layout.
6. Visually inspect the controls, long error messages, keyboard focus, HiDPI scaling, opacity, and both window modes. The desktop tool rejected access to the Python window, so screenshots were not reviewed in this session.
7. Run the application and packaged artifact on Windows and an X11 Linux desktop. The current execution environment is macOS.
8. Verify camera access and shortcuts in the packaged macOS app. Distribution signing and notarization remain release work.

A failed operating-system button release cannot be guaranteed recoverable by application code alone. The application attempts every owned release, retries on control-state errors, logs failures, and stays paused. Recognition thresholds and dial sensitivity still require calibration against real camera footage. The retained legacy MediaPipe API should eventually be migrated to Tasks in a separately tested change.

## External API references

MediaPipe maintainers confirm removal of the Solutions API in 0.10.31 in [upstream issue 6204](https://github.com/google-ai-edge/mediapipe/issues/6204). The global shortcut implementation follows the [pynput keyboard documentation](https://pynput.readthedocs.io/en/latest/keyboard-usage.html). The macOS bundle metadata uses the [PyInstaller spec file interface](https://pyinstaller.org/en/stable/spec-files.html).
