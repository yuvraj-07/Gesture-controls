"""Gesture controls for volume, brightness, and left-hand media actions.

Keys (camera window focused): v = volume, b = brightness, i = idle, q = quit.
Right hand: thumb/index pinch adjusts the selected level only.
Left hand: fist toggles mute; thumb/pinky pinch toggles play/pause;
each thumb/middle pinch advances to the next track.
"""

from collections import deque
import ctypes
import json
import os
import math
import platform
import subprocess
import sys
import time
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np


class HandDetector:
    """Detect only confident, hand-shaped landmarks; never infer a missing hand."""

    def __init__(self):
        self.model = mp.solutions.hands.Hands(
            static_image_mode=False,
            max_num_hands=2,
            model_complexity=0,
            min_detection_confidence=0.72,
            min_tracking_confidence=0.68,
        )
        self.confirmed_frames = {"left": 0, "right": 0}

    @staticmethod
    def _valid_shape(landmarks):
        points = np.array([(p.x, p.y, p.z) for p in landmarks.landmark], dtype=float)
        if points.shape != (21, 3) or not np.isfinite(points).all():
            return False
        x_span = float(points[:, 0].max() - points[:, 0].min())
        y_span = float(points[:, 1].max() - points[:, 1].min())
        palm_width = float(np.linalg.norm(points[5, :2] - points[17, :2]))
        if x_span < 0.045 or y_span < 0.065 or palm_width < 0.025:
            return False
        if np.any(points[:, 0] < -0.08) or np.any(points[:, 0] > 1.08):
            return False
        if np.any(points[:, 1] < -0.08) or np.any(points[:, 1] > 1.08):
            return False
        # A plausible palm has distinct wrist-to-knuckle distances and no
        # collapsed landmark chain, which rejects many face-shaped false hits.
        wrist_distances = [np.linalg.norm(points[i, :2] - points[0, :2]) for i in (5, 9, 13, 17)]
        if min(wrist_distances) < 0.018 or max(wrist_distances) > 0.55:
            return False
        for a, b in ((0, 1), (1, 2), (2, 3), (3, 4), (5, 6), (6, 7), (7, 8),
                     (9, 10), (10, 11), (11, 12), (13, 14), (14, 15), (15, 16),
                     (17, 18), (18, 19), (19, 20)):
            if np.linalg.norm(points[a, :2] - points[b, :2]) < 0.002:
                return False
        return True

    def process(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        rgb.flags.writeable = False
        result = self.model.process(rgb)
        found = {}
        if result.multi_hand_landmarks and result.multi_handedness:
            height, width = frame.shape[:2]
            for landmarks, handedness in zip(result.multi_hand_landmarks, result.multi_handedness):
                classification = handedness.classification[0]
                side = classification.label.lower()
                if side not in ("left", "right") or classification.score < 0.82:
                    continue
                if not self._valid_shape(landmarks):
                    continue
                # Ignore ambiguous duplicate labels instead of assigning a
                # second detection to the wrong hand.
                if side in found:
                    found.pop(side, None)
                    continue
                found[side] = [
                    (int(point.x * width), int(point.y * height), float(point.z * width))
                    for point in landmarks.landmark
                ]

        hands = {}
        for side in ("left", "right"):
            self.confirmed_frames[side] = self.confirmed_frames[side] + 1 if side in found else 0
            if side in found and self.confirmed_frames[side] >= 2:
                hands[side] = found[side]
                points = found[side]
                for landmark in (0, 4, 8, 12, 20):
                    cv2.circle(frame, points[landmark][:2], 4, (80, 190, 255), cv2.FILLED)
                cv2.putText(frame, side.upper(), points[0][:2], cv2.FONT_HERSHEY_SIMPLEX,
                            0.55, (80, 220, 255), 2, cv2.LINE_AA)
        return hands

    @staticmethod
    def distance(points, first, second):
        # MediaPipe z is normalized to image width; it is scaled to pixels in
        # process(), so pinch measurements include finger depth as well.
        return math.dist(points[first], points[second])

    @classmethod
    def palm_width(cls, points):
        return max(cls.distance(points, 5, 17), 1.0)

    @classmethod
    def pinch_ratio(cls, points, finger_tip=8):
        return cls.distance(points, 4, finger_tip) / cls.palm_width(points)

    @classmethod
    def is_fist(cls, points):
        wrist = points[0]
        curled = 0
        for mcp, pip, tip in ((5, 6, 8), (9, 10, 12), (13, 14, 16), (17, 18, 20)):
            d_pip = math.dist(wrist, points[pip])
            d_tip = math.dist(wrist, points[tip])
            segment = max(math.dist(points[mcp], points[pip]), 1.0)
            folded_at_mcp = math.dist(points[mcp], points[tip]) < 1.55 * segment
            curled += d_tip < d_pip * 1.12 or folded_at_mcp
        return curled == 4

    def close(self):
        self.model.close()


class SystemControl:
    def __init__(self):
        self.os_name = platform.system()
        self.audio = None
        self.audio_scalar = False
        self.audio_min, self.audio_max = -65.0, 0.0
        self.warned = set()
        if self.os_name == "Windows":
            self._init_audio()

    def warn(self, key, message):
        if key not in self.warned:
            print(message)
            self.warned.add(key)

    def _init_audio(self):
        try:
            from ctypes import POINTER, cast
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            device = AudioUtilities.GetSpeakers()
            endpoint = getattr(device, "EndpointVolume", None)
            if endpoint is not None:
                self.audio, self.audio_scalar = endpoint, True
            else:
                interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                self.audio = cast(interface, POINTER(IAudioEndpointVolume))
                self.audio_min, self.audio_max = self.audio.GetVolumeRange()[:2]
        except Exception as error:
            self.warn("audio_init", f"[WARN] Windows audio control unavailable: {error}")

    def get_volume(self):
        if self.os_name != "Windows" or self.audio is None:
            return None
        try:
            if self.audio_scalar:
                return round(self.audio.GetMasterVolumeLevelScalar() * 100)
            current = self.audio.GetMasterVolumeLevel()
            return round((current - self.audio_min) * 100 / (self.audio_max - self.audio_min))
        except Exception:
            return None

    def set_volume(self, value):
        value = int(np.clip(value, 0, 100))
        try:
            if self.os_name == "Windows":
                if self.audio is None:
                    return False
                if self.audio_scalar:
                    self.audio.SetMasterVolumeLevelScalar(value / 100.0, None)
                else:
                    level = self.audio_min + (value / 100.0) * (self.audio_max - self.audio_min)
                    self.audio.SetMasterVolumeLevel(level, None)
            elif self.os_name == "Darwin":
                subprocess.run(["osascript", "-e", f"set volume output volume {value}"],
                               check=True, capture_output=True)
            else:
                subprocess.run(["amixer", "-D", "pulse", "sset", "Master", f"{value}%"],
                               check=True, capture_output=True)
            return True
        except Exception as error:
            self.warn("set_volume", f"[WARN] Could not set volume: {error}")
            return False

    def is_muted(self):
        if self.os_name != "Windows" or self.audio is None:
            return None
        try:
            return bool(self.audio.GetMute())
        except Exception:
            return None

    def toggle_mute(self):
        if self.os_name != "Windows" or self.audio is None:
            self.warn("mute", "[WARN] Mute control is unavailable on this system.")
            return None
        try:
            muted = not bool(self.audio.GetMute())
            self.audio.SetMute(int(muted), None)
            return muted
        except Exception as error:
            self.warn("mute_error", f"[WARN] Could not toggle mute: {error}")
            return None

    def media_key(self, action):
        codes = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1}
        if self.os_name != "Windows":
            self.warn("media_os", "[WARN] Media-key gestures require Windows.")
            return False
        try:
            key = codes[action]
            user32 = ctypes.windll.user32
            user32.keybd_event(key, 0, 0x0001, 0)
            user32.keybd_event(key, 0, 0x0003, 0)
            return True
        except Exception as error:
            self.warn("media_key", f"[WARN] Could not send media key: {error}")
            return False

    def keyboard_shortcut(self, shortcut):
        if self.os_name != "Windows":
            self.warn("shortcut_os", "[WARN] Custom shortcuts currently require Windows.")
            return False
        names = {"ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B,
                 "enter": 0x0D, "space": 0x20, "tab": 0x09, "esc": 0x1B,
                 "delete": 0x2E, "home": 0x24, "end": 0x23, "up": 0x26,
                 "down": 0x28, "left": 0x25, "right": 0x27}
        parts = [part.strip().lower() for part in shortcut.split("+")]
        if not 1 <= len(parts) <= 4 or any(not part for part in parts): return False
        keys = []
        for part in parts:
            if part in names: code = names[part]
            elif len(part) == 1 and part.isalnum(): code = ord(part.upper())
            elif part.startswith("f") and part[1:].isdigit() and 1 <= int(part[1:]) <= 12: code = 0x70 + int(part[1:]) - 1
            else: return False
            keys.append(code)
        user32 = ctypes.windll.user32
        for key in keys: user32.keybd_event(key, 0, 0, 0)
        for key in reversed(keys): user32.keybd_event(key, 0, 0x0002, 0)
        return True

    def displays(self):
        try:
            import screen_brightness_control as sbc
            result = []
            for idx, monitor in enumerate(sbc.list_monitors_info()):
                display_id = int(monitor.get("index", idx))
                name = monitor.get("name") or monitor.get("model") or f"Display {idx + 1}"
                serial = monitor.get("serial")
                if serial:
                    name = f"{name} ({serial})"
                result.append((str(name), display_id))
            return result
        except Exception as error:
            self.warn("display_list", f"[WARN] Could not list brightness displays: {error}")
            return []

    @staticmethod
    def get_brightness(display=None):
        try:
            import screen_brightness_control as sbc
            value = sbc.get_brightness(display=display)
            if isinstance(value, (list, tuple)):
                value = value[0] if value else None
            return None if value is None else int(value)
        except Exception:
            return None

    def set_brightness(self, value, display=None):
        try:
            import screen_brightness_control as sbc
            sbc.set_brightness(int(np.clip(value, 0, 100)), display=display)
            return True
        except Exception as error:
            self.warn("brightness", f"[WARN] Could not set brightness: {error}")
            return False


class CornerStatusOverlay:
    """Small, borderless Windows-style status indicator in the screen corner."""

    def __init__(self):
        import tkinter as tk

        self.tk = tk
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.wm_attributes("-topmost", True)
        self.root.focusmodel("passive")
        self.root.configure(bg="#111827")
        try:
            self.root.wm_attributes("-alpha", 0.92)
        except tk.TclError:
            pass

        width, height, margin = 236, 112, 22
        x = max(0, self.root.winfo_screenwidth() - width - margin)
        y = margin
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        panel = tk.Frame(self.root, bg="#111827", padx=14, pady=9,
                         highlightthickness=1, highlightbackground="#344154")
        panel.pack(fill="both", expand=True)
        header = tk.Frame(panel, bg="#111827")
        header.pack(fill="x")
        self.mode_label = tk.Label(header, text="SYSTEM", bg="#111827", fg="#b8c4d6",
                                   font=("Segoe UI", 9, "bold"))
        self.mode_label.pack(side="left")
        self.value_label = tk.Label(header, text="--%", bg="#111827", fg="white",
                                    font=("Segoe UI", 22, "bold"))
        self.value_label.pack(side="right")
        self.bar = tk.Canvas(panel, width=206, height=6, bg="#273345",
                             highlightthickness=0, bd=0)
        self.bar.pack(fill="x", pady=(7, 0))
        self.fill = self.bar.create_rectangle(0, 0, 0, 6, fill="#62a8ff", outline="")
        self.action_label = tk.Label(panel, text="", bg="#111827", fg="#d7e7ff",
                                     font=("Segoe UI", 9, "bold"), anchor="w")
        self.action_label.pack(fill="x", pady=(6, 0))
        self.action_until = 0.0
        self.root.update_idletasks()

        self.last_display = None
        self.last_change = time.monotonic()
        self.visible = False

    def show_action(self, message):
        self.action_label.configure(text=message)
        self.action_until = time.monotonic() + 2.2
        self.last_change = time.monotonic()

    def update_status(self, mode, value):
        if mode not in ("volume", "brightness"):
            if self.visible:
                self.root.withdraw()
                self.visible = False
            self.last_display = None
            self.action_label.configure(text="")
            self.action_until = 0.0
            return

        now = time.monotonic()
        if self.action_until and now >= self.action_until:
            self.action_label.configure(text="")
            self.action_until = 0.0
        display_value = None if value is None else int(np.clip(round(value), 0, 100))
        state = (mode, display_value)
        if state != self.last_display:
            self.last_display = state
            self.last_change = time.monotonic()
            self.mode_label.configure(text="SYSTEM " + mode.upper())
            self.value_label.configure(text="--%" if display_value is None else f"{display_value}%")
            color = "#62a8ff" if mode == "volume" else "#f4b860"
            self.bar.itemconfigure(self.fill, fill=color)
            self.bar.coords(self.fill, 0, 0, 206 * (display_value or 0) / 100, 6)

        if not self.visible:
            self.root.deiconify()
            self.visible = True
        elapsed = time.monotonic() - self.last_change
        # Stay bright while changing, then settle into a faint corner badge.
        alpha = 0.92 if elapsed < 1.2 else max(0.24, 0.92 - (elapsed - 1.2) * 0.85)
        try:
            self.root.wm_attributes("-alpha", alpha)
            self.root.update_idletasks()
            self.root.update()
        except self.tk.TclError:
            self.visible = False

    def close(self):
        try:
            self.root.destroy()
        except self.tk.TclError:
            pass


class TrayController:
    """pystray menu; callbacks only set requests for the camera-loop thread."""

    def __init__(self, app):
        import pystray
        from PIL import Image, ImageDraw

        self.app = app
        image = Image.new("RGBA", (64, 64), (17, 24, 39, 255))
        draw = ImageDraw.Draw(image)
        draw.ellipse((9, 9, 55, 55), outline=(98, 168, 255, 255), width=4)
        draw.ellipse((25, 25, 39, 39), fill=(244, 184, 96, 255))
        self.pystray = pystray
        self.image = image
        self.icon = pystray.Icon(
            "GestureControls", image, "Gesture Volume and Brightness",
            menu=self.build_menu(),
        )

    def build_menu(self):
        pystray = self.pystray
        def profile_action(profile):
            return lambda icon, item: self.app.request_profile(profile)
        profiles = pystray.Menu(*[
            pystray.MenuItem(name, profile_action(name))
            for name in sorted(self.app.settings["profiles"])
        ])
        return pystray.Menu(
                pystray.MenuItem("Volume mode", lambda icon, item: self.app.request_mode("volume")),
                pystray.MenuItem("Brightness mode", lambda icon, item: self.app.request_mode("brightness")),
                pystray.MenuItem("Idle", lambda icon, item: self.app.request_mode("idle")),
                pystray.MenuItem("Profiles", profiles),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Show camera window", lambda icon, item: self.app.request_camera(True)),
                pystray.MenuItem("Hide camera window", lambda icon, item: self.app.request_camera(False)),
                pystray.MenuItem("Settings", lambda icon, item: self.app.request_settings()),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", lambda icon, item: self.app.request_quit()),
        )

    def refresh_menu(self):
        self.icon.menu = self.build_menu()
        self.icon.update_menu()

    def start(self):
        self.icon.run_detached()

    def stop(self):
        try:
            self.icon.stop()
        except Exception:
            pass


class GestureController:
    DEFAULTS = {
        "output_limits": {
            "volume": {"min": 5, "max": 90},
            "brightness": {"min": 10, "max": 100},
        },
        "brightness_display": None,
        "brightness_step_percent": 4,
        "right_pinch_range": None,
        "active_profile": "Default",
        "profiles": {"Default": {"fist": "mute", "pinky_pinch": "play_pause", "middle_pinch": "next"}},
    }
    CALIBRATION_SECONDS = 3.5
    PINCH_PINKY_ON = 0.62
    PINCH_MIDDLE_ON = 0.58
    PINCH_OFF = 0.68
    PINCH_SEPARATION = 0.05

    def __init__(self, width=640, height=480):
        self.width, self.height = width, height
        self.detector = HandDetector()
        self.system = SystemControl()
        self.displays = self.system.displays()
        self.config_path = self.config_file_path()
        self.settings = json.loads(json.dumps(self.DEFAULTS))
        self.load_settings()
        self.action_map = self.settings["profiles"][self.settings["active_profile"]].copy()
        self.mode = "idle"
        self.calibrated = self.valid_range(self.settings.get("right_pinch_range"))
        self.calibration_started = None
        self.calibration_samples = []
        self.ratios = deque(maxlen=5)
        self.filtered_value = None
        self.ema_alpha = 0.28
        self.deadzone_min = 1.0
        self.deadzone_gain = 2.0
        self.deadzone_max = 5.0
        self.last_written = None
        self.last_write_at = 0.0
        self.right_palm_sizes = deque(maxlen=7)
        self.right_palm_size_anchor = None
        self.right_scale_locked = False
        self.right_missing_since = None
        self.minimum_control_palm_size = 45.0
        self.maximum_palm_scale_change = 0.10
        self.left_distances = {"middle": deque(maxlen=3), "pinky": deque(maxlen=3)}
        self.left_ratio_status = "L pinch: --"
        self.left_gesture = None
        self.left_started_at = 0.0
        self.left_fired = False
        self.left_action_at = 0.0
        self.left_neutral_since = None
        self.left_missing_since = None
        self.muted = self.system.is_muted()
        self.media_is_playing = True  # Local display assumes playback is active at startup.
        self.current_value = None
        self.tray = None
        self.tray_mode_request = None
        self.tray_profile_request = None
        self.tray_menu_refresh_requested = False
        self.settings_requested = False
        self.quit_requested = False
        self.camera_visibility_request = None

    @staticmethod
    def config_file_path():
        if not getattr(sys, "frozen", False):
            return Path(__file__).with_name("gesture_config.json")
        if os.name == "nt":
            base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
        elif platform.system() == "Darwin":
            base = Path.home() / "Library" / "Application Support"
        else:
            base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
        config = base / "GestureControls" / "gesture_config.json"
        config.parent.mkdir(parents=True, exist_ok=True)
        bundled = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "gesture_config.json"
        if not config.exists() and bundled.exists():
            config.write_bytes(bundled.read_bytes())
        return config

    def request_mode(self, mode):
        if mode in ("volume", "brightness", "idle"):
            self.tray_mode_request = mode

    def request_profile(self, name):
        if name in self.settings["profiles"]:
            self.tray_profile_request = name

    def request_camera(self, visible):
        self.camera_visibility_request = bool(visible)

    def request_settings(self):
        self.settings_requested = True

    def request_quit(self):
        self.quit_requested = True

    def register_global_hotkeys(self):
        if platform.system() != "Windows":
            return
        from ctypes import wintypes
        self._hotkey_user32 = ctypes.windll.user32
        self._hotkey_user32.RegisterHotKey.argtypes = (
            wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT)
        self._hotkey_user32.RegisterHotKey.restype = wintypes.BOOL
        self._hotkey_user32.PeekMessageW.argtypes = (
            ctypes.POINTER(wintypes.MSG), wintypes.HWND,
            wintypes.UINT, wintypes.UINT, wintypes.UINT)
        self._hotkey_user32.PeekMessageW.restype = wintypes.BOOL
        self._hotkey_user32.UnregisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int)
        self._hotkey_user32.UnregisterHotKey.restype = wintypes.BOOL
        self._hotkey_ids = {1: "volume", 2: "brightness", 3: "idle", 4: "quit"}
        self._registered_hotkey_ids = set()
        modifiers = 0x0002 | 0x0001  # MOD_CONTROL | MOD_ALT
        for hotkey_id, key in enumerate("VBIQ", 1):
            if self._hotkey_user32.RegisterHotKey(None, hotkey_id, modifiers, ord(key)):
                self._registered_hotkey_ids.add(hotkey_id)
                print(f"[INFO] Global Ctrl+Alt+{key} registered.")
            else:
                error = ctypes.get_last_error()
                print(f"[WARN] Global Ctrl+Alt+{key} registration failed (Windows error {error}; shortcut may be in use).")

    def poll_global_hotkeys(self):
        if not hasattr(self, "_hotkey_user32"):
            return
        from ctypes import wintypes
        message = wintypes.MSG()
        while self._hotkey_user32.PeekMessageW(ctypes.byref(message), None, 0x0312, 0x0312, 0x0001):
            request = self._hotkey_ids.get(int(message.wParam))
            if request in ("volume", "brightness", "idle"):
                print(f"[INFO] Global shortcut activated: Ctrl+Alt+{request[0].upper()}.")
                self.tray_mode_request = request
            elif request == "quit":
                print("[INFO] Global shortcut activated: Ctrl+Alt+Q.")
                self.quit_requested = True

    def unregister_global_hotkeys(self):
        if hasattr(self, "_hotkey_user32"):
            for hotkey_id in self._registered_hotkey_ids:
                self._hotkey_user32.UnregisterHotKey(None, hotkey_id)
            del self._hotkey_user32

    def set_mode(self, mode):
        self.mode = mode
        self.current_value = None
        self.ratios.clear()
        self.filtered_value = None
        self.last_written = None
        self.last_write_at = 0.0
        if mode == "idle":
            self.left_gesture = None
            self.left_fired = False
        elif not self.calibrated:
            self.begin_calibration()

    @staticmethod
    def valid_range(value):
        if not isinstance(value, dict):
            return False
        try:
            low, high = float(value["min_ratio"]), float(value["max_ratio"])
            return math.isfinite(low) and math.isfinite(high) and 0 <= low < high <= 2 and high - low >= 0.25
        except (KeyError, TypeError, ValueError):
            return False

    def load_settings(self):
        if not self.config_path.exists():
            self.save_settings()
            return
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            limits = data.get("output_limits", {})
            for mode in ("volume", "brightness"):
                saved = limits.get(mode, {})
                low = int(np.clip(int(saved.get("min", self.settings["output_limits"][mode]["min"])), 0, 99))
                high = int(np.clip(int(saved.get("max", self.settings["output_limits"][mode]["max"])), 1, 100))
                if low < high:
                    self.settings["output_limits"][mode] = {"min": low, "max": high}
            self.settings["brightness_step_percent"] = int(np.clip(
                int(data.get("brightness_step_percent", 4)), 1, 10))
            display = data.get("brightness_display")
            self.settings["brightness_display"] = None if display is None else max(0, int(display))
            pinch = data.get("right_pinch_range")
            if not pinch and isinstance(data.get("pinch_ranges"), dict):
                pinch = data["pinch_ranges"].get("right")
            if self.valid_range(pinch):
                self.settings["right_pinch_range"] = {
                    "min_ratio": float(pinch["min_ratio"]),
                    "max_ratio": float(pinch["max_ratio"]),
                }
            for name, mapping in data.get("profiles", {}).items():
                if isinstance(name, str) and isinstance(mapping, dict):
                    self.settings["profiles"][name] = {
                        key: mapping.get(key, "none")
                        for key in ("fist", "pinky_pinch", "middle_pinch")
                    }
            active = data.get("active_profile", "Default")
            if active in self.settings["profiles"]:
                self.settings["active_profile"] = active
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            print(f"[WARN] Could not read settings: {error}")

    def save_settings(self):
        try:
            self.config_path.write_text(json.dumps(self.settings, indent=2) + "\n", encoding="utf-8")
        except OSError as error:
            print(f"[WARN] Could not save settings: {error}")

    def select_profile(self, name):
        if name in self.settings["profiles"]:
            self.settings["active_profile"] = name
            self.action_map = self.settings["profiles"][name].copy()

    def clear_right_calibration(self):
        self.settings["right_pinch_range"] = None
        self.calibrated = False
        self.calibration_started = None
        self.calibration_samples.clear()
        self.ratios.clear()
        self.save_settings()

    def draw_text(self, frame, text, point, color=(245, 245, 245), scale=0.52):
        cv2.putText(frame, text, point, cv2.FONT_HERSHEY_SIMPLEX, scale,
                    (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(frame, text, point, cv2.FONT_HERSHEY_SIMPLEX, scale,
                    color, 1, cv2.LINE_AA)

    def target_from_ratio(self, ratio):
        limits = self.settings["output_limits"][self.mode]
        calibration = self.settings["right_pinch_range"]
        low, high = calibration["min_ratio"], calibration["max_ratio"]
        amount = float(np.clip((ratio - low) / (high - low), 0.0, 1.0))
        return round(limits["min"] + amount * (limits["max"] - limits["min"]))

    def dynamic_deadzone(self, samples):
        """Scale the dead-zone with recent pinch jitter, in output percentage points."""
        values = np.asarray(samples, dtype=float)
        if values.size < 2:
            return self.deadzone_min
        calibration = self.settings["right_pinch_range"]
        ratio_span = max(calibration["max_ratio"] - calibration["min_ratio"], 0.1)
        limits = self.settings["output_limits"][self.mode]
        output_span = limits["max"] - limits["min"]
        median = float(np.median(values))
        jitter = float(np.median(np.abs(values - median)))
        jitter_points = jitter * output_span / ratio_span
        return float(np.clip(
            self.deadzone_min + self.deadzone_gain * jitter_points,
            self.deadzone_min,
            self.deadzone_max,
        ))

    def begin_calibration(self):
        self.calibrated = False
        self.calibration_started = None
        self.calibration_samples = []
        self.ratios.clear()
        self.right_palm_sizes.clear()
        self.right_palm_size_anchor = None
        self.right_scale_locked = False

    def update_calibration(self, frame, right_hand, now):
        if right_hand is None:
            self.calibration_started = None
            self.calibration_samples = []
            self.draw_text(frame, "CALIBRATION: show your right hand", (18, 110), (0, 220, 255), 0.46)
            self.draw_text(frame, "Move from closed pinch to wide spread", (18, 136), (0, 220, 255), 0.44)
            return
        self.calibration_samples.append(HandDetector.pinch_ratio(right_hand))
        if self.calibration_started is None:
            self.calibration_started = now
        remaining = max(0.0, self.CALIBRATION_SECONDS - (now - self.calibration_started))
        self.draw_text(frame, f"CALIBRATING RIGHT HAND: {remaining:.1f}s", (18, 110), (0, 220, 255), 0.46)
        self.draw_text(frame, "Keep moving between closed pinch and wide spread", (18, 136), (0, 220, 255), 0.44)
        if remaining > 0:
            return
        if len(self.calibration_samples) >= 25:
            low, high = np.percentile(self.calibration_samples, [3, 97])
            if high - low >= 0.25:
                self.settings["right_pinch_range"] = {
                    "min_ratio": float(max(0.02, low)),
                    "max_ratio": float(min(2.0, high)),
                }
                self.calibrated = True
                self.save_settings()
                self.ratios.clear()
                self.filtered_value = None
                self.draw_text(frame, "Right-hand calibration saved", (18, 140), (0, 255, 0))
                print("Saved right-hand pinch calibration.")
                return
        self.calibration_started = None
        self.calibration_samples = []
        self.draw_text(frame, "Calibration needs a wider pinch-to-open movement; retry", (18, 140), (0, 180, 255), 0.44)

    def output_current(self):
        if self.mode == "volume":
            return self.system.get_volume()
        if self.mode == "brightness":
            return self.system.get_brightness(self.settings.get("brightness_display"))
        return None

    def apply_right_hand(self, frame, points, now):
        if self.mode == "idle" or not self.calibrated:
            self.ratios.clear()
            self.filtered_value = None
            self.right_palm_sizes.clear()
            self.right_palm_size_anchor = None
            self.right_scale_locked = False
            self.right_missing_since = None
            return None

        if points is None:
            self.ratios.clear()
            if self.right_missing_since is None:
                self.right_missing_since = now
            if now - self.right_missing_since >= 0.35:
                self.filtered_value = None
                self.right_palm_sizes.clear()
                self.right_palm_size_anchor = None
                self.right_scale_locked = False
            return None

        palm_size = HandDetector.palm_width(points)
        if palm_size < self.minimum_control_palm_size:
            self.ratios.clear()
            if self.right_missing_since is None:
                self.right_missing_since = now
            if now - self.right_missing_since >= 0.35:
                self.filtered_value = None
                self.right_palm_sizes.clear()
                self.right_palm_size_anchor = None
                self.right_scale_locked = False
            return None

        self.right_missing_since = None
        if self.right_palm_size_anchor is None:
            self.right_palm_sizes.append(palm_size)
            if len(self.right_palm_sizes) < self.right_palm_sizes.maxlen:
                return None
            self.right_palm_size_anchor = float(np.median(self.right_palm_sizes))
            self.right_palm_sizes.clear()
            self.ratios.clear()
            self.filtered_value = None
            return None

        self.right_palm_sizes.append(palm_size)
        scale_change = abs(palm_size - self.right_palm_size_anchor) / self.right_palm_size_anchor
        recent_sizes = list(self.right_palm_sizes)
        shrinking = False
        if len(recent_sizes) >= 4:
            earlier = float(np.median(recent_sizes[-4:-2]))
            later = float(np.median(recent_sizes[-2:]))
            shrinking = later < earlier * 0.96
        if scale_change > self.maximum_palm_scale_change or shrinking:
            # A hand shrinking toward the camera edge is usually being withdrawn,
            # not deliberately pinched. Hold the last output until it is removed.
            self.right_scale_locked = True
            self.ratios.clear()
        if self.right_scale_locked:
            return None

        ratio = HandDetector.pinch_ratio(points)
        self.ratios.append(ratio)
        stable_ratio = float(np.median(self.ratios))
        target = self.target_from_ratio(stable_ratio)
        if self.filtered_value is None:
            self.filtered_value = float(target)
        else:
            # Ignore small output changes caused by hand tremor. The dead-zone
            # grows with recent median absolute pinch jitter, then EMA smooths
            # deliberate changes without abrupt jumps.
            deadzone = self.dynamic_deadzone(self.ratios)
            delta = target - self.filtered_value
            if abs(delta) > deadzone:
                self.filtered_value += self.ema_alpha * delta
        target = int(round(self.filtered_value))
        limits = self.settings["output_limits"][self.mode]
        target = int(np.clip(target, limits["min"], limits["max"]))
        if now - self.last_write_at < (0.10 if self.mode == "volume" else 0.16):
            return target
        if self.last_written is not None and abs(target - self.last_written) < 1:
            return target
        if self.mode == "volume":
            success = self.system.set_volume(target)
        else:
            current = self.current_value
            if current is None:
                current = self.output_current()
            if current is not None and abs(target - current) > self.settings["brightness_step_percent"]:
                target = current + int(math.copysign(self.settings["brightness_step_percent"], target - current))
            success = self.system.set_brightness(target, self.settings.get("brightness_display"))
        if success:
            self.last_written = target
            self.current_value = target
            self.last_write_at = now
        return target

    def classify_left(self, points):
        self.left_distances["middle"].append(HandDetector.pinch_ratio(points, 12))
        self.left_distances["pinky"].append(HandDetector.pinch_ratio(points, 20))
        middle_ratio = float(np.median(self.left_distances["middle"]))
        pinky_ratio = float(np.median(self.left_distances["pinky"]))
        gap = abs(middle_ratio - pinky_ratio)
        self.left_ratio_status = f"LEFT TM {middle_ratio:.2f} | TP {pinky_ratio:.2f}"

        # Middle pinch changes tracks; pinky pinch toggles play/pause.
        # Compare both distances so one held pose cannot trigger both actions.
        pinch = None
        if (self.left_gesture == "middle_pinch" and middle_ratio < self.PINCH_OFF
                and middle_ratio + 0.02 < pinky_ratio):
            pinch = "middle_pinch"
        elif (self.left_gesture == "pinky_pinch" and pinky_ratio < self.PINCH_OFF
                and pinky_ratio + 0.02 < middle_ratio):
            pinch = "pinky_pinch"
        elif (middle_ratio < self.PINCH_MIDDLE_ON
                and middle_ratio + self.PINCH_SEPARATION < pinky_ratio):
            pinch = "middle_pinch"
        elif (pinky_ratio < self.PINCH_PINKY_ON
                and pinky_ratio + self.PINCH_SEPARATION < middle_ratio):
            pinch = "pinky_pinch"

        if HandDetector.is_fist(points):
            self.left_distances["middle"].clear()
            self.left_distances["pinky"].clear()
            if not (pinch and min(middle_ratio, pinky_ratio) < 0.26 and gap > 0.10):
                self.left_ratio_status = "LEFT: FIST"
                return "fist"
        return pinch

    def handle_left_hand(self, points, now):
        if self.mode == "idle":
            self.left_gesture = None
            self.left_fired = False
            self.left_missing_since = None
            self.left_neutral_since = None
            self.left_distances["middle"].clear()
            self.left_distances["pinky"].clear()
            self.left_ratio_status = "LEFT: IDLE"
            return ""
        if points is None:
            self.left_ratio_status = "LEFT: NOT SEEN"
            if self.left_missing_since is None:
                self.left_missing_since = now
            # A single missed camera frame must not re-arm a held gesture.
            if now - self.left_missing_since >= 0.5:
                self.left_gesture = None
                self.left_fired = False
                self.left_neutral_since = None
                self.left_distances["pinky"].clear()
                self.left_distances["middle"].clear()
            return ""

        self.left_missing_since = None
        gesture = self.classify_left(points)
        if gesture is None:
            if self.left_gesture is not None:
                if self.left_neutral_since is None:
                    self.left_neutral_since = now
                elif now - self.left_neutral_since >= 0.16:
                    self.left_gesture = None
                    self.left_fired = False
                    self.left_neutral_since = None
                    self.left_distances["pinky"].clear()
                    self.left_distances["middle"].clear()
            return ""

        self.left_neutral_since = None
        if gesture != self.left_gesture:
            self.left_gesture = gesture
            self.left_started_at = now
            self.left_fired = False
        hold_time = 0.32 if gesture == "fist" else 0.20
        if self.left_fired or now - self.left_started_at < hold_time:
            return {"fist": "Hold fist", "middle_pinch": "Pinch middle", "pinky_pinch": "Pinch pinky"}[gesture]
        self.left_fired = True
        self.left_action_at = now
        if gesture == "fist":
            action = self.action_map.get("fist", "mute")
            if action == "none": return ""
            if action != "mute": return self.perform_mapped_action(action)
            self.muted = self.system.toggle_mute()
            if self.muted is None:
                return "MUTE N/A"
            return "MUTE ON" if self.muted else "MUTE OFF"
        if gesture == "pinky_pinch":
            return self.perform_mapped_action(self.action_map.get("pinky_pinch", "play_pause"))
        if gesture == "middle_pinch":
            return self.perform_mapped_action(self.action_map.get("middle_pinch", "next"))
        return ""

    def perform_mapped_action(self, action):
        if action == "none": return ""
        if action.startswith("shortcut:"):
            shortcut = action.partition(":")[2]
            return f"SHORTCUT {shortcut.upper()}" if self.system.keyboard_shortcut(shortcut) else "SHORTCUT N/A"
        if action == "mute":
            self.muted = self.system.toggle_mute()
            return "MUTE N/A" if self.muted is None else ("MUTE ON" if self.muted else "MUTE OFF")
        if action not in ("play_pause", "next", "previous"):
            return ""
        if not self.system.media_key(action): return "MEDIA N/A"
        if action == "play_pause":
            self.media_is_playing = not self.media_is_playing
            return "MUSIC PLAYING" if self.media_is_playing else "MUSIC PAUSED"
        return "NEXT TRACK" if action == "next" else "PREVIOUS TRACK"

    def show_settings(self):
        import tkinter as tk
        from tkinter import messagebox, ttk

        root = tk.Tk()
        root.title("Gesture controls")
        root.resizable(False, False)
        panel = ttk.Frame(root, padding=14)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text="Volume and brightness gestures", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(panel, text="Right hand: level control. Left hand: mute and media gestures.", wraplength=470).pack(anchor="w", pady=(4, 10))

        variables = {}
        limits_box = ttk.LabelFrame(panel, text="Output limits (%)", padding=8)
        limits_box.pack(fill="x", pady=4)
        ttk.Label(limits_box, text="Mode").grid(row=0, column=0, sticky="w")
        ttk.Label(limits_box, text="Minimum").grid(row=0, column=1, padx=8)
        ttk.Label(limits_box, text="Maximum").grid(row=0, column=2, padx=8)
        for row, mode in enumerate(("volume", "brightness"), 1):
            ttk.Label(limits_box, text=mode.title()).grid(row=row, column=0, sticky="w", pady=3)
            for col, bound in ((1, "min"), (2, "max")):
                var = tk.StringVar(value=str(self.settings["output_limits"][mode][bound]))
                ttk.Spinbox(limits_box, from_=0, to=100, textvariable=var, width=8).grid(row=row, column=col, padx=8)
                variables[f"{mode}_{bound}"] = var

        monitor_box = ttk.LabelFrame(panel, text="Brightness target and smoothing", padding=8)
        monitor_box.pack(fill="x", pady=4)
        options = {"All supported displays": None}
        options.update({name: index for name, index in self.displays})
        selected_name = next((name for name, index in options.items()
                              if index == self.settings.get("brightness_display")), "All supported displays")
        monitor_var = tk.StringVar(value=selected_name)
        ttk.Label(monitor_box, text="Display:").grid(row=0, column=0, sticky="w")
        ttk.Combobox(monitor_box, textvariable=monitor_var, values=list(options), state="readonly", width=35).grid(row=0, column=1, padx=6)
        ttk.Label(monitor_box, text="Brightness step %:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        step_var = tk.StringVar(value=str(self.settings["brightness_step_percent"]))
        ttk.Spinbox(monitor_box, from_=1, to=10, textvariable=step_var, width=6).grid(row=1, column=1, sticky="w", padx=6, pady=(8, 0))

        profile_box = ttk.LabelFrame(panel, text="Gesture profile", padding=8)
        profile_box.pack(fill="x", pady=4)
        profile_var = tk.StringVar(value=self.settings["active_profile"])
        ttk.Label(profile_box, text="Profile:").grid(row=0, column=0, sticky="w")
        profile_combo = ttk.Combobox(profile_box, textvariable=profile_var,
            values=sorted(self.settings["profiles"]), width=20)
        profile_combo.grid(row=0, column=1, sticky="w", padx=5)
        actions = ("none", "mute", "play_pause", "next", "previous", "shortcut:ctrl+shift+m")
        action_vars = {}
        gesture_names = {"fist": "Fist", "pinky_pinch": "Thumb-pinky pinch", "middle_pinch": "Thumb-middle pinch"}
        for row, gesture in enumerate(("fist", "pinky_pinch", "middle_pinch"), 1):
            ttk.Label(profile_box, text=gesture_names[gesture]).grid(row=row, column=0, sticky="w", pady=2)
            var = tk.StringVar(value=self.action_map.get(gesture, "none"))
            ttk.Combobox(profile_box, textvariable=var, values=actions, state="normal", width=24).grid(row=row, column=1, sticky="w", padx=5)
            action_vars[gesture] = var

        def load_profile(_event=None):
            name = profile_var.get()
            mapping = self.settings["profiles"].get(name)
            if mapping:
                for gesture, var in action_vars.items(): var.set(mapping.get(gesture, "none"))
        profile_combo.bind("<<ComboboxSelected>>", load_profile)
        ttk.Label(profile_box, text="For shortcuts, enter shortcut:ctrl+shift+m (Windows)", foreground="#555").grid(row=4, column=0, columnspan=2, sticky="w", pady=(5, 0))
        test_gesture_var = tk.StringVar(value="fist")
        ttk.Label(profile_box, text="Test gesture:").grid(row=5, column=0, sticky="w", pady=(5, 0))
        ttk.Combobox(profile_box, textvariable=test_gesture_var,
            values=("fist", "pinky_pinch", "middle_pinch"), state="readonly", width=22).grid(row=5, column=1, sticky="w", padx=5, pady=(5, 0))
        test_status = tk.StringVar(value="")
        ttk.Label(profile_box, textvariable=test_status).grid(row=7, column=0, columnspan=2, sticky="w")

        def test_shortcut():
            gesture_key = test_gesture_var.get()
            action = action_vars[gesture_key].get().strip()
            if not action.startswith("shortcut:") or not action.partition(":")[2]:
                test_status.set("Choose a shortcut action first.")
                return
            shortcut = action.partition(":")[2]
            test_status.set("Shortcut will send in 3 seconds; focus the target app now.")
            def send_test():
                ok = self.system.keyboard_shortcut(shortcut)
                test_status.set("Shortcut sent." if ok else "Shortcut invalid or unavailable.")
            root.after(3000, send_test)
        ttk.Button(profile_box, text="Test shortcut", command=test_shortcut).grid(row=6, column=0, columnspan=2, sticky="w", pady=(4, 0))

        calibration_text = "Saved" if self.calibrated else "Needed on first active mode"
        calibration_var = tk.StringVar(value=f"Right-hand pinch calibration: {calibration_text}")
        ttk.Label(panel, textvariable=calibration_var).pack(anchor="w", pady=(8, 2))

        def reset_calibration():
            self.clear_right_calibration()
            calibration_var.set("Right-hand pinch calibration: needed on next active mode")

        ttk.Button(panel, text="Reset right-hand calibration", command=reset_calibration).pack(anchor="w", pady=(0, 8))
        ttk.Label(panel, text="Keys: v volume | b brightness | i idle | q quit", wraplength=470).pack(anchor="w")
        ttk.Label(panel, text="Left hand: fist toggles mute; pinky pinch toggles play/pause; each middle pinch advances to the next track; release and pinch again for another.", wraplength=470).pack(anchor="w", pady=(3, 4))

        def save():
            try:
                new_limits = {}
                for mode in ("volume", "brightness"):
                    low = int(variables[f"{mode}_min"].get())
                    high = int(variables[f"{mode}_max"].get())
                    if not 0 <= low < high <= 100:
                        raise ValueError(f"{mode.title()} minimum must be below maximum.")
                    new_limits[mode] = {"min": low, "max": high}
                step = int(step_var.get())
                if monitor_var.get() not in options:
                    raise ValueError("Select a supported display.")
            except (ValueError, tk.TclError) as error:
                messagebox.showerror("Invalid settings", str(error), parent=root)
                return False
            self.settings["output_limits"] = new_limits
            self.settings["brightness_step_percent"] = int(np.clip(step, 1, 10))
            self.settings["brightness_display"] = options[monitor_var.get()]
            profile = profile_var.get().strip()[:32] or "Default"
            mapping = {gesture: var.get() for gesture, var in action_vars.items()}
            self.settings["profiles"][profile] = mapping
            self.settings["active_profile"] = profile
            self.select_profile(profile)
            profile_combo.configure(values=sorted(self.settings["profiles"]))
            self.tray_menu_refresh_requested = True
            self.save_settings()
            return True

        buttons = ttk.Frame(panel)
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text="Save and start", command=lambda: (save() and root.destroy())).pack(side="right")
        ttk.Button(buttons, text="Save", command=save).pack(side="left")
        root.mainloop()

    def run(self):
        self.show_settings()
        try:
            self.tray = TrayController(self)
            self.tray.start()
        except Exception as error:
            self.tray = None
            print(f"[WARN] System tray unavailable: {error}")
        camera = cv2.VideoCapture(0, cv2.CAP_DSHOW) if platform.system() == "Windows" else cv2.VideoCapture(0)
        if not camera.isOpened():
            camera.release()
            camera = cv2.VideoCapture(0)
        if not camera.isOpened():
            print("[ERROR] Could not open the camera.")
            if self.tray:
                self.tray.stop()
            self.detector.close()
            return
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        print("Keys: v=volume | b=brightness | i=idle | q=quit")
        self.register_global_hotkeys()
        if platform.system() == "Windows":
            print("Global shortcuts: Ctrl+Alt+V=volume | Ctrl+Alt+B=brightness | Ctrl+Alt+I=idle | Ctrl+Alt+Q=quit")
        try:
            overlay = CornerStatusOverlay()
        except Exception as error:
            overlay = None
            print(f"[WARN] Corner status overlay unavailable: {error}")
        last_action_text, last_action_until = "", 0.0
        status_mute = self.system.is_muted()
        last_status_poll = 0.0
        last_overlay_update = 0.0
        camera_window_name = "Gesture Volume and Brightness"
        camera_visible = True
        try:
            while True:
                self.poll_global_hotkeys()
                ok, frame = camera.read()
                if not ok:
                    print("[ERROR] Camera frame could not be read.")
                    break
                frame = cv2.flip(frame, 1)
                now = time.monotonic()
                hands = self.detector.process(frame)
                right_hand, left_hand = hands.get("right"), hands.get("left")

                if self.mode != "idle" and not self.calibrated:
                    self.update_calibration(frame, right_hand, now)
                else:
                    self.apply_right_hand(frame, right_hand, now)
                # The left-hand controls do not depend on right-hand calibration.
                action = self.handle_left_hand(left_hand, now)
                if action and not action.startswith("Hold "):
                    last_action_text, last_action_until = action, now + 1.0
                    if overlay:
                        overlay.show_action(action)

                if self.mode in ("volume", "brightness") and now - last_status_poll >= 0.25:
                    if self.mode == "volume":
                        live_value = self.system.get_volume()
                        status_mute = self.system.is_muted()
                    else:
                        live_value = self.system.get_brightness(self.settings.get("brightness_display"))
                    if live_value is not None:
                        self.current_value = live_value
                    last_status_poll = now

                if self.mode == "volume":
                    shown = "--" if self.current_value is None else f"{self.current_value}%"
                    mute_text = "MUTED" if status_mute else "UNMUTED" if status_mute is not None else "MUTE N/A"
                    line = f"VOLUME {shown}  {mute_text}"
                elif self.mode == "brightness":
                    shown = "--" if self.current_value is None else f"{self.current_value}%"
                    line = f"BRIGHTNESS {shown}"
                else:
                    line = "IDLE — controls paused"

                if overlay and now - last_overlay_update >= 0.10:
                    overlay.update_status(self.mode, self.current_value)
                    last_overlay_update = now

                self.draw_text(frame, f"MODE: {self.mode.upper()}  |  RIGHT: {'OK' if right_hand else 'NOT SEEN'}  LEFT: {'OK' if left_hand else 'NOT SEEN'}", (16, 26), (255, 255, 255), 0.48)
                self.draw_text(frame, line, (16, 54), (255, 210, 80), 0.58)
                if right_hand and self.mode != "idle":
                    if self.right_scale_locked:
                        right_status = "RIGHT MOVING — LEVEL HELD"
                    elif HandDetector.palm_width(right_hand) < self.minimum_control_palm_size:
                        right_status = "RIGHT TOO FAR — LEVEL HELD"
                    elif self.right_palm_size_anchor is None:
                        right_status = "RIGHT: HOLD STEADY"
                    else:
                        ratio = HandDetector.pinch_ratio(right_hand)
                        right_status = f"RIGHT PINCH {ratio:.2f}"
                else:
                    right_status = "RIGHT: NOT SEEN" if self.mode != "idle" else "RIGHT: IDLE"
                if self.mode == "idle":
                    left_status = "LEFT: IDLE"
                elif not left_hand:
                    left_status = "LEFT: NOT SEEN"
                elif not self.calibrated:
                    left_status = "LEFT: WAIT"
                else:
                    left_status = self.left_ratio_status
                self.draw_text(frame, f"{right_status}  |  {left_status}", (16, 82), (220, 220, 220), 0.42)
                if last_action_text and now < last_action_until:
                    self.draw_text(frame, last_action_text, (16, 112), (70, 255, 130), 0.52)
                self.draw_text(frame, "v volume | b brightness | i idle | q quit", (16, frame.shape[0] - 14), (220, 220, 220), 0.43)
                if camera_visible:
                    cv2.imshow(camera_window_name, frame)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q") or self.quit_requested:
                    break

                if self.settings_requested:
                    self.settings_requested = False
                    self.show_settings()
                    self.current_value = None
                    last_status_poll = 0.0
                if self.tray_profile_request is not None:
                    self.select_profile(self.tray_profile_request)
                    self.tray_profile_request = None
                    self.save_settings()
                if self.tray_menu_refresh_requested and self.tray:
                    self.tray.refresh_menu()
                    self.tray_menu_refresh_requested = False
                if self.tray_mode_request is not None:
                    requested_mode = self.tray_mode_request
                    self.tray_mode_request = None
                    self.set_mode(requested_mode)
                    last_status_poll = 0.0
                if key in (ord("v"), ord("b")):
                    self.set_mode("volume" if key == ord("v") else "brightness")
                    last_status_poll = 0.0
                elif key == ord("i"):
                    self.set_mode("idle")

                if self.camera_visibility_request is not None:
                    camera_visible = self.camera_visibility_request
                    self.camera_visibility_request = None
                    try:
                        cv2.setWindowProperty(
                            camera_window_name, cv2.WND_PROP_VISIBLE,
                            1 if camera_visible else 0,
                        )
                    except cv2.error:
                        pass
        finally:
            self.unregister_global_hotkeys()
            if overlay:
                overlay.close()
            camera.release()
            cv2.destroyAllWindows()
            self.detector.close()
            if self.tray:
                self.tray.stop()


if __name__ == "__main__":
    GestureController().run()
