"""Filesystem locations.

Read-only resources (icons, the hand reference image, bundled models) live
next to the code, or inside the PyInstaller bundle when frozen.

User data (settings, calibration, logs, custom sticker images) must be
writable. An installed copy lives in Program Files, which is not writable,
so the frozen build keeps user data in %APPDATA%\\HandTrack. A source
checkout keeps it next to the repository, as earlier versions did.
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from handtrack import APP_NAME

FROZEN = getattr(sys, "frozen", False)

if FROZEN:
    RESOURCE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    _appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    DATA_DIR = os.path.join(_appdata, APP_NAME)
else:
    RESOURCE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DATA_DIR = RESOURCE_DIR

ASSETS_DIR = os.path.join(RESOURCE_DIR, "assets")
BUNDLED_MODELS_DIR = os.path.join(RESOURCE_DIR, "models")
HAND_REFERENCE_PATH = os.path.join(ASSETS_DIR, "hand_reference.png")
ICON_PATH = os.path.join(ASSETS_DIR, "icon.ico")

MODELS_DIR = os.path.join(DATA_DIR, "models")
IMAGES_DIR = os.path.join(DATA_DIR, "images")
LOGS_DIR = os.path.join(DATA_DIR, "logs")
SCREENSHOT_DIR = os.path.join(DATA_DIR, "screenshots")
SETTINGS_PATH = os.path.join(DATA_DIR, "app_settings.json")
GAZE_CALIB_PATH = os.path.join(DATA_DIR, "gaze_calibration.json")
HAND_CALIB_PATH = os.path.join(DATA_DIR, "hand_calibration.json")
CUSTOM_GESTURES_PATH = os.path.join(DATA_DIR, "custom_gestures.json")


def ensure_dirs():
    for path in (DATA_DIR, MODELS_DIR, IMAGES_DIR, LOGS_DIR, SCREENSHOT_DIR):
        os.makedirs(path, exist_ok=True)


def model_path(filename):
    """Prefer a model shipped with the installer, else the user's download."""
    bundled = os.path.join(BUNDLED_MODELS_DIR, filename)
    if os.path.isfile(bundled) and os.path.getsize(bundled) > 0:
        return bundled
    return os.path.join(MODELS_DIR, filename)


def setup_logging():
    ensure_dirs()
    logger = logging.getLogger("handtrack")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = RotatingFileHandler(
            os.path.join(LOGS_DIR, "handtrack.log"),
            maxBytes=1_000_000,
            backupCount=2,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)s | %(threadName)s | %(message)s"
        ))
        logger.addHandler(handler)
    return logger
