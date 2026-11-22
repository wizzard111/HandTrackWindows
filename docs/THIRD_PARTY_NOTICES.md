# Third-party components

HandTrack's own code is MIT licensed. These components keep their own licenses.

## Bundled with the program

| Component | License | Source |
|---|---|---|
| MediaPipe and the Hand / Face Landmarker models | Apache-2.0 | https://github.com/google-ai-edge/mediapipe |
| Qt for Python (PySide6) | LGPL-3.0 | https://www.qt.io/qt-for-python |
| OpenCV | Apache-2.0 | https://github.com/opencv/opencv-python |
| NumPy | BSD-3-Clause | https://numpy.org |
| PyAutoGUI | BSD-3-Clause | https://github.com/asweigart/pyautogui |
| Lucide icons (`assets/icons`) | ISC | https://lucide.dev |
| Russo One font (`assets/fonts`) | SIL OFL 1.1 | https://fonts.google.com/specimen/Russo+One |
| Python | PSF License | https://www.python.org |
| Windows only: Unity Capture DirectShow filter | MIT | https://github.com/schellingb/UnityCapture |

PySide6 is used as unmodified, dynamically linked libraries; you may replace the
Qt libraries in the installation folder with your own build, as the LGPL allows.

## Installed separately (not distributed by HandTrack)

| Component | Where | License |
|---|---|---|
| uv (fetches Python when installing from source) | all | MIT / Apache-2.0 |
| v4l2loopback kernel module (from your distribution) | Linux | GPL-2.0 |
| OBS Studio, pyvirtualcam (built on your Mac) | macOS | GPL-2.0 |
