"""Render docs/screenshots (live, gestures, effects) with a synthetic camera frame.

Run after changing the design:  PYTHONPATH=src python packaging/make_screenshots.py [OUT_DIR]
Uses a throwaway data folder, so no personal settings or gestures end up in the images.
"""
import os
import sys
import tempfile

tmp = tempfile.mkdtemp(prefix="ht-shots-")
os.environ["APPDATA"] = tmp
os.environ["XDG_CONFIG_HOME"] = tmp

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from handtrack.config import Settings  # noqa: E402
from handtrack.ui import theme  # noqa: E402
from handtrack.vision import render  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs", "screenshots")
extra = sys.argv[2:]  # e.g. "settings" to also save settings.png (layout check)
app = QApplication(sys.argv[:1])
app.setStyle("Fusion")
theme.set_dark(True)
theme.load_fonts()
app.setStyleSheet(theme.stylesheet())

from handtrack.engine import Engine  # noqa: E402
from handtrack.ui.main_window import MainWindow  # noqa: E402

settings = Settings(hide_face=True, draw_enabled=True, afk_enabled=True, gaze=False,
                    resolution="1280x720", vcam=False, dark_mode=True)
engine = Engine(settings)
win = MainWindow(settings, engine)
win.resize(1360, 840)
win.show()

# Synthetic 1280x720 frame: dark diagonal gradient, a drawn stroke, the face mask.
w, h = 1280, 720
yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
t = (xx / w + yy / h) / 2
frame = np.zeros((h, w, 3), np.uint8)
frame[..., 0] = (40 + 60 * t).astype(np.uint8)        # B
frame[..., 1] = (22 + 10 * (1 - t)).astype(np.uint8)  # G
frame[..., 2] = (70 - 30 * t).astype(np.uint8)        # R
xs = np.arange(230, 560)
ys = (380 - 90 * np.sin((xs - 230) / 330 * 2 * np.pi)).astype(np.int32)
cv2.polylines(frame, [np.stack([xs, ys], 1).astype(np.int32)], False, (34, 13, 154), 6, cv2.LINE_AA)
render.draw_privacy_mask(frame, (520, 120, 780, 420))
render.draw_corner_counter(frame, "1")

tr = win.tr
win._camera_state = "live"
win._status_text = tr("status_running", w=w, h=h, note="")
win._refresh_all()
win.camera.preview.set_frame(frame)
win.camera.preview.set_fps(30.0)
win._on_stats({"fps": 30.0, "gesture": ("gesture_no_hand", {})})


def settle(seconds=0.2):
    import time
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def shot(index, name):
    win.nav.set_current(index, animate=False)
    win._on_nav(index)          # the real click path, with its fade
    settle(1.2)
    win.grab().save(os.path.join(out_dir, name))
    print("saved", name)


settle()
shot(0, "live.png")
shot(2, "gestures.png")
shot(1, "effects.png")
if "settings" in extra:
    shot(4, "settings.png")
