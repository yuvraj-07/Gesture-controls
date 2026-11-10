# Software Requirements Specification (SRS)

## Gesture Volume & Brightness Controller
**Normative software behavior, interfaces, algorithms, data, and verification**

| Metadata | Details |
| :--- | :--- |
| **Document Type** | Software Requirements Specification |
| **Version / Baseline** | 1.0 — current implementation and requested product scope |
| **Prepared** | 09 November 2026 |
| **Status** | Detailed working specification; hardware/package verification remains open |

> **Reading note:** This document describes the current workspace implementation and the user decisions that shaped it. It distinguishes implemented behavior from validation still required on a real Windows/macOS device.

---

## 1. Introduction

### 1.1 Purpose
This SRS defines the current software requirements for the Gesture Volume & Brightness Controller, including the camera pipeline, hand ownership, output mapping, safety behavior, feedback surfaces, tray operations, settings persistence, packaging, and verification status. “Shall” statements describe required behavior for this implementation baseline.

### 1.2 Scope
The software runs locally on a desktop, reads webcam frames, recognizes left/right hand landmarks, maps the right-hand pinch to one selected system output, and converts left-hand gestures to mute/media commands. It offers a Tkinter setup/settings UI, a translucent corner OSD, a camera preview, and a `pystray` system-tray menu. It contains no mouse automation.

### 1.3 Document Conventions
- **Requirement IDs:** Prefixed by category:
  - `SRS-F`: Functional requirement
  - `SRS-NF`: Non-functional requirement
  - `SRS-D`: Data/configuration requirement
  - `SRS-I`: Interface requirement
- **Priority Labels:**
  - **Must:** Baseline required behavior for this release.
  - **Should:** Important quality/product support capability.
  - **Could:** Planned enhancement, not present in the current baseline.
- **Verification Context:** *“Verified in workspace”* means syntax, configuration, mocked, or synthetic tests only; it does not mean a physical device or operating-system integration was verified.

---

## 2. Overall System Description

### 2.1 System Context
The application is a single-process Python program. OpenCV captures and displays camera frames; MediaPipe Hands returns landmarks; `GestureController` classifies and debounces gestures; `SystemControl` adapts output operations to the OS; `CornerStatusOverlay` provides a Tkinter OSD; `TrayController` exposes background commands via `pystray`. The camera loop is the state owner. Tray callbacks only set request values, which the camera loop consumes.

### 2.2 Runtime Components

| Component | Responsibilities |
| :--- | :--- |
| **HandDetector** | MediaPipe Hands setup; confidence, landmark-shape, and size validation; two-frame confirmation; side labels; geometric helpers for palm width, pinch ratios, and fist classification. |
| **SystemControl** | Read/write master volume; query/toggle Windows mute; send Windows media virtual-key events; enumerate/read/write supported brightness displays; log one-time warnings. |
| **GestureController** | Settings/config, right-hand calibration, mode state, filtering, scale lock, left-hand gesture state machine, camera loop, keyboard/tray requests. |
| **CornerStatusOverlay** | Topmost borderless semi-transparent output/action OSD; progress bar; fade behavior; Tk event pumping. |
| **TrayController** | `pystray` icon/menu for modes, camera visibility, settings, and quit; callback-to-loop request bridge. |

### 2.3 Execution Modes

| Mode | Entry | Effect |
| :--- | :--- | :--- |
| **idle** | Key `i` or tray Idle | Right output writes and left-hand actions are paused; OSD is withdrawn. |
| **volume** | Key `v` or tray Volume mode | Right-hand pinch changes master volume; left-hand gestures remain available. |
| **brightness** | Key `b` or tray Brightness mode | Right-hand pinch changes selected display brightness; left-hand gestures remain available. |

The mode model is exclusive: volume and brightness are never driven simultaneously. Keys are `v`, `b`, `i`, `q`. `q` is a keyboard-window command; tray Quit provides an alternate quit path.

---

## 3. Operating Environment and Dependencies

| Area | Current Baseline |
| :--- | :--- |
| **Primary development/runtime target** | Windows desktop; user environment previously confirmed as Python 3.12 x64. |
| **Python dependencies** | `mediapipe==0.10.21`, `opencv-contrib-python==4.11.0.86`, `numpy<2`, `screen-brightness-control`, `pycaw`, `comtypes`, `pystray>=0.19.5`, `Pillow>=10.0.0`. |
| **Packaging** | PyInstaller; PowerShell script for Windows and shell script for macOS. Build must run on the target OS. |
| **Camera** | OpenCV camera index 0; requested 640×480 frame size; buffer size 1; mirrored frame processing. |
| **MediaPipe** | Legacy `mp.solutions.hands` API; `max_num_hands=2`; `model_complexity=0`; `min_detection_confidence=0.72`; `min_tracking_confidence=0.68`. |
| **Hardware requirements** | Webcam; Windows master audio endpoint for Pycaw volume/mute; brightness-capable monitor/backend for brightness control. |

---

## 4. External Interfaces

| Interface | Inputs / Outputs | Current Behavior and Constraints |
| :--- | :--- | :--- |
| **Webcam / OpenCV** | Video frames to detector; preview window to user. | Camera index 0. Preview may be hidden from tray while processing continues. |
| **MediaPipe Hands** | RGB frame in; handedness and 21 landmarks per detection out. | Candidate needs handedness score $\ge 0.82$, plausible landmark geometry, and two consecutive valid frames. |
| **Windows audio endpoint** | Master volume scalar/level and mute flag. | Pycaw uses `EndpointVolume` when available, with older `Activate`/`IAudioEndpointVolume` fallback. |
| **Brightness library** | Display list, brightness read/write and display index. | `screen_brightness_control`; output only works for supported monitors. |
| **Windows media keys** | `VK_MEDIA_PLAY_PAUSE` (0xB3) and `VK_MEDIA_NEXT_TRACK` (0xB0). | Injected with `user32.keybd_event`; success indicates send attempt, not proof the player acted. |
| **Tkinter** | Settings form and OSD windows. | Settings runs on Tk mainloop; OSD is pumped from camera loop about every 0.10 s. |
| **pystray** | Native tray icon/menu. | Callbacks enqueue mode/visibility/settings/quit requests; camera loop performs actions. |

---

## 5. User and System Workflows

### 5.1 Startup / Setup
1. Show settings window and read saved limits, brightness display, brightness step, and calibration status.
2. On *Save and start* or closing the settings loop, start `pystray` when installed, then open camera 0.
3. If camera cannot open, log an error, close detector, stop tray if present, and return.
4. On first active `v`/`b` mode without a valid saved right pinch range, run guided calibration. Calibration records right-hand pinch ratios for 3.5 seconds; 25+ samples and a percentile range span $\ge 0.25$ are required.
5. After successful calibration, save settings and resume control. If calibration is incomplete, retry; left-hand actions are still processed in active modes.

### 5.2 Main Frame Loop
1. Read frame; mirror it; process MediaPipe; retrieve accepted left/right hands.
2. In an active mode, apply right-hand output control or calibration; always run the left-hand handler (which returns immediately in idle).
3. Poll current output and mute state at 0.25-second intervals; update the OSD at 0.10-second intervals.
4. Render concise camera status; show preview only when `camera_visible` is true; process keyboard input and queued tray requests.
5. On shutdown, destroy OSD, release camera, close OpenCV windows, close MediaPipe, and stop tray icon.

---

## 6. Functional Requirements

| ID | Requirement | Priority |
| :--- | :--- | :---: |
| **SRS-F01** | The system shall use MediaPipe to detect up to two hands and shall associate valid detections with left/right handedness. | **Must** |
| **SRS-F02** | A detection shall be rejected if handedness confidence is below 0.82, required geometry is invalid, landmark coordinates are implausible, or consecutive confirmation has not been reached. | **Must** |
| **SRS-F03** | The detector shall require two consecutive valid frames before returning a hand to the controller. | **Must** |
| **SRS-F04** | The right hand shall be the only hand that drives continuous volume or brightness output. | **Must** |
| **SRS-F05** | In volume mode, calibrated right thumb–index ratio shall map linearly to configured volume min/max; out-of-range values shall clamp to limits. | **Must** |
| **SRS-F06** | In brightness mode, the same right-hand control shall map to configured brightness min/max and target monitor; writes shall be ramp-limited by configured step. | **Must** |
| **SRS-F07** | If calibration is absent/invalid, active `v`/`b` mode shall prompt a 3.5-second right-hand closed-to-wide pinch calibration; only valid ranges shall be saved. | **Must** |
| **SRS-F08** | A valid right calibration shall contain at least 25 samples; low/high bounds shall be the 3rd/97th percentiles and must span at least 0.25 ratio. | **Must** |
| **SRS-F09** | The right control shall establish a palm-size anchor from seven valid samples; it shall not adjust output during acquisition. | **Must** |
| **SRS-F10** | Right-hand output shall pause when the hand is absent, too small (<45 palm-width metric), or scale-locked. | **Must** |
| **SRS-F11** | A right hand that shrinks >10% from anchor or shows >=4% short-window shrinking shall lock output until missing/small-hand duration reaches 0.35 seconds and the hand is reacquired. | **Must** |
| **SRS-F12** | Pinch-ratio input shall use a five-sample median, an EMA with alpha 0.28, and a jitter-adaptive dead-zone bounded from 1 to 5 output percentage points. | **Must** |
| **SRS-F13** | Volume writes shall be rate-limited to at most one write per 0.10 seconds; brightness writes to at most one per 0.16 seconds, with brightness ramp step applied. | **Must** |
| **SRS-F14** | Left fist held >=0.32 seconds shall toggle Windows mute once; another toggle shall require release/neutral re-arm. | **Must** |
| **SRS-F15** | Left thumb–pinky pinch held >=0.20 seconds shall send exactly one play/pause media key per pinch cycle. | **Must** |
| **SRS-F16** | The local OSD play state shall toggle on successful key injection; its initial state shall assume playback is active. It shall not claim OS/player-confirmed state. | **Must / Known Limitation** |
| **SRS-F17** | Left thumb–middle pinch held >=0.20 seconds shall send one next-track key per distinct pinch; it shall never alternate to previous track. | **Must** |
| **SRS-F18** | Left pinch actions shall distinguish middle/pinky distances normalized to palm width, apply activation/release thresholds, and require a neutral release period of 0.16 seconds to re-arm. | **Must** |
| **SRS-F19** | Left actions shall remain independent from right calibration but shall be disabled in idle mode. | **Must** |
| **SRS-F20** | Keyboard controls shall be exactly `v`=volume, `b`=brightness, `i`=idle, `q`=quit. | **Must** |
| **SRS-F21** | Settings shall support volume/brightness output limits, display target, brightness step, and reset right-hand calibration. | **Must** |
| **SRS-F22** | The corner OSD shall show active mode and percentage, update on value changes, fade from alpha 0.92 to a minimum of 0.24, hide in idle, and display gesture action messages for about 2.2 seconds. | **Must** |
| **SRS-F23** | The tray menu shall support volume, brightness, idle, show/hide camera window, settings, and quit. Tray callbacks shall communicate by request flags rather than touching camera-loop UI directly. | **Should** |
| **SRS-F24** | Tray Quit shall terminate the camera loop and close camera, detector, OSD, and tray resources. | **Must** |
| **SRS-F25** | The application shall log actionable warnings/errors for unavailable audio, brightness, media, camera, tray, or OSD services and continue where possible. | **Should** |
| **SRS-F26** | The application shall persist named profiles containing one action per left fist, thumb-pinky pinch, and thumb-middle pinch. | **Must** |
| **SRS-F27** | Profile actions shall include none, mute, play/pause, next, previous, or a user-entered keyboard shortcut. | **Should** |
| **SRS-F28** | On Windows, shortcut syntax shall accept one to four keys joined by `+`, supporting Ctrl, Alt, Shift, Win, letters, digits, F1–F12, and common navigation keys. Invalid syntax shall not send key events. | **Must** |
| **SRS-F29** | Settings shall offer a shortcut test for a selected gesture mapping and send it after a three-second countdown, allowing the user to focus the target application. | **Should** |
| **SRS-F30** | The tray menu shall expose each saved profile; selecting one shall enqueue the request for the camera-loop owner to apply and persist. Profile selection shall not change the active output mode. | **Should** |
| **SRS-F31** | On Windows, register Ctrl+Alt+V/B/I/Q as global volume/brightness/idle/quit shortcuts, poll them from the camera loop, and unregister them during shutdown. Registration conflicts shall be reported without terminating the application. | **Must** |

---

## 7. Gesture and Control Algorithms

### 7.1 Right-Hand Continuous Control
- **Pinch Ratio:** Calculated as the 3D Euclidean distance from thumb tip (landmark 4) to index fingertip (landmark 8) divided by the 3D distance between MCP landmarks 5 and 17. MediaPipe $z$ is scaled to frame width before 3D distances are calculated.
- **Calibration Mapping:** Stores `min_ratio` and `max_ratio`.
  $$\text{normalized} = \text{clip}\left(\frac{\text{ratio} - \text{min}}{\text{max} - \text{min}}, 0, 1\right)$$
  $$\text{Output} = \text{round}\Big(\text{output\_min} + \text{normalized} \times (\text{output\_max} - \text{output\_min})\Big)$$
- **Input Smoothing:** A sliding window `deque(maxlen=5)` extracts the median sample, followed by an Exponential Moving Average (EMA):
  $$\text{filtered} \leftarrow \text{filtered} + 0.28 \times (\text{target} - \text{filtered})$$
  *(applied only when delta exceeds the dynamic dead-zone).*
- **Dynamic Dead-Zone:** Median Absolute Deviation (MAD) of recent ratio samples is converted to output percentage points using calibration span and output range:
  $$\text{Deadzone} = \text{clip}(1 + 2 \times \text{jitter\_points}, 1, 5)$$
- **Palm Withdrawal Guard:** Seven valid palm-size observations establish a reference; a minimum metric of 45 is required. $>10\%$ change or short-term shrink trend triggers a hold. The OSD and camera report `RIGHT MOVING — LEVEL HELD`.

### 7.2 Left-Hand Gesture State Machine

| Gesture | Signal / Threshold | Hold / Re-arm | Output |
| :--- | :--- | :--- | :--- |
| **Fist** | All four finger chains classified curled by wrist and MCP/PIP/TIP geometry. | 0.32 s stable hold; one event until neutral/release. | Toggle Windows master mute; show `MUTE ON` / `MUTE OFF`. |
| **Thumb–pinky pinch** | Thumb-tip/pinky-tip normalized distance; activation 0.62; release 0.68; distinguish from middle pinch by 0.05 separation. | 0.20 s stable hold; one event; neutral 0.16 s re-arm. | Send play/pause media key; local state toggles between `MUSIC PAUSED` and `MUSIC PLAYING`. |
| **Thumb–middle pinch** | Thumb-tip/middle-tip normalized distance; activation 0.58; release 0.68; distinguish from pinky pinch by 0.05 separation. | 0.20 s stable hold; one next-track event; neutral 0.16 s re-arm. | Send next-track media key every distinct pinch. |

The left-hand state retains a fired latch through short detection losses (up to 0.5 seconds) to avoid duplicate triggers from a one-frame dropout. The hand must be visibly neutral or absent long enough to re-arm.

---

## 8. Data and Configuration

### 8.1 Current JSON Schema

```json
{
  "output_limits": {
    "volume": {"min": 5, "max": 90},
    "brightness": {"min": 10, "max": 100}
  },
  "brightness_display": null,
  "brightness_step_percent": 4,
  "right_pinch_range": null,
  "active_profile": "Default",
  "profiles": {"Default": {"fist": "mute", "pinky_pinch": "play_pause", "middle_pinch": "next"}}
}
```

- **Defaults:** Volume min/max 5/90; brightness min/max 10/100; brightness step 4%; `right_pinch_range` null until calibration.
- **Migration & Paths:** The loader can migrate the right-hand entry from the previous `pinch_ranges` object.
- **Profiles:** `active_profile` selects a named entry in `profiles`; each profile maps `fist`, `pinky_pinch`, and `middle_pinch` to an action. Shortcuts use the form `shortcut:ctrl+shift+m` and are supported on Windows only.
  - *Source execution:* Stores JSON next to `gesture_control.py`.
  - *Frozen builds:* Stores under the per-user application config directory (`%APPDATA%\GestureControls` on Windows; `~/Library/Application Support/GestureControls` on macOS; XDG config path on Linux) and copies the bundled initial config on first run.

### 8.2 Validation and Persistence
- Output limits are clamped/validated so `min < max` and within 0–100.
- Brightness step is clamped to 1–10.
- Display is selected from discovered monitor names/indexes; `null` means all supported displays.
- Pinch range must be finite, $0 \le \text{min} < \text{max} \le 2$, with span at least 0.25.
- Settings serialize as indented UTF-8 JSON. Save errors are logged; invalid/missing settings fall back to defaults.

---

## 9. Non-Functional Requirements

| ID | Requirement / Target | Evidence / Status |
| :--- | :--- | :--- |
| **SRS-NF01** | Local-only camera processing; no video/audio recording or network transmission. | Code path is local; no recording/network feature exists. |
| **SRS-NF02** | A lost right hand shall cease output writes immediately for that frame; missing hand resets tracking after 0.35 s. | Source logic; synthetic no-hand safety check passed. |
| **SRS-NF03** | Status reads are throttled to 0.25 s and OSD pumping to 0.10 s, avoiding system polling on every camera frame. | Implemented; not benchmarked on target hardware. |
| **SRS-NF04** | Detector uses two-frame confirmation and geometry checks to reduce false positives. | Implemented; real face/hand scene validation pending. |
| **SRS-NF05** | The OSD shall be borderless, topmost, semi-transparent, and non-modal. | Implemented in Tkinter; desktop appearance/focus behavior pending target OS test. |
| **SRS-NF06** | The tray app shall run without a terminal when packaged with `--windowed`. | Build scripts created; package not built in this environment. |
| **SRS-NF07** | The camera loop shall release hardware/UI resources on normal quit and camera read/open failure. | Normal quit and open-failure cleanup paths implemented. |
| **SRS-NF08** | Gesture thresholds and smoothing shall be explicit constants and maintainable in the codebase. | Implemented as class constants/fields; end-user calibration currently covers the right continuous pinch only. |
| **SRS-NF09** | No mouse automation or mouse-control dependency shall be included. | No mouse code/dependency in current requirements. |

---

## 10. Error Handling and Operational Constraints

| Condition | Expected Response |
| :--- | :--- |
| **Camera cannot open/read** | Log error; release camera where possible; close detector/tray; terminate run or loop cleanly. |
| **Hand absent / invalid** | Do not calculate new output; clear ratio history; after timeout reset scale anchor. |
| **Audio endpoint unavailable** | Warn once; volume/mute actions report unavailable or return no readback; rest of app remains usable. |
| **Brightness backend/display unavailable** | Warn on setting failure or report no current readback; do not crash the application loop. |
| **Media action on non-Windows OS/player ignores key** | Warn that media-key support is Windows-only; success is not proof of playback response. |
| **pystray import/backend failure** | Warn and continue with keyboard/camera workflow; tray functionality unavailable. |
| **Tkinter OSD failure** | Warn and continue with camera-window overlay/controls where possible. |
| **Settings JSON invalid or unreadable** | Warn, retain defaults, and continue; frozen path is per-user and writable. |

---

## 11. Verification and Validation Plan

| Test ID | Test | Current Result / Required Follow-Up |
| :--- | :--- | :--- |
| **SRS-T01** | Compile `gesture_control.py` and parse `gesture_config.json`. | Passed in workspace after tray changes. |
| **SRS-T02** | Synthetic thumb-middle and thumb-pinky landmark classification. | Passed in prior workspace test; tests are synthetic, not camera input. |
| **SRS-T03** | Dynamic dead-zone should increase as sample jitter increases. | Passed with synthetic steady/noisy sample sets. |
| **SRS-T04** | No accepted right hand issues no volume write. | Mocked no-hand safety check passed. |
| **SRS-T05** | Mocked `pystray` menu construction and detached start wiring. | Passed with a fake tray backend; actual OS tray remains untested. |
| **SRS-T06** | Run on Windows with real webcam; verify side labels, face rejection, calibration, hand withdrawal lock. | Not run; required on user’s device. |
| **SRS-T07** | Verify Pycaw volume and mute read/write against Windows default endpoint. | Not run on target machine. |
| **SRS-T08** | Verify media keys with target player, including pause/resume and repeated next-track pinch cycles. | Not run; player may ignore global media keys. |
| **SRS-T09** | Verify brightness read/write on each selected monitor and output ramp. | Not run on target monitor hardware. |
| **SRS-T10** | Build and launch Windows no-console executable; test tray open/hide/settings/quit. | Not built in the Linux workspace; run `build_windows.ps1` on Windows. |
| **SRS-T11** | Build and launch macOS `.app` and check camera permissions/tray behavior. | Not built/tested; run `build_macos.sh` on macOS. |

---

## 12. Traceability to User Decisions

| User Direction / Issue | Current Implementation Response |
| :--- | :--- |
| **Remove mouse functionality.** | No mouse APIs/features/dependency; only volume, brightness, mute, and media actions. |
| **Use different hands to avoid gesture conflicts.** | Right hand is continuous level control; left hand owns all discrete gestures. |
| **Right hand controls volume and brightness, with v/b selecting output.** | Right pinch changes only the active `v` or `b` mode. |
| **Left fist toggles mute/unmute.** | Debounced fist event toggles actual Windows mute once; release/reform required. |
| **Thumb-middle changes track repeatedly forward, not alternating.** | Each distinct left thumb-middle pinch sends next-track only. |
| **Use thumb-pinky rather than index-thumb for play/pause.** | Left thumb-pinky pinch sends play/pause; index pinch has no media action. |
| **Reduce jitter and stop level changes when hand is withdrawn.** | Median + EMA + dynamic dead-zone and palm-scale withdrawal lock. |
| **Show level and gesture feedback in a native-like overlay.** | Tkinter topmost fading OSD reports volume/brightness and discrete action messages. |
| **Run quietly in the background.** | `pystray` menu plus PyInstaller `--windowed` scripts; camera can be hidden. |

---

## 13. Implementation Change Log

| Revision Stage | Technical Change | Status in Current Baseline |
| :--- | :--- | :--- |
| **Prototype** | Single-hand volume/brightness controller and settings began; mouse experiments were later removed. | Current baseline contains no mouse behavior. |
| **Initial Feature Expansion** | Added output limits/presets, spatial calibration, mute/media actions, brightness ramp and monitor choice. | Limits/ramp/display remain; earlier preset/open-palm/index gestures are superseded. |
| **Two-Hand Redesign** | Separated continuous control from discrete actions and reduced overlay detail after user feedback. | Fixed roles are final; no configurable hand assignment. |
| **Gesture Refinement** | Changed play/pause from index-thumb to pinky-thumb; changed middle pinch from alternating previous/next to next-only. | Final maps are in SRS-F15–F17. |
| **Accuracy / Performance** | Added detector validation, frame confirmation, median/EMA/dead-zone, hand scale gate, 0.25 s output polling, brightness cache/ramp. | Current filter constants and guard are documented above. |
| **OSD / Tray / Package** | Added action feedback OSD, `pystray` menu, frozen-config path, requirements, Windows/macOS build scripts. | Source and scripts present; packages await native-host build/test. |

---

## 14. Known Limitations and Future Work

1. **Media Playback State:** The app does not query Windows Global System Media Transport Controls; OSD `MUSIC PLAYING / PAUSED` is a local toggle that assumes playback started active. External player controls can desynchronize it.
2. **Platform Parity:** Media keys and custom keyboard shortcuts are implemented for Windows only; Mac/Linux volume branches do not provide matching mute/media behavior.
3. **Environmental Validation:** Face rejection and hand geometry have not been validated across lighting, camera models, occlusions, or multiple users.
4. **Anchor Sensitivity:** The fixed palm-scale lock may require hand removal/re-entry after substantial hand movement; thresholds may need per-device tuning.
5. **Packaging Smoke-Testing:** PyInstaller scripts and app bundles are not built or smoke-tested; signing, notarization, installer, auto-start, and tray icon polish are future work.
6. **Device End-to-End Tests:** Automated end-to-end tests against actual camera/audio/monitor devices are still required.
