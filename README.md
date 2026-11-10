# Gesture-controls
[![Ask DeepWiki](https://devin.ai/assets/askdeepwiki.png)](https://deepwiki.com/yuvraj-07/Gesture-controls)

This application allows you to control your system's volume, brightness, and media playback using hand gestures detected through your webcam. It runs in the background with a system tray icon and provides a non-intrusive on-screen display (OSD) for real-time feedback.

The system is designed with a clear separation of controls: the right hand is dedicated to continuous adjustments (volume/brightness), while the left hand performs discrete actions like muting or changing tracks.

## Features

- **Volume & Brightness Control:** Adjust system volume or screen brightness by pinching your right thumb and index finger.
- **Media Controls:** Use your left hand for media playback:
  - **Fist:** Toggle mute.
  - **Thumb-to-Pinky Pinch:** Play/Pause media.
  - **Thumb-to-Middle Pinch:** Skip to the next track.
- **Configurable Gesture Profiles:** Customize the actions assigned to left-hand gestures, including setting custom keyboard shortcuts (Windows only).
- **On-Screen Display (OSD):** A sleek, semi-transparent corner overlay shows the current mode, level, and feedback for actions.
- **System Tray Integration:** Manage the application from the system tray to switch modes, show/hide the camera window, access settings, or quit.
- **Intelligent Tracking:** Includes features to reduce jitter, prevent accidental changes when your hand leaves the frame, and a one-time calibration for your pinch range.
- **Cross-Platform:** Includes build scripts to create standalone executables for Windows and macOS.

## How It Works

The application uses a combination of libraries to achieve real-time gesture recognition:
- **OpenCV:** Captures the video feed from your webcam.
- **MediaPipe:** Detects hand landmarks with high accuracy.
- **pycaw & comtypes:** Manages system audio control (volume, mute) on Windows.
- **screen-brightness-control:** Provides a cross-platform way to adjust display brightness.
- **pystray & Pillow:** Creates and manages the system tray icon and menu.
- **Tkinter:** Powers the settings window and the on-screen display.

## Installation and Usage

To run the application from the source code, follow these steps.

1.  **Clone the repository:**
    ```sh
    git clone https://github.com/yuvraj-07/Gesture-controls.git
    cd Gesture-controls
    ```

2.  **Create a virtual environment (recommended):**
    ```sh
    python -m venv venv
    # On Windows
    venv\Scripts\activate
    # On macOS/Linux
    source venv/bin/activate
    ```

3.  **Install the required dependencies:**
    ```sh
    pip install -r requirements.txt
    ```

4.  **Run the application:**
    ```sh
    python gesture_control.py
    ```

### First-time Setup
- The settings window will appear on the first launch. You can configure output limits and other preferences here.
- When you first switch to "volume" or "brightness" mode, a 3.5-second calibration process will begin. Follow the on-screen prompt to move your right hand from a closed pinch to a wide spread to calibrate your control range.

### Controls
You can control the application using the camera window, system tray, or global hotkeys.

| Action                 | Keyboard (Camera Window) | Tray Menu          | Global Hotkey (Windows) |
| ---------------------- | ------------------------ | ------------------ | ----------------------- |
| Activate Volume Mode   | `v`                      | `Volume mode`      | `Ctrl + Alt + V`        |
| Activate Brightness Mode| `b`                      | `Brightness mode`  | `Ctrl + Alt + B`        |
| Pause Controls (Idle)  | `i`                      | `Idle`             | `Ctrl + Alt + I`        |
| Open Settings          | -                        | `Settings`         | -                       |
| Show/Hide Camera       | -                        | `Show/Hide camera` | -                       |
| Quit Application       | `q`                      | `Quit`             | `Ctrl + Alt + Q`        |


## Building an Executable

You can create a standalone executable that doesn't require a Python installation to run.

### For Windows
Run the PowerShell build script:
```powershell
.\build_windows.ps1
```
The application will be located at `dist\GestureControls\GestureControls.exe`.

### For macOS
Run the shell build script:
```sh
./build_macos.sh
```
The application bundle will be created at `dist/GestureControls.app`.

## Configuration

The application's settings are stored in `gesture_config.json`. While most settings can be configured through the UI, you can manually edit this file to create advanced gesture profiles.

The `profiles` section allows you to map left-hand gestures to specific actions, including custom keyboard shortcuts on Windows.

**Example `gesture_config.json`:**
```json
{
  "output_limits": {
    "volume": { "min": 5, "max": 100 },
    "brightness": { "min": 10, "max": 100 }
  },
  "brightness_display": null,
  "brightness_step_percent": 2,
  "right_pinch_range": {
    "min_ratio": 0.22,
    "max_ratio": 1.69
  },
  "active_profile": "Default",
  "profiles": {
    "Default": {
      "fist": "mute",
      "pinky_pinch": "play_pause",
      "middle_pinch": "next"
    },
    "My Profile": {
      "fist": "shortcut:ctrl+f",
      "pinky_pinch": "shortcut:ctrl+r",
      "middle_pinch": "play_pause"
    }
  }
}