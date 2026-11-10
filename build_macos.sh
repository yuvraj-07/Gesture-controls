#FOR MAC INSTALLATION GUIDE
#!/bin/sh
set -eu

python3 -m pip install -r requirements.txt
python3 -m pip install pyinstaller

python3 -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --onedir \
  --name GestureControls \
  --collect-all mediapipe \
  --collect-all pystray \
  --collect-all PIL \
  --collect-all screen_brightness_control \
  --add-data "gesture_config.json:." \
  gesture_control.py

printf 'Built app bundle under dist/GestureControls.app (if supported by this PyInstaller version).\n'
