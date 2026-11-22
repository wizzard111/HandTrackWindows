# Third-party components

The Windows installer bundles the following software. Each keeps its own
license; HandTrack's MIT license does not apply to them.

| Component | License | Source |
|---|---|---|
| Unity Capture DirectShow filter (`UnityCaptureFilter32/64.dll`) | MIT | https://github.com/schellingb/UnityCapture |
| MediaPipe and the Hand/Face Landmarker models | Apache-2.0 | https://github.com/google-ai-edge/mediapipe |
| Qt for Python (PySide6) | LGPL-3.0 | https://www.qt.io/qt-for-python |
| OpenCV | Apache-2.0 | https://github.com/opencv/opencv-python |
| NumPy | BSD-3-Clause | https://numpy.org |
| Pillow | MIT-CMU | https://python-pillow.org |
| PyAutoGUI | BSD-3-Clause | https://github.com/asweigart/pyautogui |
| Python | PSF License | https://www.python.org |

PySide6 is used as dynamically linked, unmodified libraries; you may replace
the Qt DLLs in the installation folder with your own build, as the LGPL allows.
