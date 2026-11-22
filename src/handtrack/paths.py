"""Filesystem locations.

Read-only resources (icons, fonts, the hand outline, bundled models) live in
the package, or inside the PyInstaller bundle when frozen.

User data (settings, calibration, logs, sticker images) goes to the usual
per-user folder of each OS:

* Windows: %APPDATA%\\HandTrack
* macOS:   ~/Library/Application Support/HandTrack
* Linux:   $XDG_CONFIG_HOME/handtrack (~/.config/handtrack)

HANDTRACK_DATA_DIR overrides it (portable use, tests).
"""

import logging
import os
import shutil
import sys
from logging.handlers import RotatingFileHandler

from handtrack import APP_NAME

FROZEN = getattr(sys, "frozen", False)
IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
if FROZEN:
    RESOURCE_DIR = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)), "handtrack")
    BUNDLE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
else:
    RESOURCE_DIR = PACKAGE_DIR
    BUNDLE_DIR = os.path.dirname(os.path.dirname(PACKAGE_DIR))  # repository root
# Earlier versions kept user data next to main.py, i.e. in the repository root.
LEGACY_DATA_DIR = None if FROZEN else BUNDLE_DIR


def _default_data_dir():
    if os.environ.get("HANDTRACK_DATA_DIR"):
        return os.environ["HANDTRACK_DATA_DIR"]
    home = os.path.expanduser("~")
    if IS_WINDOWS:
        return os.path.join(os.environ.get("APPDATA") or home, APP_NAME)
    if IS_MAC:
        return os.path.join(home, "Library", "Application Support", APP_NAME)
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config"), "handtrack")


DATA_DIR = _default_data_dir()

ASSETS_DIR = os.path.join(RESOURCE_DIR, "assets")
ICONS_DIR = os.path.join(ASSETS_DIR, "icons")
FONTS_DIR = os.path.join(ASSETS_DIR, "fonts")
HAND_REFERENCE_PATH = os.path.join(ASSETS_DIR, "hand_reference.png")
ICON_PATH = os.path.join(ASSETS_DIR, "icon.ico" if IS_WINDOWS else "icon.png")
LOGO_PATH = os.path.join(ASSETS_DIR, "icon.png")
BUNDLED_MODELS_DIR = os.path.join(BUNDLE_DIR, "models")

MODELS_DIR = os.path.join(DATA_DIR, "models")
IMAGES_DIR = os.path.join(DATA_DIR, "images")
LOGS_DIR = os.path.join(DATA_DIR, "logs")
SCREENSHOT_DIR = os.path.join(DATA_DIR, "screenshots")
SETTINGS_PATH = os.path.join(DATA_DIR, "app_settings.json")
GAZE_CALIB_PATH = os.path.join(DATA_DIR, "gaze_calibration.json")
HAND_CALIB_PATH = os.path.join(DATA_DIR, "hand_calibration.json")
CUSTOM_GESTURES_PATH = os.path.join(DATA_DIR, "custom_gestures.json")

_USER_FILES = ("app_settings.json", "gaze_calibration.json", "hand_calibration.json",
               "custom_gestures.json")


def ensure_dirs():
    for path in (DATA_DIR, MODELS_DIR, IMAGES_DIR, LOGS_DIR, SCREENSHOT_DIR):
        os.makedirs(path, exist_ok=True)


def migrate_legacy_data():
    """Copy settings/calibration from the old location once (source checkouts)."""
    if not LEGACY_DATA_DIR or os.path.normcase(LEGACY_DATA_DIR) == os.path.normcase(DATA_DIR):
        return
    for name in _USER_FILES:
        src, dst = os.path.join(LEGACY_DATA_DIR, name), os.path.join(DATA_DIR, name)
        if os.path.isfile(src) and not os.path.exists(dst):
            try:
                shutil.copy2(src, dst)
            except OSError:
                pass
    old_images = os.path.join(LEGACY_DATA_DIR, "images")
    if os.path.isdir(old_images):
        for name in os.listdir(old_images):
            if name.lower().startswith("gesture_") and not os.path.exists(os.path.join(IMAGES_DIR, name)):
                try:
                    shutil.copy2(os.path.join(old_images, name), IMAGES_DIR)
                except OSError:
                    pass


def model_path(filename):
    """Prefer a model shipped with the app, then a download, then a legacy copy."""
    candidates = [os.path.join(BUNDLED_MODELS_DIR, filename), os.path.join(MODELS_DIR, filename)]
    if LEGACY_DATA_DIR:
        candidates.append(os.path.join(LEGACY_DATA_DIR, "models", filename))
    for path in candidates:
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            return path
    return candidates[1]


LOG_FILE = os.path.join(LOGS_DIR, "handtrack.log")


def setup_logging():
    ensure_dirs()
    migrate_legacy_data()
    logger = logging.getLogger("handtrack")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = RotatingFileHandler(LOG_FILE,
                                      maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)s | %(threadName)s | %(message)s"))
        logger.addHandler(handler)
    return logger
