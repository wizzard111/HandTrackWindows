"""System actions bound to custom gestures (keyboard, media keys, programs)."""

import importlib.util
import logging
import os
import shlex
import subprocess
import sys
from datetime import datetime

from handtrack import paths

logger = logging.getLogger("handtrack")

# pyautogui is imported on first use: it pulls in several modules and on
# Linux connects to the X server, which would slow every start.
PYAUTOGUI_AVAILABLE = importlib.util.find_spec("pyautogui") is not None
_pyautogui = None

MEDIA_KEYS = {
    "media_playpause": "playpause",
    "volume_up": "volumeup",
    "volume_down": "volumedown",
    "mute": "volumemute",
}


def _keyboard():
    global _pyautogui
    if _pyautogui is None:
        import pyautogui
        pyautogui.FAILSAFE = True  # slam the cursor into a corner to abort
        pyautogui.PAUSE = 0
        _pyautogui = pyautogui
    return _pyautogui


def take_screenshot():
    """Grab all screens into the screenshots folder. Must run in the GUI thread."""
    from PySide6.QtGui import QGuiApplication, QPainter, QPixmap
    paths.ensure_dirs()
    screens = QGuiApplication.screens()
    geometry = screens[0].virtualGeometry()
    canvas = QPixmap(geometry.size())
    canvas.fill()
    painter = QPainter(canvas)
    for screen in screens:
        g = screen.geometry()
        painter.drawPixmap(g.topLeft() - geometry.topLeft(), screen.grabWindow(0))
    painter.end()
    path = os.path.join(paths.SCREENSHOT_DIR, f"screenshot_{datetime.now():%Y%m%d_%H%M%S}.png")
    canvas.save(path, "PNG")
    return path


def open_path(target):
    if sys.platform == "win32":
        os.startfile(target)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", target])
    else:
        subprocess.Popen(["xdg-open", target])


def run_system_action(action_type, param):
    """Keyboard/program actions; safe to call from a worker thread."""
    try:
        if action_type in MEDIA_KEYS or action_type in ("hotkey", "key"):
            if not PYAUTOGUI_AVAILABLE:
                return
            kb = _keyboard()
            if action_type == "hotkey":
                keys = [k.strip() for k in param.split("+") if k.strip()]
                if keys:
                    kb.hotkey(*keys)
            elif action_type == "key":
                if param:
                    kb.press(param)
            else:
                kb.press(MEDIA_KEYS[action_type])
        elif action_type == "run" and param:
            # No shell: pipes and redirections in the gestures file are never executed.
            args = param if sys.platform == "win32" else shlex.split(param)
            subprocess.Popen(args, shell=False)
        elif action_type == "open" and param:
            open_path(param)
    except Exception:
        logger.exception("Gesture action failed: %s", action_type)
