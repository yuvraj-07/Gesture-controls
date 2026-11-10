# Product Requirements Document (PRD)

## Gesture Volume & Brightness Controller
**Product definition, user experience, scope, and acceptance criteria**

| Metadata | Details |
| :--- | :--- |
| **Document Type** | Product Requirements Document |
| **Version / Baseline** | 1.0 — current implementation and requested product scope |
| **Prepared** | 09 November 2026 |
| **Status** | Detailed working specification; hardware/package verification remains open |

> **Reading note:** This document describes the current workspace implementation and the user decisions that shaped it. It distinguishes implemented behavior from validation still required on a real Windows/macOS device.

---

## 1. Executive Summary

The Gesture Volume & Brightness Controller is a local, camera-based desktop utility. It lets a user adjust one selected system output with the right hand while reserving the left hand for mute and media gestures. A compact corner overlay reports output level and action feedback. A system-tray menu supports mode selection, camera-window visibility, settings, and quit; PyInstaller scripts are supplied for windowed desktop builds.

The product is designed around gesture separation and safe loss-of-tracking behavior. It contains no mouse movement or clicking features. It does not control volume and brightness simultaneously: `v` selects volume, `b` selects brightness, and `i` pauses control.

---

## 2. Problem and Opportunity

The starting prototype placed multiple meanings on one hand. The user reported that gestures conflicted and that the camera overlay was cluttered. Subsequent testing feedback also identified false hand detections when hands left the frame, unreliable left-hand media gestures, unintended volume changes while withdrawing the control hand, and a need to run without a terminal window.

The current product resolves these problems by fixing hand roles, limiting the gesture vocabulary, requiring consistent hand detections, calibrating the right-hand control range, filtering jitter, freezing the output when the control hand appears to be withdrawn, and adding dedicated status surfaces.

---

## 3. Product Vision and Goals

- **Continuous Output Control:** Provide hands-free, continuous volume or brightness adjustment using a right-hand thumb–index pinch.
- **Strict Hand Separation:** Keep mute and media gestures on the left hand so they do not compete with the continuous right-hand control.
- **Fail-Safe Tracking:** Ensure loss, small size, or withdrawal of the right hand never causes continued system writes or a sudden level increase.
- **Clean Feedback:** Give visible confirmation of current output and discrete gesture actions without a dense camera overlay.
- **Background Execution:** Allow the application to stay in the system tray and run as a windowed executable rather than requiring a console.
- **Local & Dedicated:** Keep all camera processing local and avoid mouse-control functionality.

---

## 4. Users and Use Context

| User / Context | Need | Product Response |
| :--- | :--- | :--- |
| **Primary user at a Windows desktop** | Adjust sound or screen brightness without reaching for controls. | Right-hand pinch controls the currently selected `v` or `b` mode. |
| **User operating a media player** | Mute, pause/resume, or skip forward using the other hand. | Left fist toggles mute; left thumb–pinky pinch sends play/pause; left thumb–middle pinch sends next-track. |
| **User who wants minimal desktop clutter** | Keep the controller running without a terminal or camera window in the way. | Tray controls can hide/show the camera preview; a small translucent overlay remains available. |
| **Developer/operator** | Tune output range and select brightness target. | Settings window exposes output limits, display target, brightness step, and right-hand calibration reset. |

---

## 5. Product Scope

### 5.1 In Scope
- Camera-based recognition of up to two hands using MediaPipe Hands and OpenCV.
- Right-hand thumb–index continuous level control for either volume mode or brightness mode.
- First-use right-hand pinch calibration, per-mode output limits, EMA smoothing, dynamic dead-zone, and withdrawal guard.
- Left-hand fist mute toggle, thumb–pinky play/pause toggle, and thumb–middle next-track gesture.
- Keyboard controls exactly `v`, `b`, `i`, `q`, with equivalent mode/quit actions in the tray where applicable.
- Brightness display selection and configurable brightness ramp step.
- Semi-transparent corner OSD for output level and discrete action feedback.
- `pystray` menu and windowed PyInstaller build scripts for Windows and macOS.

### 5.2 Out of Scope / Explicitly Excluded
- Mouse movement, click, drag, scroll, or any mouse automation.
- Simultaneous volume and brightness control; only one output is active at a time.
- Preset gestures, open-palm track swipes, or index-pinch play/pause; these were removed/superseded during conflict reduction.
- Previous-track gesture in the final product; the middle-finger pinch always requests next track.
- Guaranteed discovery of actual playback state from all media players. The current OSD state is a local toggle assumption.
- Cloud processing, account sign-in, audio recording, video recording, telemetry, or network service.

---

## 6. User Experience and Primary Flows

### 6.1 First Launch and Calibration
1. The settings dialog appears at launch. The user chooses output limits, brightness target/step if needed, then starts the camera.
2. The tray icon is created after the initial settings dialog. Selecting `v` or `b` starts the selected mode.
3. If no valid right-hand pinch range is stored, a 3.5-second calibration prompt asks the user to move from a closed pinch to a wide spread. A valid range needs at least 25 samples and at least 0.25 ratio span.
4. Left-hand actions remain available during right-hand calibration, provided the app is in volume or brightness mode.
5. The calibrated right-hand range is written to `gesture_config.json` (source run) or the per-user application config path (frozen build).

### 6.2 Normal Operation
1. Press `v` for volume or `b` for brightness while the camera window is focused, or choose the mode from the tray menu.
2. The right hand must remain visible and stable long enough to establish its palm-size reference. Thumb–index distance maps to the selected output limits.
3. The left hand can independently perform one discrete gesture at a time. Gestures latch until release/neutral recognition so holding a gesture does not repeat commands.
4. The corner overlay reports level, and temporarily reports music, track, or mute actions. The camera preview contains only concise status and landmark hints.
5. Select `i` or the tray Idle item to pause controls. Select `q` or tray Quit to terminate. Tray Show/Hide controls the preview window while processing can continue.

---

## 7. Functional Product Requirements

| ID | Requirement | Priority | Acceptance Outcome |
| :--- | :--- | :---: | :--- |
| **PRD-F01** | Right thumb–index pinch controls the active output only. | **Must** | `v` changes volume; `b` changes brightness; neither mode changes the other output. |
| **PRD-F02** | Left fist toggles mute once per fist-and-release cycle. | **Must** | One mute state transition after a stable fist; release and reform toggles again. |
| **PRD-F03** | Left thumb–pinky pinch sends a play/pause media key once per pinch cycle. | **Must** | A distinct pinch sends one command; release is needed to re-arm. |
| **PRD-F04** | Left thumb–middle pinch always advances to the next track. | **Must** | Each distinct pinch-release cycle sends one next-track command; no alternation to previous. |
| **PRD-F05** | No-hand and withdrawal conditions must not drive output upward. | **Must** | No writes occur while the hand is absent, too small, or scale-locked. |
| **PRD-F06** | A semi-transparent corner OSD shows system level and discrete action feedback. | **Must** | The overlay updates while active; action text appears briefly; idle hides it. |
| **PRD-F07** | Tray actions manage modes, settings, camera-window visibility, and shutdown. | **Should** | Menu commands are applied on the camera-loop thread. |
| **PRD-F08** | A windowed build avoids opening a terminal window. | **Should** | PyInstaller build uses `--windowed` and is launched from the generated output folder. |
| **PRD-F09** | User can configure output limits and brightness target/ramp. | **Must** | Saved settings load on the next run. |
| **PRD-F10** | No mouse features are present. | **Must** | No mouse library or mouse input/output paths are included. |

---

## 8. Product Feedback and Visual Design

- **Corner OSD:** Borderless, topmost Tkinter window, approximately 236 × 112 px, alpha 0.92 while active and fading to a faint 0.24 badge. It shows a bar, mode, percentage, and action message.
- **OSD Action Messages:** `MUSIC PAUSED` / `MUSIC PLAYING`, `NEXT TRACK`, `MUTE ON` / `MUTE OFF`, or an unavailable/media error message. Action text is retained for approximately 2.2 seconds.
- **Camera Overlay:** Mode and hand presence, selected level, right pinch/hold/movement status, left pinch ratios, and a short action message. This is intentionally reduced from the former multi-line gesture-debug display.
- **System Tray Menu:** Volume mode, Brightness mode, Idle, Show camera window, Hide camera window, Settings, Quit.

---

## 9. Success Criteria and Acceptance Checklist

| Area | Acceptance Check |
| :--- | :--- |
| **Control Separation** | Right-hand movement only affects the selected `v`/`b` output; left-hand gestures do not alter that continuous level. |
| **Tracking Safety** | With hands absent, or while the right hand is withdrawing and locked, no new system volume/brightness writes are issued. |
| **Gesture Repeat Behavior** | Held gestures fire once. A new mute/media event requires the release/neutral cycle described in the SRS. |
| **Feedback** | OSD value follows the system readback within the polling interval; discrete events appear in the OSD. |
| **Tray** | Each menu item produces its request and Quit ends the camera loop and stops the tray icon. |
| **Build** | On a supported host, the relevant build script creates a windowed package that starts without a console. |

> **Current verification status:** Source syntax and JSON configuration checks have passed in the workspace. Synthetic landmark checks have exercised the pinch classifiers, dead-zone behavior, no-hand output safety, play/pause status logic, and mocked tray wiring. A real webcam, Windows audio endpoint, display brightness device, real media player, and finished Windows/macOS package have not been tested in this environment.

---

## 10. Assumptions, Dependencies, and Risks

| Item | Product Implication / Mitigation |
| :--- | :--- |
| **Lighting, camera angle, and hand visibility** | Recognition can vary by hardware and environment; use calibration and hand-presence status. Real-device validation is required. |
| **Media key support** | Playback commands are sent as global media keys and depend on the operating system/player handling them. |
| **Playback state display** | The OSD toggles a local state that assumes playback is active at app startup; it does not query the player, so external toggles or an initially paused player can make this label inaccurate. |
| **Brightness hardware** | `screen_brightness_control` can only adjust displays supported by its backend; external monitors may not expose brightness. |
| **Tray/build dependencies** | `pystray`, `Pillow`, and `PyInstaller` must be installed on the target build machine; build scripts are not cross-compilers. |
| **OS-specific media controls** | Mute and media-key behavior is implemented for Windows. Volume has platform-specific commands, but Windows is the validated design target; Mac/Linux media control is not equivalent. |

---

## 11. Release Status and Recommended Next Work

Current state is an implementation baseline with source files, configuration, tray integration, and build scripts. It is not a verified release. 

**Recommended next steps:**
1. Run an acceptance pass on the user’s Windows 3.12 x64 machine.
2. Tune palm-size and pinch thresholds from camera measurements.
3. Verify player media-key behavior.
4. Verify window hiding and tray shutdown.
5. Build and smoke-test the PyInstaller output.
6. Consider replacing assumed media status with a Windows media-session query.

---

## 12. Change History from Prototype to Current Product

| Stage | What Changed | Current Disposition |
| :--- | :--- | :--- |
| **Initial Prototype** | Built a webcam-controlled volume/brightness utility with keyboard mode selection and gesture mappings; mouse interactions were briefly explored. | Mouse behavior explicitly removed. Keys remain `v`, `b`, `i`, `q`. |
| **Settings and Calibration** | Added output ranges/presets, pinch calibration persistence, and a Tkinter settings dialog. | Output limits and right-hand calibration remain; preset gestures were removed from final behavior. |
| **Windows System Control** | Added Pycaw volume/mute integration, media keys, brightness monitor selection, and gradual brightness changes. | Volume/brightness/mute/media architecture retained; media actions now fixed to the final left-hand map. |
| **Conflict and Overlay Redesign** | User reported one-hand gesture conflicts and a crowded overlay; roles were separated across two hands. | Right hand is level-only; left hand owns mute and media actions. Camera overlay reduced. |
| **Gesture Corrections** | Index-thumb play/pause and alternating next/previous track were tried. | Replaced: thumb-pinky toggles play/pause; thumb-middle always next track per distinct pinch. |
| **Accuracy and Safety** | Addressed false detections, output jitter, and unintended changes while withdrawing the hand. | Added validation/two-frame confirmation, per-hand role gating, right-hand calibration, median+EMA+dynamic dead-zone, palm-size/withdrawal lock. |
| **Status and Packaging** | Added corner OSD, action feedback, throttled readback, `pystray`, and PyInstaller scripts. | Current OSD/tray design; actual host build and hardware QA remain open. |
