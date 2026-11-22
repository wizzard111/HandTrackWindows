"""Persistent settings, calibration and custom gesture storage.

Settings is a plain object shared by the UI thread (writes) and the
processing thread (reads). Each field is a single attribute assignment of
an immutable value, which is atomic under the GIL, so no lock is needed.
"""

import json
import logging
import os
from dataclasses import asdict, dataclass, fields

import numpy as np

from handtrack import paths

logger = logging.getLogger("handtrack")

HAND_TEMPLATE_VERSION = 2
RESOLUTIONS = ("640x480", "1280x720", "1920x1080")
ACTION_KEYS = (
    "toggle_hide_face", "screenshot", "toggle_preview", "hotkey", "key",
    "media_playpause", "volume_up", "volume_down", "mute", "run", "open", "clear_drawing",
)
ACTIONS_WITH_PARAM = frozenset(("hotkey", "key", "run", "open"))
ACTIONS_WITH_KEYS = frozenset(("hotkey", "key", "media_playpause",
                               "volume_up", "volume_down", "mute"))


def atomic_json_dump(path, data):
    """Write JSON so a crash never leaves a half-written file behind."""
    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp_path, path)
    except Exception:
        logger.exception("Could not save JSON: %s", path)
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        return False
    return True


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        logger.warning("Ignoring unreadable file %s", path, exc_info=True)
        return None


@dataclass
class Settings:
    hide_face: bool = False
    visualize: bool = True
    gaze: bool = True
    threshold: float = 0.55
    attach_photo: bool = True
    rotate_sticker: bool = True
    sticker_scale: float = 1.3
    show_counter: bool = True
    preview_visible: bool = True
    fast_mode: bool = True
    resolution: str = "1280x720"
    dark_mode: bool = True
    vcam: bool = False
    draw_enabled: bool = True
    draw_color: int = 0
    draw_thickness: int = 6
    draw_lifetime: float = 10.0     # seconds, 0 = until cleared
    draw_glow: bool = True
    afk_enabled: bool = True
    afk_timeout: float = 8.0
    lang: str = "ru"
    custom_gestures_enabled: bool = True
    camera_index: int = 0

    # Files written by v6 used a "_var" suffix on every key.
    @classmethod
    def load(cls):
        settings = cls()
        data = _read_json(paths.SETTINGS_PATH)
        if not isinstance(data, dict):
            return settings
        for field in fields(cls):
            raw = data.get(field.name, data.get(f"{field.name}_var"))
            if raw is None:
                continue
            try:
                value = field.type(raw) if field.type is not bool else bool(raw)
            except (TypeError, ValueError):
                continue
            setattr(settings, field.name, value)
        if settings.lang not in ("ru", "en"):
            settings.lang = "ru"
        if settings.resolution not in RESOLUTIONS:
            settings.resolution = "1280x720"
        return settings

    def save(self):
        atomic_json_dump(paths.SETTINGS_PATH, asdict(self))

    def resolution_tuple(self):
        try:
            width, height = self.resolution.split("x")
            return int(width), int(height)
        except ValueError:
            return 1280, 720


def load_saved_lang():
    data = _read_json(paths.SETTINGS_PATH)
    if isinstance(data, dict):
        lang = data.get("lang", data.get("lang_var"))
        if lang in ("ru", "en"):
            return lang
    return "ru"


# ------------------------------------------------------------- calibration ----
def load_gaze_calibration():
    data = _read_json(paths.GAZE_CALIB_PATH)
    try:
        coeffs_x = [float(v) for v in data["coeffs_x"]]
        coeffs_y = [float(v) for v in data["coeffs_y"]]
    except (TypeError, KeyError, ValueError):
        return None
    if len(coeffs_x) != 5 or len(coeffs_y) != 5:
        return None
    return coeffs_x, coeffs_y


def save_gaze_calibration(coeffs):
    if coeffs is None:
        _remove(paths.GAZE_CALIB_PATH)
        return
    coeffs_x, coeffs_y = coeffs
    atomic_json_dump(paths.GAZE_CALIB_PATH, {"coeffs_x": list(coeffs_x),
                                             "coeffs_y": list(coeffs_y)})


def load_hand_templates():
    data = _read_json(paths.HAND_CALIB_PATH)
    if not isinstance(data, dict) or data.get("version") != HAND_TEMPLATE_VERSION:
        return {}
    try:
        return {int(k): np.asarray(v, dtype=np.float32)
                for k, v in (data.get("templates") or {}).items()}
    except (TypeError, ValueError):
        logger.warning("Ignoring invalid hand calibration", exc_info=True)
        return {}


def save_hand_templates(templates):
    if not templates:
        _remove(paths.HAND_CALIB_PATH)
        return
    atomic_json_dump(paths.HAND_CALIB_PATH, {
        "version": HAND_TEMPLATE_VERSION,
        "templates": {str(n): t.tolist() for n, t in templates.items()},
    })


# --------------------------------------------------------- custom gestures ----
def load_custom_gestures():
    data = _read_json(paths.CUSTOM_GESTURES_PATH)
    gestures = []
    if not isinstance(data, list):
        return gestures
    for item in data:
        try:
            pattern = tuple(bool(x) for x in item["pattern"])
            action = str(item["action_type"])
            if len(pattern) != 5 or action not in ACTION_KEYS:
                continue
            gestures.append({
                "name": str(item["name"]),
                "pattern": pattern,
                "action_type": action,
                "action_param": str(item.get("action_param", "")),
            })
        except (TypeError, KeyError):
            continue
    return gestures


def save_custom_gestures(gestures):
    atomic_json_dump(paths.CUSTOM_GESTURES_PATH, [
        {**g, "pattern": list(g["pattern"])} for g in gestures
    ])


def _remove(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError:
        logger.warning("Could not remove %s", path, exc_info=True)
