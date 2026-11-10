#FOR WINDOWS INSTALLAATION GUIDE

$ErrorActionPreference = "Stop"

python -m pip install -r requirements.txt
python -m pip install pyinstaller

python -m PyInstaller `
  --noconfirm `
  --clean `
  --windowed `
  --onedir `
  --name GestureControls `
  --collect-all mediapipe `
  --collect-all pystray `
  --collect-all PIL `
  --collect-all screen_brightness_control `
  --collect-all pycaw `
  --collect-all comtypes `
  --add-data "gesture_config.json;." `
  gesture_control.py

Write-Host "Built: dist\GestureControls\GestureControls.exe"
