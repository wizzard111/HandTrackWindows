"""System actions bound to custom gestures (keyboard, media keys, programs)."""

import logging
import os
import shlex
import subprocess
from datetime import datetime

from handtrack import paths

logger = logging.getLogger("handtrack")

try:
    import pyautogui
    pyautogui.FAILSAFE = True  # slam the cursor into a corner to abort
    pyautogui.PAUSE = 0
    PYAUTOGUI_AVAILABLE = True
except Exception:  # pragma: no cover - headless / Wayland
    pyautogui = None
    PYAUTOGUI_AVAILABLE = False

MEDIA_KEYS = {
    "media_playpause": "playpause",
    "volume_up": "volumeup",
    "volume_down": "volumedown",
    "mute": "volumemute",
}


def take_screenshot():
    from PIL import ImageGrab
    paths.ensure_dirs()
    path = os.path.join(paths.SCREENSHOT_DIR,
                        f"screenshot_{datetime.now():%Y%m%d_%H%M%S}.png")
    ImageGrab.grab(all_screens=True).save(path)
    return path


def open_path(target):
    if os.name == "nt":
        os.startfile(target)
    else:
        subprocess.Popen(["xdg-open", target])


def run_system_action(action_type, param):
    """Run keyboard/program actions. UI toggles are handled by the window."""
    try:
        if action_type in MEDIA_KEYS or action_type in ("hotkey", "key"):
            if not PYAUTOGUI_AVAILABLE:
                return
            if action_type == "hotkey":
                keys = [k.strip() for k in param.split("+") if k.strip()]
                if keys:
                    pyautogui.hotkey(*keys)
            elif action_type == "key":
                if param:
                    pyautogui.press(param)
            else:
                pyautogui.press(MEDIA_KEYS[action_type])
        elif action_type == "run" and param:
            # No shell: pipes and redirections in the gestures file are never executed.
            args = param if os.name == "nt" else shlex.split(param)
            subprocess.Popen(args, shell=False)
        elif action_type == "open" and param:
            open_path(param)
        elif action_type == "screenshot":
            take_screenshot()
    except Exception:
        logger.exception("Gesture action failed: %s", action_type)
