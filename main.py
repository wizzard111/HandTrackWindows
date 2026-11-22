"""
HandTrack GUI v6 Optimized — hand/gesture tracking (with step-by-step 1-5 calibration),
gaze tracking (with calibration), visualization, privacy, virtual camera,
and RU/EN localization.

Uses the MediaPipe Tasks API (HandLandmarker / FaceLandmarker) instead of
the legacy mp.solutions.

Dependencies (see requirements.txt):
    pip install -r requirements.txt

On first launch, 2 model files (~10-15 MB) are downloaded automatically
from Google's servers into a models/ folder next to the script — internet
is needed once.

The virtual camera (so effects are visible in Discord/Zoom/OBS etc.)
requires OBS Studio (which provides "OBS Virtual Camera") or Unity
Capture to be installed — pyvirtualcam itself installs nothing, it only
connects to an already-existing virtual device.

Run:
    python main.py
"""

import os
import json
import time
import shutil
import math
import logging
import queue
import shlex
import threading
import urllib.request
import urllib.error
import tkinter as tk
from collections import OrderedDict, defaultdict, deque
from logging.handlers import RotatingFileHandler
from tkinter import ttk, messagebox
from datetime import datetime

import cv2
import numpy as np
from PIL import Image, ImageTk, ImageGrab, ImageDraw, ImageFont, ImageFilter

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCREENSHOT_DIR = os.path.join(BASE_DIR, "screenshots")
MODELS_DIR = os.path.join(BASE_DIR, "models")
IMAGES_DIR = os.path.join(BASE_DIR, "images")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
HAND_REFERENCE_PATH = os.path.join(ASSETS_DIR, "hand_reference.png")
GAZE_CALIB_PATH = os.path.join(BASE_DIR, "gaze_calibration.json")
HAND_CALIB_PATH = os.path.join(BASE_DIR, "hand_calibration.json")
SETTINGS_PATH = os.path.join(BASE_DIR, "app_settings.json")
CUSTOM_GESTURES_PATH = os.path.join(BASE_DIR, "custom_gestures.json")

os.makedirs(LOGS_DIR, exist_ok=True)
logger = logging.getLogger("handtrack")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _log_handler = RotatingFileHandler(
        os.path.join(LOGS_DIR, "handtrack.log"),
        maxBytes=1_000_000,
        backupCount=2,
        encoding="utf-8",
    )
    _log_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)s | %(threadName)s | %(message)s"
    ))
    logger.addHandler(_log_handler)

# ============================================================ Локализация / i18n ====
# Все строки интерфейса — на русском и английском. self.tr(key, **kwargs) в классе
# приложения выбирает нужный язык; для сообщений ДО появления окна (сплэш, ошибка
# отсутствия mediapipe) используется _STARTUP_LANG, подхваченный из сохранённых
# настроек прошлого запуска (см. load_saved_lang() ниже).
STRINGS = {
    "ru": {
        "app_title": "HandTrack — жесты, взгляд, приватность",
        "splash_title": "HandTrack",
        "splash_checking": "Проверка моделей распознавания...",
        "downloading_model": "Скачивание модели {name}...",
        "err_mediapipe_missing": (
            "Не найден пакет mediapipe (или версия слишком старая для Tasks API).\n"
            "Установите зависимости:\n"
            "    pip install opencv-python mediapipe pillow numpy pyvirtualcam"
        ),
        "err_model_download": (
            "Не удалось скачать модель {name} ({url}).\n"
            "Проверьте интернет-соединение или скачайте файл вручную и "
            "положите в папку models/.\nОшибка: {err}"
        ),
        "err_models_title": "Ошибка загрузки моделей",

        "dark_theme": "🌙 Тёмная тема",
        "lang_toggle": "🌐 EN",

        "preview_frame": "Предпросмотр камеры",
        "standby_start": "⏸  STANDBY\nНажмите «Старт»",
        "standby_stopped": "⏸  STANDBY\nКамера остановлена",
        "preview_hidden": "Предпросмотр скрыт.\nОбработка и виртуальная камера продолжают работать.",

        "gazemap_frame": "Карта взгляда (экран)",

        "controls_frame": "Управление",
        "start_btn": "Старт",
        "stop_btn": "Стоп",
        "resolution_label": "Разрешение камеры:",
        "hide_face_cb": "Скрыть лицо (чёрный квадрат)",
        "visualize_cb": "Визуализация трекинга (точки/контуры)",
        "gaze_cb": "Трекинг взгляда",
        "counter_cb": "Счётчик пальцев в углу кадра",
        "preview_cb": "Показывать предпросмотр",
        "fastmode_cb": "Ускоренный режим (половина разрешения для распознавания)",
        "draw_cb": "Рисование щипком (👌 большой+указательный)",
        "afk_cb": "Авто-AFK при отсутствии лица в кадре",
        "afk_timeout_label": "Время до AFK (сек):",
        "threshold_label": "Порог доверия к калибровке:",

        "vcam_frame": "Виртуальная камера (для Discord и т.п.)",
        "vcam_cb": "Транслировать обработанное видео",
        "vcam_note_ok": (
            "Выберите «OBS Virtual Camera» / «Unity Video Capture» как камеру в Discord.\n\n"
            "ВАЖНО: если видео в Discord растянуто — откройте OBS → Настройки → Видео и "
            "поставьте Базовое (Холст) и Выходное (Масштаб.) разрешение ТОЧНО ТАКОЕ ЖЕ, как "
            "выбрано выше в «Разрешение камеры» (и как показано в статусной строке после "
            "«Старт»). OBS всегда выводит камеру в СВОЁМ заданном разрешении и растягивает "
            "под него любой присланный кадр."
        ),
        "vcam_note_missing": (
            "Не установлен pyvirtualcam. Установите:\npip install pyvirtualcam\n"
            "и OBS Studio (даёт виртуальную камеру)."
        ),

        "sticker_frame": "Фото на жестах (1-5 пальцев)",
        "attach_cb": "Крепить фото к руке",
        "rotate_cb": "Поворачивать по повороту руки",
        "sticker_size_label": "Размер фото:",
        "open_folder_btn": "Открыть папку с картинками",
        "reload_stickers_btn": "Обновить картинки",
        "sticker_hint": ("1 палец → gesture_1.png/.jpg, 2 → gesture_2 и т.д.\n"
                          "(кладите файлы в папку images/, любое расширение)"),
        "sticker_status_prefix": "Свои фото загружены: ",
        "sticker_status_suffix": "  (— = плейсхолдер)",

        "calib_frame": "Калибровка",
        "gaze_calib_btn": "Калибровать взгляд (9 точек)",
        "gaze_calib_reset_btn": "Сбросить калибровку взгляда",
        "hand_calib_btn": "Калибровать жесты 1→5 (мастер)",
        "hand_calib_cancel_btn": "Отменить калибровку",
        "hand_calib_reset_btn": "Сбросить калибровку жестов",

        "status_frame": "Статус",

        "status_stopped": "Остановлено",
        "status_running": "Запущено (разрешение камеры: {w}x{h}{note})",
        "status_running_mismatch_note": " (камера не поддерживает {w}x{h}, дала своё ближайшее)",
        "status_screenshot_saved": "Скриншот сохранён: {path}",
        "status_stickers_reloaded": "Картинки для жестов обновлены",
        "status_gaze_calib_cancelled": "Калибровка взгляда отменена",
        "status_gaze_calib_done": "Калибровка взгляда завершена",
        "status_vcam_started": ("Виртуальная камера запущена ({dev}, {w}x{h}). "
                                 "В OBS выставьте такое же разрешение вывода, иначе видео растянется."),

        "gaze_calib_done_label": "Взгляд откалиброван (9 точек) ✓",
        "gaze_calib_reset_label": "Взгляд не откалиброван (грубая оценка лево/право)",
        "gaze_calib_fullscreen_hint": "Смотрите на красную точку. Esc — отмена.",

        "gaze_zone_top_left": "лево-верх", "gaze_zone_top_center": "центр-верх", "gaze_zone_top_right": "право-верх",
        "gaze_zone_mid_left": "лево-центр", "gaze_zone_mid_center": "центр", "gaze_zone_mid_right": "право-центр",
        "gaze_zone_bottom_left": "лево-низ", "gaze_zone_bottom_center": "центр-низ", "gaze_zone_bottom_right": "право-низ",
        "gaze_status_zone": "Взгляд: {zone}",
        "gaze_dir_left": "влево", "gaze_dir_right": "вправо", "gaze_dir_center": "прямо",
        "gaze_status_rough": "Взгляд: {direction} (грубо, {val:.2f})",
        "gaze_status_no_face": "Взгляд: лицо не найдено",
        "gaze_status_off": "Взгляд: выключен",

        "hand_calib_step_prep": "Шаг {n}/5: приготовьтесь показать {n} палец(-ев)...",
        "hand_calib_step_countdown": "Шаг {n}/5: покажите {n} палец(-ев)! Старт через {r:.1f} с",
        "hand_calib_step_collect": "Шаг {n}/5: держите {n} палец(-ев)... {c}/{t}",
        "hand_calib_done": "Жесты 1-5 откалиброваны ✓",
        "hand_calib_prev_done": "Откалибровано ранее: {list} ✓",
        "hand_calib_reset_label": "Жесты не откалиброваны (базовый счёт пальцев)",

        "gesture_calibrating": "Жест: идёт калибровка (сырой счёт: {n})",
        "gesture_templ": "Жест: {n} (калибровка, расст. {d:.2f})",
        "gesture_templ_unsure": "Жест: {n} (базовый счёт; калибровка не уверена: {d:.2f})",
        "gesture_basic": "Жест: {n} пальцев (базовый счёт)",
        "gesture_no_hand": "Жест: рука не найдена",

        "afk_text": "AFK",
        "afk_subtext": "отошёл от камеры",

        "err_title": "Ошибка",
        "err_camera": "Не удалось открыть веб-камеру.",
        "info_images_folder_title": "Папка с картинками",
        "info_images_folder_fail": "{dir}\n\n(Не удалось открыть автоматически: {err})",
        "info_need_camera_title": "Нужна камера",
        "info_need_camera_gaze": "Сначала нажмите «Старт», затем калибруйте взгляд.",
        "info_need_camera_hand": "Сначала нажмите «Старт», затем калибруйте жесты.",
        "err_calib_build": "Не удалось построить калибровку. Попробуйте снова.",
        "warn_face_not_found_title": "Лицо не найдено",
        "warn_face_not_found_msg": "Не удалось увидеть глаза для этой точки. Калибровка отменена.",
        "warn_hand_calib_interrupted_title": "Калибровка прервана",
        "warn_hand_calib_interrupted_msg": (
            "Не удалось увидеть руку на шаге {n} (жест «{n} палец(-ев)»). Попробуйте снова."
        ),
        "err_vcam_title": "Виртуальная камера",
        "err_vcam_msg": (
            "Не удалось запустить виртуальную камеру.\n"
            "Нужен установленный OBS Studio (даёт виртуальную камеру) или Unity Capture.\n\n"
            "Ошибка: {err}"
        ),

        "tab_camera": "Камера",
        "tab_gestures": "Мои жесты",
        "gesture_designer_intro": (
            "Задайте точную форму жеста: нажимайте прямо на пальцы ладони или "
            "используйте переключатели под ней. Зелёный палец должен быть поднят, "
            "чёрный — согнут. Затем укажите название и действие и нажмите "
            "«Добавить жест». Камера выполнит действие, когда увидит именно эту "
            "комбинацию пяти пальцев."
        ),
        "gesture_hand_hint": "Нажмите на пальцы, которые должны быть подняты",
        "finger_thumb": "Большой",
        "finger_index": "Указательный",
        "finger_middle": "Средний",
        "finger_ring": "Безымянный",
        "finger_pinky": "Мизинец",
        "finger_up": "поднят",
        "finger_down": "согнут",

        "custom_frame": "Список моих жестов",
        "custom_enabled_cb": "Включить мои жесты",
        "custom_add_btn": "+ Добавить жест",
        "custom_empty": "Пока нет ни одного своего жеста.",
        "custom_delete_btn": "✕",
        "custom_name_label": "Название жеста:",
        "custom_action_label": "Действие:",
        "custom_param_label": "Параметр:",
        "custom_name_empty_msg": "Введите название жеста.",
        "custom_param_empty_msg": "Заполните параметр действия.",
        "custom_pyautogui_missing_msg": (
            "Для этого действия нужен пакет pyautogui.\n"
            "Установите: pip install pyautogui"
        ),

        "action_toggle_hide_face": "Скрыть/показать лицо",
        "action_screenshot": "Сделать скриншот",
        "action_toggle_preview": "Показать/скрыть предпросмотр",
        "action_hotkey": "Комбинация клавиш",
        "action_key": "Одна клавиша",
        "action_media_playpause": "Медиа: пауза/воспроизведение",
        "action_volume_up": "Громкость +",
        "action_volume_down": "Громкость -",
        "action_mute": "Без звука",
        "action_run": "Запустить программу",
        "action_open": "Открыть файл/ссылку",

        "hint_hotkey": "Например: ctrl+shift+s",
        "hint_key": "Например: enter, space, f5",
        "hint_media_playpause": "Параметр не нужен",
        "hint_volume_up": "Параметр не нужен",
        "hint_volume_down": "Параметр не нужен",
        "hint_mute": "Параметр не нужен",
        "hint_run": "Например: notepad.exe или программа.exe файл.txt",
        "hint_open": "Например: https://example.com или C:\\путь\\файл",
        "hint_toggle_hide_face": "Параметр не нужен",
        "hint_screenshot": "Параметр не нужен",
        "hint_toggle_preview": "Параметр не нужен",

        "custom_capture_btn": "🎹 Записать комбинацию",
        "custom_capture_recording": "Нажмите клавиши... (Esc — отмена)",
    },
    "en": {
        "app_title": "HandTrack — Gestures, Gaze, Privacy",
        "splash_title": "HandTrack",
        "splash_checking": "Checking recognition models...",
        "downloading_model": "Downloading {name} model...",
        "err_mediapipe_missing": (
            "The mediapipe package was not found (or the version is too old for the Tasks API).\n"
            "Install the dependencies:\n"
            "    pip install opencv-python mediapipe pillow numpy pyvirtualcam"
        ),
        "err_model_download": (
            "Could not download the {name} model ({url}).\n"
            "Check your internet connection, or download the file manually and "
            "place it in the models/ folder.\nError: {err}"
        ),
        "err_models_title": "Model download error",

        "dark_theme": "🌙 Dark theme",
        "lang_toggle": "🌐 RU",

        "preview_frame": "Camera preview",
        "standby_start": "⏸  STANDBY\nPress \u201cStart\u201d",
        "standby_stopped": "⏸  STANDBY\nCamera stopped",
        "preview_hidden": "Preview hidden.\nProcessing and the virtual camera keep running.",

        "gazemap_frame": "Gaze map (screen)",

        "controls_frame": "Controls",
        "start_btn": "Start",
        "stop_btn": "Stop",
        "resolution_label": "Camera resolution:",
        "hide_face_cb": "Hide face (black box)",
        "visualize_cb": "Tracking visualization (dots/outlines)",
        "gaze_cb": "Gaze tracking",
        "counter_cb": "Finger counter in frame corner",
        "preview_cb": "Show preview",
        "fastmode_cb": "Fast mode (half resolution for detection)",
        "draw_cb": "Pinch drawing (👌 thumb+index)",
        "afk_cb": "Auto-AFK when no face in frame",
        "afk_timeout_label": "Time until AFK (sec):",
        "threshold_label": "Calibration confidence threshold:",

        "vcam_frame": "Virtual camera (for Discord, etc.)",
        "vcam_cb": "Stream processed video",
        "vcam_note_ok": (
            "Select \u201cOBS Virtual Camera\u201d / \u201cUnity Video Capture\u201d as the camera in Discord.\n\n"
            "IMPORTANT: if the video looks stretched in Discord — open OBS → Settings → Video and "
            "set the Base (Canvas) and Output (Scaled) resolution to EXACTLY the same value chosen "
            "above in \u201cCamera resolution\u201d (and shown in the status line after \u201cStart\u201d). "
            "OBS always outputs the camera at ITS OWN configured resolution and stretches "
            "any incoming frame to fit it."
        ),
        "vcam_note_missing": (
            "pyvirtualcam is not installed. Install it with:\npip install pyvirtualcam\n"
            "and OBS Studio (provides the virtual camera)."
        ),

        "sticker_frame": "Photos on gestures (1-5 fingers)",
        "attach_cb": "Attach photo to hand",
        "rotate_cb": "Rotate with hand orientation",
        "sticker_size_label": "Photo size:",
        "open_folder_btn": "Open images folder",
        "reload_stickers_btn": "Reload images",
        "sticker_hint": ("1 finger → gesture_1.png/.jpg, 2 → gesture_2, etc.\n"
                          "(place files in the images/ folder, any extension)"),
        "sticker_status_prefix": "Custom photos loaded: ",
        "sticker_status_suffix": "  (— = placeholder)",

        "calib_frame": "Calibration",
        "gaze_calib_btn": "Calibrate gaze (9 points)",
        "gaze_calib_reset_btn": "Reset gaze calibration",
        "hand_calib_btn": "Calibrate gestures 1→5 (wizard)",
        "hand_calib_cancel_btn": "Cancel calibration",
        "hand_calib_reset_btn": "Reset gesture calibration",

        "status_frame": "Status",

        "status_stopped": "Stopped",
        "status_running": "Running (camera resolution: {w}x{h}{note})",
        "status_running_mismatch_note": " (camera doesn't support {w}x{h}, using closest match)",
        "status_screenshot_saved": "Screenshot saved: {path}",
        "status_stickers_reloaded": "Gesture images reloaded",
        "status_gaze_calib_cancelled": "Gaze calibration cancelled",
        "status_gaze_calib_done": "Gaze calibration complete",
        "status_vcam_started": ("Virtual camera started ({dev}, {w}x{h}). "
                                 "Set the same output resolution in OBS or the video will look stretched."),

        "gaze_calib_done_label": "Gaze calibrated (9 points) ✓",
        "gaze_calib_reset_label": "Gaze not calibrated (rough left/right estimate)",
        "gaze_calib_fullscreen_hint": "Look at the red dot. Esc to cancel.",

        "gaze_zone_top_left": "top-left", "gaze_zone_top_center": "top-center", "gaze_zone_top_right": "top-right",
        "gaze_zone_mid_left": "mid-left", "gaze_zone_mid_center": "center", "gaze_zone_mid_right": "mid-right",
        "gaze_zone_bottom_left": "bottom-left", "gaze_zone_bottom_center": "bottom-center", "gaze_zone_bottom_right": "bottom-right",
        "gaze_status_zone": "Gaze: {zone}",
        "gaze_dir_left": "left", "gaze_dir_right": "right", "gaze_dir_center": "center",
        "gaze_status_rough": "Gaze: {direction} (rough, {val:.2f})",
        "gaze_status_no_face": "Gaze: face not found",
        "gaze_status_off": "Gaze: off",

        "hand_calib_step_prep": "Step {n}/5: get ready to show {n} finger(s)...",
        "hand_calib_step_countdown": "Step {n}/5: show {n} finger(s)! Starting in {r:.1f}s",
        "hand_calib_step_collect": "Step {n}/5: hold {n} finger(s)... {c}/{t}",
        "hand_calib_done": "Gestures 1-5 calibrated ✓",
        "hand_calib_prev_done": "Previously calibrated: {list} ✓",
        "hand_calib_reset_label": "Gestures not calibrated (basic finger count)",

        "gesture_calibrating": "Gesture: calibrating (raw count: {n})",
        "gesture_templ": "Gesture: {n} (calibrated, dist {d:.2f})",
        "gesture_templ_unsure": "Gesture: {n} (basic count; calibration unsure: {d:.2f})",
        "gesture_basic": "Gesture: {n} fingers (basic count)",
        "gesture_no_hand": "Gesture: no hand found",

        "afk_text": "AFK",
        "afk_subtext": "away from camera",

        "err_title": "Error",
        "err_camera": "Could not open the webcam.",
        "info_images_folder_title": "Images folder",
        "info_images_folder_fail": "{dir}\n\n(Could not open automatically: {err})",
        "info_need_camera_title": "Camera needed",
        "info_need_camera_gaze": "Press \u201cStart\u201d first, then calibrate gaze.",
        "info_need_camera_hand": "Press \u201cStart\u201d first, then calibrate gestures.",
        "err_calib_build": "Could not build the calibration. Try again.",
        "warn_face_not_found_title": "Face not found",
        "warn_face_not_found_msg": "Could not see your eyes for this point. Calibration cancelled.",
        "warn_hand_calib_interrupted_title": "Calibration interrupted",
        "warn_hand_calib_interrupted_msg": (
            "Could not see your hand on step {n} (gesture \u201c{n} finger(s)\u201d). Try again."
        ),
        "err_vcam_title": "Virtual camera",
        "err_vcam_msg": (
            "Could not start the virtual camera.\n"
            "You need OBS Studio (provides a virtual camera) or Unity Capture installed.\n\n"
            "Error: {err}"
        ),

        "tab_camera": "Camera",
        "tab_gestures": "My gestures",
        "gesture_designer_intro": (
            "Build the exact hand shape: click the fingers in the picture or use "
            "the switches below it. A green finger must be raised; a black finger "
            "must be bent. Then enter a name and action and press \u201cAdd gesture\u201d. "
            "The camera runs the action only when it sees that exact five-finger "
            "combination."
        ),
        "gesture_hand_hint": "Click every finger that should be raised",
        "finger_thumb": "Thumb",
        "finger_index": "Index",
        "finger_middle": "Middle",
        "finger_ring": "Ring",
        "finger_pinky": "Pinky",
        "finger_up": "raised",
        "finger_down": "bent",

        "custom_frame": "My gestures list",
        "custom_enabled_cb": "Enable my gestures",
        "custom_add_btn": "+ Add gesture",
        "custom_empty": "No custom gestures yet.",
        "custom_delete_btn": "✕",
        "custom_name_label": "Gesture name:",
        "custom_action_label": "Action:",
        "custom_param_label": "Parameter:",
        "custom_name_empty_msg": "Enter a name for the gesture.",
        "custom_param_empty_msg": "Fill in the action parameter.",
        "custom_pyautogui_missing_msg": (
            "This action needs the pyautogui package.\n"
            "Install it with: pip install pyautogui"
        ),

        "action_toggle_hide_face": "Toggle hide face",
        "action_screenshot": "Take screenshot",
        "action_toggle_preview": "Toggle preview",
        "action_hotkey": "Key combination",
        "action_key": "Single key",
        "action_media_playpause": "Media: play/pause",
        "action_volume_up": "Volume +",
        "action_volume_down": "Volume -",
        "action_mute": "Mute",
        "action_run": "Run program",
        "action_open": "Open file/link",

        "hint_hotkey": "e.g. ctrl+shift+s",
        "hint_key": "e.g. enter, space, f5",
        "hint_media_playpause": "No parameter needed",
        "hint_volume_up": "No parameter needed",
        "hint_volume_down": "No parameter needed",
        "hint_mute": "No parameter needed",
        "hint_run": "e.g. notepad.exe or program.exe file.txt",
        "hint_open": "e.g. https://example.com or C:\\path\\file",
        "hint_toggle_hide_face": "No parameter needed",
        "hint_screenshot": "No parameter needed",
        "hint_toggle_preview": "No parameter needed",

        "custom_capture_btn": "🎹 Record combination",
        "custom_capture_recording": "Press the keys... (Esc to cancel)",
    },
}


def load_saved_lang():
    """Подглядывает сохранённый язык интерфейса ДО построения окна (в т.ч. для
    экрана загрузки моделей) — не критично, если файла ещё нет, тогда 'ru'."""
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        lang = data.get("lang_var", "ru")
        return lang if lang in STRINGS else "ru"
    except (OSError, ValueError, TypeError):
        logger.debug("Could not load saved language; using Russian", exc_info=True)
        return "ru"


_STARTUP_LANG = load_saved_lang()

try:
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions
    from mediapipe.tasks.python.vision import (
        HandLandmarker, HandLandmarkerOptions,
        FaceLandmarker, FaceLandmarkerOptions,
        RunningMode,
    )
except ImportError:
    raise SystemExit(STRINGS[_STARTUP_LANG]["err_mediapipe_missing"])

try:
    import pyvirtualcam
    VCAM_AVAILABLE = True
except ImportError:
    VCAM_AVAILABLE = False

try:
    import pyautogui
    # Оставляем аварийную остановку PyAutoGUI включённой: резкое перемещение
    # курсора в левый верхний угол прервёт ошибочно зациклившееся действие.
    pyautogui.FAILSAFE = True
    PYAUTOGUI_AVAILABLE = True
except Exception:
    logger.info("PyAutoGUI is unavailable; keyboard/media actions are disabled", exc_info=True)
    PYAUTOGUI_AVAILABLE = False

import subprocess

# Какие поля (имя атрибута -> тип) сохраняются между запусками программы.
SETTINGS_SPEC = [
    ("hide_face_var", "bool"), ("visualize_var", "bool"), ("gaze_var", "bool"),
    ("threshold_var", "float"), ("attach_photo_var", "bool"), ("rotate_sticker_var", "bool"),
    ("sticker_scale_var", "float"), ("show_counter_var", "bool"), ("preview_visible_var", "bool"),
    ("fast_mode_var", "bool"), ("resolution_var", "str"),
    ("dark_mode_var", "bool"), ("vcam_var", "bool"), ("draw_enabled_var", "bool"),
    ("afk_enabled_var", "bool"), ("afk_timeout_var", "float"),
    ("lang_var", "str"), ("custom_gestures_enabled_var", "bool"),
]
os.makedirs(SCREENSHOT_DIR, exist_ok=True)
os.makedirs(MODELS_DIR, exist_ok=True)
os.makedirs(IMAGES_DIR, exist_ok=True)

# Картинки для жестов 1-5 пальцев: images/gesture_1.* ... gesture_5.*
# (любое из расширений ниже, регистр не важен). Если файла нет — плейсхолдер.
STICKER_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
STICKER_PLACEHOLDER_COLORS = {
    1: (71, 99, 255), 2: (0, 165, 255), 3: (0, 215, 255),
    4: (113, 179, 60), 5: (225, 105, 65),
}  # BGR

HAND_MODEL_PATH = os.path.join(MODELS_DIR, "hand_landmarker.task")
FACE_MODEL_PATH = os.path.join(MODELS_DIR, "face_landmarker.task")
HAND_MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
                   "hand_landmarker/float16/latest/hand_landmarker.task")
FACE_MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/face_landmarker/"
                   "face_landmarker/float16/latest/face_landmarker.task")

AFK_DEFAULT_TIMEOUT = 8.0      # сек без лица в кадре, после которых включается AFK-заглушка
CUSTOM_GESTURE_COOLDOWN = 1.5  # сек между повторными срабатываниями одного пользовательского жеста
HAND_TEMPLATE_VERSION = 2      # v2 дополнительно нормализует поворот кисти

# Асинхронные детекторы не блокируют Tkinter. Частоту тяжёлого FaceLandmarker
# снижаем, когда он нужен только для взгляда/AFK; для приватной маски и
# калибровки оставляем частую обработку.
HAND_INFERENCE_INTERVAL = 1.0 / 30.0
FACE_GAZE_INTERVAL = 1.0 / 20.0
FACE_AFK_INTERVAL = 1.0 / 10.0
RESULT_STALE_SECONDS = 0.35
UI_POLL_MS = 8

# Фиксированное разрешение захвата с камеры (16:9). Явно задаём его, а не
# полагаемся на дефолт устройства (часто 640x480 4:3) — так предсказуемее,
# и это же разрешение нужно указать в OBS (Settings → Video → Base/Output
# Resolution), иначе OBS растянет/сожмёт кадр под своё собственное
# настроенное разрешение — именно это выглядит как "растянутое видео" в
# приложениях, использующих виртуальную камеру (Discord и т.п.), хотя в
# нашем локальном предпросмотре всё нормально (он показывает кадр как есть).
CAPTURE_WIDTH = 1280   # значение по умолчанию для выпадающего списка разрешений
CAPTURE_HEIGHT = 720

# "Ускоренный режим": детекторам скармливается уменьшенная (в 2 раза по
# каждой стороне) копия кадра — реальный размер считается на лету от
# фактического разрешения камеры (см. _update_frame), а не фиксирован
# здесь, чтобы не искажать пропорции при разных выбранных разрешениях.
GAZE_CALIB_POINTS_FRAC = [
    (0.08, 0.08), (0.5, 0.08), (0.92, 0.08),
    (0.08, 0.5), (0.5, 0.5), (0.92, 0.5),
    (0.08, 0.92), (0.5, 0.92), (0.92, 0.92),
]
GAZE_SAMPLES_PER_POINT = 15
GAZE_WAIT_BEFORE_COLLECT = 0.7
GAZE_POINT_TIMEOUT = 8.0
GAZE_ZONE_KEYS = [
    ["gaze_zone_top_left", "gaze_zone_top_center", "gaze_zone_top_right"],
    ["gaze_zone_mid_left", "gaze_zone_mid_center", "gaze_zone_mid_right"],
    ["gaze_zone_bottom_left", "gaze_zone_bottom_center", "gaze_zone_bottom_right"],
]

HAND_SAMPLES_TARGET = 20
HAND_WIZARD_COUNTDOWN = 2.5
HAND_CALIB_TIMEOUT = 10.0

# --- Индексы точек руки (те же в Tasks API, что и в старом Hands) ---
FINGER_TIPS = [4, 8, 12, 16, 20]
FINGER_PIPS = [3, 6, 10, 14, 18]

# --- Индексы точек глаз/радужки (те же, что были в FaceMesh refine_landmarks=True) ---
LEFT_IRIS = 468
LEFT_CORNER_L, LEFT_CORNER_R = 33, 133
LEFT_LID_TOP, LEFT_LID_BOTTOM = 159, 145

RIGHT_IRIS = 473
RIGHT_CORNER_L, RIGHT_CORNER_R = 362, 263
RIGHT_LID_TOP, RIGHT_LID_BOTTOM = 386, 374

# Точки-якоря для маски "Скрыть лицо": лоб/подбородок (высота), края лица
# (ширина), нос, рот, щёки — устойчивее к дрожанию, чем весь меш из 478
# точек (не зависит от моргания/мимики), маска держится крепче на месте.
FACE_MASK_ANCHOR_IDX = [10, 152, 234, 454, 1, 4, 168, 61, 291, 13, 14, 50, 280]

# --- Запись комбинации клавиш для "Мои жесты" (кнопка "Записать комбинацию") ---
KEYSYM_TO_PYAUTOGUI = {
    "Control_L": "ctrl", "Control_R": "ctrl",
    "Shift_L": "shift", "Shift_R": "shift",
    "Alt_L": "alt", "Alt_R": "alt",
    "Super_L": "win", "Super_R": "win",
    "Meta_L": "alt", "Meta_R": "alt",
    "Escape": "esc", "Return": "enter", "BackSpace": "backspace",
    "Tab": "tab", "space": "space", "Delete": "delete",
    "Up": "up", "Down": "down", "Left": "left", "Right": "right",
    "Prior": "pageup", "Next": "pagedown", "Home": "home", "End": "end",
    "Insert": "insert", "Caps_Lock": "capslock",
}
MODIFIER_KEY_NAMES = ("ctrl", "alt", "shift", "win")


def keysym_to_pyautogui(keysym):
    """Переводит event.keysym из Tkinter в имя клавиши, понятное pyautogui."""
    return KEYSYM_TO_PYAUTOGUI.get(keysym, keysym.lower())


# --- Рисование жестом "щипок" (большой + указательный палец) ---
PINCH_DIST_THRESHOLD = 0.35   # доля от длины ладони (запястье -> основание среднего пальца)
DRAW_FADE_SECONDS = 10.0      # через сколько секунд нарисованное пропадает
DRAW_COLOR_BGR = (0, 0, 255)  # красный
DRAW_MIN_POINT_DISTANCE = 3   # не копим сотни одинаковых точек неподвижного щипка

STICKER_SIZE_BUCKET = 8
STICKER_ANGLE_BUCKET = 5
STICKER_CACHE_SIZE = 192


def atomic_json_dump(path, data):
    """Записывает JSON атомарно, чтобы аварийное закрытие не оставило
    наполовину записанный файл настроек или калибровки."""
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
            logger.debug("Could not remove temporary JSON: %s", tmp_path, exc_info=True)
        raise


class LatestFrameCapture:
    """Читает камеру в отдельном потоке и хранит только самый свежий кадр.

    GUI никогда не ждёт блокирующий ``VideoCapture.read()``, а устаревшие
    кадры не накапливаются в очереди и не создают растущую задержку.
    """

    def __init__(self, capture):
        self.capture = capture
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._frame = None
        self._frame_id = 0
        self._thread = threading.Thread(
            target=self._run, name="CameraCapture", daemon=True
        )

    def start(self):
        self._thread.start()

    def _run(self):
        while not self._stop_event.is_set():
            ok, frame = self.capture.read()
            if not ok:
                if not self._stop_event.wait(0.02):
                    continue
                break
            with self._lock:
                self._frame = frame
                self._frame_id += 1

    def get_latest(self, after_id):
        with self._lock:
            if self._frame is None or self._frame_id == after_id:
                return after_id, None
            return self._frame_id, self._frame

    def stop(self):
        self._stop_event.set()
        # release() обычно разблокирует ожидающий read() у драйвера камеры.
        try:
            self.capture.release()
        except Exception:
            logger.exception("Could not release camera")
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)


class VirtualCameraSender:
    """Отправляет последний RGB-кадр в виртуальную камеру вне GUI-потока."""

    def __init__(self, width, height, fps=30):
        self.width = width
        self.height = height
        self.fps = fps
        self.events = queue.Queue()
        self._frames = queue.Queue(maxsize=1)
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="VirtualCamera", daemon=True
        )

    @property
    def alive(self):
        return self._thread.is_alive()

    def start(self):
        self._thread.start()

    def submit(self, rgb_frame):
        if rgb_frame is None or self._stop_event.is_set():
            return
        try:
            self._frames.put_nowait(rgb_frame)
        except queue.Full:
            try:
                self._frames.get_nowait()
            except queue.Empty:
                pass
            try:
                self._frames.put_nowait(rgb_frame)
            except queue.Full:
                pass

    def _run(self):
        camera = None
        try:
            camera = pyvirtualcam.Camera(
                width=self.width,
                height=self.height,
                fps=self.fps,
                fmt=pyvirtualcam.PixelFormat.RGB,
            )
            self.events.put(("started", getattr(camera, "device", "OK")))
            while not self._stop_event.is_set():
                try:
                    frame = self._frames.get(timeout=0.2)
                except queue.Empty:
                    continue
                camera.send(frame)
                # Пейсинг остаётся полезным, но теперь спит только этот поток.
                camera.sleep_until_next_frame()
        except Exception as exc:
            logger.exception("Virtual camera worker failed")
            self.events.put(("error", str(exc)))
        finally:
            if camera is not None:
                try:
                    camera.close()
                except Exception:
                    logger.exception("Could not close virtual camera")
            self.events.put(("stopped", None))

    def stop(self):
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1.5)


class StickerTransformCache:
    """Небольшой LRU-кэш масштабированных/повёрнутых стикеров."""

    def __init__(self, max_items=STICKER_CACHE_SIZE):
        self.max_items = max_items
        self._items = OrderedDict()

    def clear(self):
        self._items.clear()

    def get(self, sticker_id, source_bgra, size, angle_deg=None):
        size_bucket = max(20, int(round(size / STICKER_SIZE_BUCKET) * STICKER_SIZE_BUCKET))
        angle_bucket = None
        if angle_deg is not None:
            angle_bucket = int(round(angle_deg / STICKER_ANGLE_BUCKET) * STICKER_ANGLE_BUCKET)
        key = (sticker_id, size_bucket, angle_bucket)
        cached = self._items.pop(key, None)
        if cached is not None:
            self._items[key] = cached
            return cached

        transformed = cv2.resize(
            source_bgra, (size_bucket, size_bucket), interpolation=cv2.INTER_AREA
        )
        if angle_bucket is not None:
            matrix = cv2.getRotationMatrix2D(
                (size_bucket / 2, size_bucket / 2), angle_bucket, 1.0
            )
            transformed = cv2.warpAffine(
                transformed,
                matrix,
                (size_bucket, size_bucket),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=(0, 0, 0, 0),
            )
        self._items[key] = transformed
        while len(self._items) > self.max_items:
            self._items.popitem(last=False)
        return transformed


def _dist2(ax, ay, bx, by):
    """Квадрат расстояния между двумя 2D-точками, без numpy — для пары чисел
    чистый Python заметно (~10-15x на измерениях) быстрее, чем оборачивать их
    в np.array ради одной операции: у numpy тут накладные расходы больше,
    чем сама польза от векторизации."""
    dx, dy = ax - bx, ay - by
    return dx * dx + dy * dy


def is_pinching(lm):
    """Определяет, соединены ли кончики большого и указательного пальцев.
    Возвращает (щипок_ли, средняя_точка_в_нормализованных_координатах)."""
    thumb_x, thumb_y = lm[4].x, lm[4].y
    index_x, index_y = lm[8].x, lm[8].y
    wrist_x, wrist_y = lm[0].x, lm[0].y
    mcp9_x, mcp9_y = lm[9].x, lm[9].y

    scale2 = _dist2(mcp9_x, mcp9_y, wrist_x, wrist_y)
    if scale2 < 1e-12:
        return False, None
    dist2 = _dist2(thumb_x, thumb_y, index_x, index_y)
    mid = ((thumb_x + index_x) / 2, (thumb_y + index_y) / 2)
    return dist2 < (PINCH_DIST_THRESHOLD ** 2) * scale2, mid

# --- Скелет руки для ручной отрисовки ---
HAND_CONNECTIONS = [
    (0, 1), (0, 5), (9, 13), (13, 17), (5, 9), (0, 17),
    (1, 2), (2, 3), (3, 4),
    (5, 6), (6, 7), (7, 8),
    (9, 10), (10, 11), (11, 12),
    (13, 14), (14, 15), (15, 16),
    (17, 18), (18, 19), (19, 20),
]


def ensure_models(status_callback=None, lang="ru"):
    """Скачивает файлы моделей, если их ещё нет. Бросает исключение при неудаче."""
    tr = STRINGS[lang]
    for name, url, path in (
        ("HandLandmarker", HAND_MODEL_URL, HAND_MODEL_PATH),
        ("FaceLandmarker", FACE_MODEL_URL, FACE_MODEL_PATH),
    ):
        if os.path.exists(path) and os.path.getsize(path) > 0:
            continue
        if status_callback:
            status_callback(tr["downloading_model"].format(name=name))
        tmp_path = path + ".part"
        try:
            with urllib.request.urlopen(url, timeout=30) as resp, open(tmp_path, "wb") as out:
                shutil.copyfileobj(resp, out)
            os.replace(tmp_path, path)
        except (urllib.error.URLError, OSError) as e:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise RuntimeError(tr["err_model_download"].format(name=name, url=url, err=e)) from e


def get_finger_states(lm):
    """lm — список из 21 точки (объекты с .x/.y).

    Возвращает кортеж из 5 bool (большой, указательный, средний, безымянный,
    мизинец) — True, если палец разогнут. Каждый палец считается независимо
    от остальных, сравнивая расстояние от кончика до опорной точки с
    расстоянием от среднего сустава этого же пальца до той же точки. Это
    устойчиво к повороту руки в кадре (в отличие от сравнения одних только
    X/Y координат).
    """
    wx, wy = lm[0].x, lm[0].y
    pkx, pky = lm[17].x, lm[17].y
    thresh = 1.05 ** 2  # сравниваем квадраты расстояний — corень не нужен

    # Большой палец — особый случай: сгибается вбок, а не вверх/вниз,
    # поэтому сравниваем расстояние до основания мизинца, а не до запястья.
    thumb_up = _dist2(lm[4].x, lm[4].y, pkx, pky) > _dist2(lm[2].x, lm[2].y, pkx, pky) * thresh

    states = [thumb_up]
    for tip_idx, pip_idx in zip(FINGER_TIPS[1:], FINGER_PIPS[1:]):
        tip_d2 = _dist2(lm[tip_idx].x, lm[tip_idx].y, wx, wy)
        pip_d2 = _dist2(lm[pip_idx].x, lm[pip_idx].y, wx, wy)
        states.append(tip_d2 > pip_d2 * thresh)

    return tuple(states)


def count_raised_fingers(lm):
    """Суммарное число разогнутых пальцев (0-5). См. get_finger_states()."""
    return sum(get_finger_states(lm))


def normalize_hand_vector(lm):
    """Нормализует 21 точку по положению, масштабу и повороту кисти.

    Вектор ``запястье → основание среднего пальца`` всегда направляется
    вверх. Поэтому один шаблон устойчивее распознаётся, даже если человек
    немного повернул руку в кадре.
    """
    arr = np.array([(p.x, p.y, p.z) for p in lm], dtype=np.float32)
    origin = arr[0]
    centered = arr - origin
    palm_x, palm_y = centered[9, 0], centered[9, 1]
    palm_angle = math.atan2(float(palm_y), float(palm_x))
    rotation = (-math.pi / 2.0) - palm_angle
    cos_a, sin_a = math.cos(rotation), math.sin(rotation)
    x = centered[:, 0].copy()
    y = centered[:, 1].copy()
    centered[:, 0] = x * cos_a - y * sin_a
    centered[:, 1] = x * sin_a + y * cos_a

    scale = np.linalg.norm(centered[9])
    if scale < 1e-6:
        scale = 1e-6
    return (centered / scale).ravel()


def classify_by_templates(lm, templates):
    """Сравнивает текущую форму руки со всеми откалиброванными шаблонами
    (словарь {число_пальцев: вектор}) и возвращает (лучшее_число, расстояние)."""
    if not templates:
        return None, None
    vec = normalize_hand_vector(lm)
    best_n, best_dist = None, None
    for n, tmpl in templates.items():
        d = float(np.linalg.norm(vec - tmpl))
        if best_dist is None or d < best_dist:
            best_dist, best_n = d, n
    return best_n, best_dist


def eye_ratio(landmarks, iris_idx, left_idx, right_idx, top_idx, bottom_idx):
    iris = landmarks[iris_idx]
    left, right = landmarks[left_idx], landmarks[right_idx]
    top, bottom = landmarks[top_idx], landmarks[bottom_idx]
    h_span = right.x - left.x
    v_span = bottom.y - top.y
    h_ratio = (iris.x - left.x) / h_span if abs(h_span) > 1e-6 else 0.5
    v_ratio = (iris.y - top.y) / v_span if abs(v_span) > 1e-6 else 0.5
    h_ratio = 0.0 if h_ratio < 0.0 else (1.0 if h_ratio > 1.0 else h_ratio)
    v_ratio = 0.0 if v_ratio < 0.0 else (1.0 if v_ratio > 1.0 else v_ratio)
    return h_ratio, v_ratio


def draw_hand_skeleton(frame, lm, w, h):
    pts = [(int(p.x * w), int(p.y * h)) for p in lm]
    for a, b in HAND_CONNECTIONS:
        cv2.line(frame, pts[a], pts[b], (0, 200, 0), 2)
    for x, y in pts:
        cv2.circle(frame, (x, y), 3, (0, 255, 0), -1)


def draw_corner_counter(frame, text, w, h):
    """Маленький счётчик пальцев в левом нижнем углу кадра (вместо большой наклейки)."""
    x, y = 14, h - 16
    cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (0, 0, 0), 6, cv2.LINE_AA)
    cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (255, 255, 255), 2, cv2.LINE_AA)


def make_placeholder_sticker(n, size=400):
    """Генерирует картинку-заглушку (цветной круг с цифрой), если пользователь
    ещё не положил свою фотографию в images/gesture_N.*."""
    color_bgr = STICKER_PLACEHOLDER_COLORS.get(n, (200, 200, 200))
    color_rgb = (color_bgr[2], color_bgr[1], color_bgr[0])
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = 10
    draw.ellipse([pad, pad, size - pad, size - pad], fill=color_rgb + (230,),
                 outline=(255, 255, 255, 255), width=8)
    font = None
    for font_name in ("arial.ttf", "Arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        try:
            font = ImageFont.truetype(font_name, size // 2)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()
    text = str(n)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1]),
               text, fill=(255, 255, 255, 255), font=font)
    arr = np.array(img)  # RGBA
    return arr[:, :, [2, 1, 0, 3]].copy()  # -> BGRA для OpenCV


def find_sticker_file(n):
    """Ищет images/gesture_N.<любое из расширений>, регистр не важен."""
    if not os.path.isdir(IMAGES_DIR):
        return None
    target = f"gesture_{n}"
    for fname in os.listdir(IMAGES_DIR):
        stem, ext = os.path.splitext(fname)
        if stem.lower() == target and ext.lower() in STICKER_EXTENSIONS:
            return os.path.join(IMAGES_DIR, fname)
    return None


def load_sticker_images():
    """Загружает images/gesture_1..5.*, либо плейсхолдер, если файл не найден.
    Возвращает (stickers, is_custom) — is_custom[n]=True, если это реальное
    фото пользователя, а не сгенерированная заглушка."""
    stickers, is_custom = {}, {}
    for n in range(1, 6):
        path = find_sticker_file(n)
        loaded = None
        if path:
            try:
                with Image.open(path) as source_image:
                    pil_img = source_image.convert("RGBA")
                arr = np.array(pil_img)
                loaded = arr[:, :, [2, 1, 0, 3]].copy()
            except (OSError, ValueError):
                logger.warning("Could not load sticker %s", path, exc_info=True)
                loaded = None
        if loaded is not None:
            stickers[n] = loaded
            is_custom[n] = True
        else:
            stickers[n] = make_placeholder_sticker(n)
            is_custom[n] = False
    return stickers, is_custom


def alpha_blend(frame, overlay_bgra, x1, y1):
    """Накладывает BGRA-картинку overlay_bgra на frame (BGR) в точке (x1,y1)
    с учётом альфа-канала и обрезкой по границам кадра."""
    h_f, w_f = frame.shape[:2]
    oh, ow = overlay_bgra.shape[:2]
    x2, y2 = x1 + ow, y1 + oh

    ox1, oy1 = 0, 0
    if x1 < 0:
        ox1 = -x1
        x1 = 0
    if y1 < 0:
        oy1 = -y1
        y1 = 0
    ox2 = ow - max(0, x2 - w_f)
    oy2 = oh - max(0, y2 - h_f)
    x2 = min(x2, w_f)
    y2 = min(y2, h_f)

    if x2 <= x1 or y2 <= y1 or ox2 <= ox1 or oy2 <= oy1:
        return

    overlay_crop = overlay_bgra[oy1:oy2, ox1:ox2]
    alpha = overlay_crop[:, :, 3:4].astype(np.float32) / 255.0
    roi = frame[y1:y2, x1:x2].astype(np.float32)
    fg = overlay_crop[:, :, :3].astype(np.float32)
    blended = fg * alpha + roi * (1 - alpha)
    frame[y1:y2, x1:x2] = blended.astype(np.uint8)


def overlay_sticker_on_hand(
    frame,
    lm,
    w,
    h,
    sticker_bgra,
    scale_factor=1.3,
    rotate=True,
    sticker_id=None,
    transform_cache=None,
):
    """«Крепит» картинку к руке: центр — между запястьем и основанием среднего
    пальца, размер и (опционально) поворот подстраиваются под положение руки."""
    ox, oy = lm[0].x * w, lm[0].y * h
    rx, ry = lm[9].x * w, lm[9].y * h
    vx, vy = rx - ox, ry - oy
    dist = math.hypot(vx, vy)
    if dist < 2:
        return

    requested_size = max(20, int(dist * scale_factor))
    angle_deg = -(math.degrees(math.atan2(vy, vx)) + 90) if rotate else None
    if transform_cache is not None and sticker_id is not None:
        resized = transform_cache.get(sticker_id, sticker_bgra, requested_size, angle_deg)
    else:
        resized = cv2.resize(
            sticker_bgra, (requested_size, requested_size), interpolation=cv2.INTER_AREA
        )
        if angle_deg is not None:
            matrix = cv2.getRotationMatrix2D(
                (requested_size / 2, requested_size / 2), angle_deg, 1.0
            )
            resized = cv2.warpAffine(
                resized,
                matrix,
                (requested_size, requested_size),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=(0, 0, 0, 0),
            )

    size = resized.shape[0]
    x1 = int((ox + rx) / 2) - size // 2
    y1 = int((oy + ry) / 2) - size // 2
    alpha_blend(frame, resized, x1, y1)


HAND_GUIDE_SOURCE_SIZE = 360
HAND_GUIDE_RENDER_SIZE = 270
HAND_GUIDE_OFFSET = (15, 25)
# Зоны соответствуют порядку get_finger_states(): большой, указательный,
# средний, безымянный, мизинец. Координаты заданы в исходных 360x360.
HAND_GUIDE_FINGER_ZONES = (
    ((30, 135), (112, 135), (112, 275), (30, 275)),
    ((88, 32), (160, 32), (160, 248), (88, 248)),
    ((136, 0), (216, 0), (216, 194), (136, 194)),
    ((192, 15), (273, 15), (273, 194), (192, 194)),
    ((249, 43), (330, 43), (330, 210), (249, 210)),
)
HAND_GUIDE_NUMBER_POINTS = ((70, 158), (124, 55), (178, 15), (232, 38), (286, 67))


def load_hand_reference_rgba():
    """Загружает присланную ладонь и убирает запечённую шахматную подложку."""
    try:
        with Image.open(HAND_REFERENCE_PATH) as source_image:
            image = source_image.convert("RGBA")
    except (OSError, ValueError):
        logger.exception("Could not load hand reference image: %s", HAND_REFERENCE_PATH)
        # Резервная схема нужна только если пользователь случайно удалил asset.
        image = Image.new("RGBA", (HAND_GUIDE_SOURCE_SIZE, HAND_GUIDE_SOURCE_SIZE), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((42, 145, 320, 350), radius=80, outline="black", width=18)
        for box in ((91, 43, 151, 247), (145, 3, 211, 188),
                    (199, 23, 269, 190), (257, 52, 320, 204)):
            draw.rounded_rectangle(box, radius=28, outline="black", width=18)
        return image

    gray = np.asarray(image.convert("L"), dtype=np.int16)
    # Фон состоит из белых/светло-серых клеток, контур — почти чёрный.
    # Порог сохраняет сглаженные края, но полностью убирает шахматку.
    alpha = np.clip((190 - gray) * 4, 0, 255).astype(np.uint8)
    rgba = np.zeros((image.height, image.width, 4), dtype=np.uint8)
    rgba[:, :, :3] = (16, 16, 18)
    rgba[:, :, 3] = alpha
    return Image.fromarray(rgba, "RGBA")


def render_hand_reference(base_image, pattern, dark=False):
    """Красит контур выбранных пальцев в зелёный и добавляет мягкое свечение."""
    background = (43, 43, 43, 255) if dark else (245, 245, 245, 255)
    canvas = Image.new("RGBA", base_image.size, background)

    zone_mask = Image.new("L", base_image.size, 0)
    zone_draw = ImageDraw.Draw(zone_mask)
    for enabled, polygon in zip(pattern, HAND_GUIDE_FINGER_ZONES):
        if enabled:
            zone_draw.polygon(polygon, fill=255)

    base_alpha = base_image.getchannel("A")
    selected_alpha = Image.fromarray(
        np.minimum(np.asarray(base_alpha), np.asarray(zone_mask)).astype(np.uint8), "L"
    )
    glow_alpha = selected_alpha.filter(ImageFilter.GaussianBlur(radius=8)).point(
        lambda value: min(125, int(value * 0.65))
    )
    glow = Image.new("RGBA", base_image.size, (42, 255, 105, 0))
    glow.putalpha(glow_alpha)
    canvas = Image.alpha_composite(canvas, glow)

    colored = np.asarray(base_image).copy()
    if dark:
        visible = colored[:, :, 3] > 0
        colored[visible, 0:3] = (218, 218, 222)
    selected = np.asarray(selected_alpha) > 0
    colored[selected, 0] = 35
    colored[selected, 1] = 235
    colored[selected, 2] = 92
    canvas = Image.alpha_composite(canvas, Image.fromarray(colored, "RGBA"))
    return canvas.resize(
        (HAND_GUIDE_RENDER_SIZE, HAND_GUIDE_RENDER_SIZE), Image.Resampling.LANCZOS
    )


class HandTrackApp:
    def __init__(self, root):
        self.root = root
        self.lang_var = tk.StringVar(value=_STARTUP_LANG)
        self.root.title(self.tr("app_title"))
        self.root.resizable(True, True)
        self.root.minsize(860, 620)
        self._preview_box = (CAPTURE_WIDTH, CAPTURE_HEIGHT)

        self.dark_mode_var = tk.BooleanVar(value=False)
        self.fast_mode_var = tk.BooleanVar(value=True)
        self.resolution_var = tk.StringVar(value=f"{CAPTURE_WIDTH}x{CAPTURE_HEIGHT}")
        self._style = ttk.Style(self.root)
        self._default_theme = self._style.theme_use()
        self._default_root_bg = self.root.cget("bg")

        self.running = False
        self.cap = None
        self.capture_reader = None
        self._last_capture_id = 0
        self._start_time = time.monotonic()
        self._last_ts_ms = -1
        self._update_generation = 0
        self._preview_hidden_shown = False

        self._inference_lock = threading.Lock()
        self._latest_hand_result = None
        self._latest_hand_result_ts = -1
        self._latest_hand_received_at = 0.0
        self._latest_face_result = None
        self._latest_face_result_ts = -1
        self._latest_face_received_at = 0.0
        self._last_hand_result_used_ts = -1
        self._last_face_result_used_ts = -1
        self._last_hand_submit_at = 0.0
        self._last_face_submit_at = 0.0

        self.hide_face_var = tk.BooleanVar(value=False)
        self.visualize_var = tk.BooleanVar(value=True)
        self.gaze_var = tk.BooleanVar(value=True)
        self.threshold_var = tk.DoubleVar(value=0.55)
        self.attach_photo_var = tk.BooleanVar(value=True)
        self.rotate_sticker_var = tk.BooleanVar(value=True)
        self.sticker_scale_var = tk.DoubleVar(value=1.3)
        self.show_counter_var = tk.BooleanVar(value=True)
        self.preview_visible_var = tk.BooleanVar(value=True)
        self.vcam_var = tk.BooleanVar(value=False)
        self._vcam_sender = None
        self.draw_enabled_var = tk.BooleanVar(value=True)
        self.draw_points = defaultdict(deque)
        self._was_pinching = defaultdict(bool)

        # Пользовательские жесты: точное совпадение с состоянием пальцев
        # (кортеж из 5 bool), заданным во вкладке "Мои жесты".
        self.custom_gestures_enabled_var = tk.BooleanVar(value=True)
        self.custom_gestures = []
        self._last_hand_pattern = None
        self._last_primary_hand_key = None
        self._last_pattern_trigger_time = {}

        # Запись комбинации клавиш кнопкой "🎹 Записать комбинацию".
        self._capture_mode = None      # None, "hotkey" или "key"
        self._capture_pressed = set()
        self._capture_session = 0

        self.afk_enabled_var = tk.BooleanVar(value=True)
        self.afk_timeout_var = tk.DoubleVar(value=AFK_DEFAULT_TIMEOUT)
        self._face_last_seen = time.monotonic()

        self.stickers, self.stickers_custom = load_sticker_images()
        self.sticker_transform_cache = StickerTransformCache()
        self._hand_reference_base = load_hand_reference_rgba()

        self.status_var = tk.StringVar(value="")
        self.gesture_var = tk.StringVar(value="")
        self.gaze_status_var = tk.StringVar(value="")
        self.hand_calib_var = tk.StringVar(value="")
        self.gaze_calib_var = tk.StringVar(value="")
        self.sticker_status_var = tk.StringVar(value="")

        self.gaze_calibrated = False
        self.gaze_coeffs_x = None
        self.gaze_coeffs_y = None
        self.gaze_calibration_active = False
        self.calib_win = None
        self.calib_canvas = None
        self.calib_index = 0
        self.calib_samples = []
        self.calib_phase = None
        self.calib_phase_start = 0
        self.calib_targets = []
        self._calib_results = []

        self.hand_templates = {}
        self.hand_calibration_active = False
        self.hand_wizard_step = 1
        self.hand_wizard_templates = {}
        self.hand_calib_phase = None
        self.hand_calib_phase_start = 0
        self.hand_calib_samples = []

        self._load_gaze_calibration()
        self._load_hand_calibration()
        self._load_custom_gestures()
        self._load_settings()
        self.root.title(self.tr("app_title"))  # на случай, если язык поменялся при загрузке настроек
        self._refresh_dynamic_labels()

        self._build_ui()
        self.apply_theme()

        hand_options = HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=HAND_MODEL_PATH),
            running_mode=RunningMode.LIVE_STREAM,
            num_hands=2,
            min_hand_detection_confidence=0.6,
            min_hand_presence_confidence=0.6,
            min_tracking_confidence=0.6,
            result_callback=self._on_hand_result,
        )
        self.hand_landmarker = HandLandmarker.create_from_options(hand_options)

        face_options = FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=FACE_MODEL_PATH),
            running_mode=RunningMode.LIVE_STREAM,
            num_faces=1,
            min_face_detection_confidence=0.6,
            min_face_presence_confidence=0.6,
            min_tracking_confidence=0.6,
            output_face_blendshapes=False,
            output_facial_transformation_matrixes=False,
            result_callback=self._on_face_result,
        )
        self.face_landmarker = FaceLandmarker.create_from_options(face_options)

    # -------------------------------------------------------------- i18n ----
    def tr(self, key, **kwargs):
        text = STRINGS[self.lang_var.get()].get(key, key)
        return text.format(**kwargs) if kwargs else text

    # ----------------------------------------------- Асинхронные результаты MediaPipe ----
    def _on_hand_result(self, result, _output_image, timestamp_ms):
        with self._inference_lock:
            self._latest_hand_result = result
            self._latest_hand_result_ts = timestamp_ms
            self._latest_hand_received_at = time.monotonic()

    def _on_face_result(self, result, _output_image, timestamp_ms):
        with self._inference_lock:
            self._latest_face_result = result
            self._latest_face_result_ts = timestamp_ms
            self._latest_face_received_at = time.monotonic()

    def _inference_snapshot(self):
        with self._inference_lock:
            return (
                self._latest_hand_result,
                self._latest_hand_result_ts,
                self._latest_hand_received_at,
                self._latest_face_result,
                self._latest_face_result_ts,
                self._latest_face_received_at,
            )

    @staticmethod
    def _hand_entries(hand_result):
        """Возвращает руки со стабильными ключами Left/Right.

        MediaPipe может менять порядок элементов между кадрами; handedness
        не даёт линии одной руки случайно продолжиться точками другой.
        """
        if not hand_result or not hand_result.hand_landmarks:
            return []
        entries = []
        used = set()
        handedness = getattr(hand_result, "handedness", None) or []
        for index, landmarks in enumerate(hand_result.hand_landmarks[:2]):
            label = ""
            if index < len(handedness) and handedness[index]:
                category = handedness[index][0]
                label = (getattr(category, "category_name", "")
                         or getattr(category, "display_name", ""))
            if label not in ("Left", "Right") or label in used:
                label = f"Hand{index}"
            used.add(label)
            entries.append((label, landmarks))
        priority = {"Right": 0, "Left": 1}
        entries.sort(key=lambda item: (priority.get(item[0], 2), item[0]))
        return entries

    def _toggle_language(self):
        self.lang_var.set("en" if self.lang_var.get() == "ru" else "ru")
        self._refresh_dynamic_labels()
        self._rebuild_ui()
        self._save_settings()

    def _rebuild_ui(self):
        finger_pattern = None
        if hasattr(self, "finger_toggle_vars"):
            finger_pattern = tuple(variable.get() for variable in self.finger_toggle_vars)
        if self._capture_mode is not None:
            self._finish_key_capture(cancel=True)
        for child in list(self.root.winfo_children()):
            child.destroy()
        self._preview_hidden_shown = False
        self._build_ui()
        if finger_pattern is not None:
            for variable, value in zip(self.finger_toggle_vars, finger_pattern):
                variable.set(value)
            self._draw_hand_diagram()
        self.apply_theme()

    def _refresh_dynamic_labels(self):
        """Перезаполняет содержимое StringVar-ов на текущем языке — нужно и
        при первом запуске (после загрузки сохранённого языка), и при
        переключении языка на лету (виджеты только показывают то, что уже
        лежит в переменной, сама переменная не переводится автоматически)."""
        if not self.running:
            self.status_var.set(self.tr("status_stopped"))
        self.gesture_var.set(self.tr("gesture_no_hand"))
        self.gaze_status_var.set(self.tr("gaze_status_off"))
        if self.gaze_calibrated:
            self.gaze_calib_var.set(self.tr("gaze_calib_done_label"))
        else:
            self.gaze_calib_var.set(self.tr("gaze_calib_reset_label"))
        if self.hand_templates:
            done = ", ".join(str(n) for n in sorted(self.hand_templates))
            self.hand_calib_var.set(self.tr("hand_calib_prev_done", list=done))
        else:
            self.hand_calib_var.set(self.tr("hand_calib_reset_label"))
        self._update_sticker_status_label()

    # ---------------------------------------------------------------- UI ----
    def _build_ui(self):
        self.root.title(self.tr("app_title"))
        self.root.grid_rowconfigure(0, weight=0)
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        top_bar = ttk.Frame(self.root, padding=(8, 4))
        top_bar.grid(row=0, column=0, sticky="ew")
        ttk.Checkbutton(top_bar, text=self.tr("dark_theme"), variable=self.dark_mode_var,
                         command=self.apply_theme).pack(side="left")
        ttk.Button(top_bar, text=self.tr("lang_toggle"),
                   command=self._toggle_language).pack(side="left", padx=(8, 0))

        notebook = ttk.Notebook(self.root)
        notebook.grid(row=1, column=0, sticky="nsew")
        tab_camera = ttk.Frame(notebook)
        tab_gestures = ttk.Frame(notebook)
        notebook.add(tab_camera, text=self.tr("tab_camera"))
        notebook.add(tab_gestures, text=self.tr("tab_gestures"))

        # =============================================================== Вкладка "Камера" ====
        main = ttk.Frame(tab_camera, padding=8)
        main.pack(fill="both", expand=True)
        main.grid_rowconfigure(0, weight=1)
        main.grid_columnconfigure(0, weight=1)   # превью — растягивается
        main.grid_columnconfigure(1, weight=0)   # боковая панель — фикс. ширина

        preview_frame = ttk.LabelFrame(main, text=self.tr("preview_frame"), padding=6)
        preview_frame.grid(row=0, column=0, rowspan=6, sticky="nsew")
        preview_frame.grid_rowconfigure(0, weight=1)
        preview_frame.grid_columnconfigure(0, weight=1)
        # ВАЖНО: без этого окно "расползается" само по себе при включённом
        # предпросмотре. Причина — обратная связь по размеру: без
        # grid_propagate(False) размер preview_frame подстраивается под
        # размер картинки внутри video_label, а мы каждый кадр подгоняем
        # картинку под текущий размер preview_frame — получается петля,
        # где окно на пару пикселей растёт с каждым кадром. Явно задаём
        # стартовый размер и отключаем автоподстройку контейнера под
        # содержимое: дальше его размер определяется только grid-весом
        # (сеткой) со стороны родителя, то есть только пользователь,
        # растягивая окно, может его менять.
        preview_frame.configure(width=CAPTURE_WIDTH // 2 + 250, height=CAPTURE_HEIGHT // 2 + 60)
        preview_frame.grid_propagate(False)
        standby_text = self.tr("standby_start") if not self.running else ""
        self.video_label = ttk.Label(preview_frame, anchor="center", justify="center",
                                      text=standby_text)
        self.video_label.grid(row=0, column=0, sticky="nsew")
        self.video_label.bind("<Configure>", self._on_preview_resize)

        side_container = ttk.Frame(main)
        side_container.grid(row=0, column=1, sticky="nsew")
        side_container.grid_rowconfigure(0, weight=1)

        side_canvas = tk.Canvas(side_container, width=250, highlightthickness=0)
        self.side_canvas = side_canvas
        self._default_side_canvas_bg = side_canvas.cget("bg")
        side_scrollbar = ttk.Scrollbar(side_container, orient="vertical", command=side_canvas.yview)
        side_canvas.configure(yscrollcommand=side_scrollbar.set)
        side_canvas.grid(row=0, column=0, sticky="nsew")
        side_scrollbar.grid(row=0, column=1, sticky="ns")

        side = ttk.Frame(side_canvas, padding=(10, 0))
        side_window = side_canvas.create_window((0, 0), window=side, anchor="nw")

        def _on_side_configure(event):
            side_canvas.configure(scrollregion=side_canvas.bbox("all"))
        side.bind("<Configure>", _on_side_configure)

        def _on_mousewheel(event):
            # Windows/macOS: event.delta кратен 120; Linux: приходит как Button-4/5
            side_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _on_mousewheel_linux(event, direction):
            side_canvas.yview_scroll(direction, "units")

        def _bind_mousewheel(event):
            side_canvas.bind_all("<MouseWheel>", _on_mousewheel)
            side_canvas.bind_all("<Button-4>", lambda e: _on_mousewheel_linux(e, -1))
            side_canvas.bind_all("<Button-5>", lambda e: _on_mousewheel_linux(e, 1))

        def _unbind_mousewheel(event):
            side_canvas.unbind_all("<MouseWheel>")
            side_canvas.unbind_all("<Button-4>")
            side_canvas.unbind_all("<Button-5>")

        # Прокрутка колесом работает, только пока курсор над панелью — иначе
        # она бы мешала прокрутке других частей окна, если бы такие были.
        side_canvas.bind("<Enter>", _bind_mousewheel)
        side_canvas.bind("<Leave>", _unbind_mousewheel)

        gazemap_frame = ttk.LabelFrame(side, text=self.tr("gazemap_frame"), padding=4)
        gazemap_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.gaze_canvas = tk.Canvas(gazemap_frame, width=180, height=100, bg="#eee",
                                      highlightthickness=1, highlightbackground="#999")
        self.gaze_canvas.pack(anchor="w")
        self.gaze_dot = self.gaze_canvas.create_oval(85, 45, 95, 55, fill="red", outline="")

        controls = ttk.LabelFrame(side, text=self.tr("controls_frame"), padding=6)
        controls.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        btn_row = ttk.Frame(controls)
        btn_row.grid(row=0, column=0, sticky="ew")
        self.start_btn = ttk.Button(btn_row, text=self.tr("start_btn"), command=self.start)
        self.start_btn.grid(row=0, column=0, padx=2)
        self.stop_btn = ttk.Button(btn_row, text=self.tr("stop_btn"), command=self.stop,
                                    state="disabled" if not self.running else "normal")
        self.stop_btn.grid(row=0, column=1, padx=2)
        if self.running:
            self.start_btn.config(state="disabled")

        res_row = ttk.Frame(controls)
        res_row.grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Label(res_row, text=self.tr("resolution_label")).pack(side="left")
        ttk.Combobox(res_row, textvariable=self.resolution_var, state="readonly", width=11,
                     values=["640x480", "1280x720", "1920x1080"]).pack(side="left", padx=(4, 0))

        ttk.Checkbutton(controls, text=self.tr("hide_face_cb"),
                         variable=self.hide_face_var).grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Checkbutton(controls, text=self.tr("visualize_cb"),
                         variable=self.visualize_var).grid(row=3, column=0, sticky="w")
        ttk.Checkbutton(controls, text=self.tr("gaze_cb"),
                         variable=self.gaze_var).grid(row=4, column=0, sticky="w")
        ttk.Checkbutton(controls, text=self.tr("counter_cb"),
                         variable=self.show_counter_var).grid(row=5, column=0, sticky="w")
        ttk.Checkbutton(controls, text=self.tr("preview_cb"),
                         variable=self.preview_visible_var).grid(row=6, column=0, sticky="w")
        ttk.Checkbutton(controls, text=self.tr("fastmode_cb"),
                         variable=self.fast_mode_var).grid(row=7, column=0, sticky="w")
        ttk.Checkbutton(controls, text=self.tr("draw_cb"),
                         variable=self.draw_enabled_var).grid(row=8, column=0, sticky="w")
        ttk.Checkbutton(controls, text=self.tr("afk_cb"),
                         variable=self.afk_enabled_var).grid(row=9, column=0, sticky="w")
        ttk.Label(controls, text=self.tr("afk_timeout_label")).grid(row=10, column=0, sticky="w", pady=(4, 0))
        ttk.Scale(controls, from_=2.0, to=30.0, variable=self.afk_timeout_var,
                  orient="horizontal").grid(row=11, column=0, sticky="ew")

        ttk.Label(controls, text=self.tr("threshold_label")).grid(row=12, column=0, sticky="w", pady=(6, 0))
        ttk.Scale(controls, from_=0.2, to=1.2, variable=self.threshold_var,
                  orient="horizontal").grid(row=13, column=0, sticky="ew")

        vcam_frame = ttk.LabelFrame(side, text=self.tr("vcam_frame"), padding=6)
        vcam_frame.grid(row=5, column=0, sticky="ew", pady=(0, 8))
        vcam_state = "normal" if VCAM_AVAILABLE else "disabled"
        ttk.Checkbutton(vcam_frame, text=self.tr("vcam_cb"),
                         variable=self.vcam_var, state=vcam_state).grid(row=0, column=0, sticky="w")
        note = self.tr("vcam_note_ok") if VCAM_AVAILABLE else self.tr("vcam_note_missing")
        ttk.Label(vcam_frame, text=note, wraplength=220, foreground="#555").grid(
            row=1, column=0, sticky="w", pady=(4, 0))

        sticker_frame = ttk.LabelFrame(side, text=self.tr("sticker_frame"), padding=6)
        sticker_frame.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        ttk.Checkbutton(sticker_frame, text=self.tr("attach_cb"),
                         variable=self.attach_photo_var).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(sticker_frame, text=self.tr("rotate_cb"),
                         variable=self.rotate_sticker_var).grid(row=1, column=0, sticky="w")
        ttk.Label(sticker_frame, text=self.tr("sticker_size_label")).grid(row=2, column=0, sticky="w", pady=(4, 0))
        ttk.Scale(sticker_frame, from_=0.4, to=3.0, variable=self.sticker_scale_var,
                  orient="horizontal").grid(row=3, column=0, sticky="ew")
        ttk.Button(sticker_frame, text=self.tr("open_folder_btn"),
                   command=self.open_images_folder).grid(row=4, column=0, sticky="ew", pady=(4, 0))
        ttk.Button(sticker_frame, text=self.tr("reload_stickers_btn"),
                   command=self.reload_stickers).grid(row=5, column=0, sticky="ew", pady=2)
        ttk.Label(sticker_frame, text=self.tr("sticker_hint"),
                  wraplength=220, foreground="#555").grid(row=6, column=0, sticky="w", pady=(4, 0))
        ttk.Label(sticker_frame, textvariable=self.sticker_status_var,
                  wraplength=220, foreground="#555").grid(row=7, column=0, sticky="w", pady=(4, 0))

        calib = ttk.LabelFrame(side, text=self.tr("calib_frame"), padding=6)
        calib.grid(row=2, column=0, sticky="ew", pady=(0, 8))

        ttk.Button(calib, text=self.tr("gaze_calib_btn"),
                   command=self.start_gaze_calibration).grid(row=0, column=0, sticky="ew", pady=2)
        ttk.Button(calib, text=self.tr("gaze_calib_reset_btn"),
                   command=self.reset_gaze_calibration).grid(row=1, column=0, sticky="ew", pady=2)
        ttk.Label(calib, textvariable=self.gaze_calib_var, wraplength=220,
                  foreground="#555").grid(row=2, column=0, sticky="w", pady=(2, 8))

        ttk.Button(calib, text=self.tr("hand_calib_btn"),
                   command=self.start_hand_calibration).grid(row=3, column=0, sticky="ew", pady=2)
        ttk.Button(calib, text=self.tr("hand_calib_cancel_btn"),
                   command=self.cancel_hand_calibration).grid(row=4, column=0, sticky="ew", pady=2)
        ttk.Button(calib, text=self.tr("hand_calib_reset_btn"),
                   command=self.reset_hand_calibration).grid(row=5, column=0, sticky="ew", pady=2)
        ttk.Label(calib, textvariable=self.hand_calib_var, wraplength=220,
                  foreground="#555").grid(row=6, column=0, sticky="w")

        status = ttk.LabelFrame(side, text=self.tr("status_frame"), padding=6)
        status.grid(row=3, column=0, sticky="ew")
        ttk.Label(status, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        ttk.Label(status, textvariable=self.gesture_var).grid(row=1, column=0, sticky="w")
        ttk.Label(status, textvariable=self.gaze_status_var).grid(row=2, column=0, sticky="w")

        # Ширина прокручиваемой панели фиксируется один раз, под её реальный
        # минимально нужный размер (после того как все виджеты построены) —
        # без этого при подгонке "на лету" под ширину видимого окна прокрутки
        # содержимое могло обрезаться или "уезжать" вбок из-за центрирования
        # некоторых виджетов внутри более широкой колонки.
        side.update_idletasks()
        panel_width = side.winfo_reqwidth()
        side_canvas.configure(width=panel_width)
        side_canvas.itemconfig(side_window, width=panel_width)

        # =============================================================== Вкладка "Мои жесты" ====
        gest_frame = ttk.Frame(tab_gestures, padding=12)
        gest_frame.pack(fill="both", expand=True)

        ttk.Label(gest_frame, text=self.tr("gesture_designer_intro"), wraplength=760,
                  justify="left").pack(anchor="w", pady=(0, 10))

        body = ttk.Frame(gest_frame)
        body.pack(fill="both", expand=True)

        left_col = ttk.Frame(body)
        left_col.pack(side="left", anchor="n", padx=(0, 20))

        ttk.Label(left_col, text=self.tr("gesture_hand_hint")).pack(anchor="center", pady=(0, 4))
        self.hand_canvas = tk.Canvas(left_col, width=300, height=310, bg="#f5f5f5",
                                      highlightthickness=1, highlightbackground="#999")
        self.hand_canvas.pack()
        try:
            self.hand_canvas.configure(cursor="hand2")
        except tk.TclError:
            pass
        self.hand_canvas.bind("<Button-1>", self._on_hand_canvas_click)
        self.finger_toggle_vars = [tk.BooleanVar(value=False) for _ in range(5)]
        self._draw_hand_diagram()

        finger_switches = ttk.Frame(left_col)
        finger_switches.pack(fill="x", pady=(6, 0))
        finger_keys = ("finger_thumb", "finger_index", "finger_middle",
                       "finger_ring", "finger_pinky")
        for index, key in enumerate(finger_keys):
            ttk.Checkbutton(
                finger_switches,
                text=f"{index + 1}. {self.tr(key)}",
                variable=self.finger_toggle_vars[index],
                command=self._draw_hand_diagram,
            ).grid(row=index // 2, column=index % 2, sticky="w", padx=(0, 12))

        ttk.Checkbutton(left_col, text=self.tr("custom_enabled_cb"),
                         variable=self.custom_gestures_enabled_var).pack(anchor="w", pady=(10, 0))

        right_col = ttk.Frame(body)
        right_col.pack(side="left", anchor="n", fill="x", expand=True)

        ttk.Label(right_col, text=self.tr("custom_name_label")).grid(row=0, column=0, sticky="w")
        self.gesture_name_var = tk.StringVar()
        ttk.Entry(right_col, textvariable=self.gesture_name_var, width=26).grid(
            row=0, column=1, sticky="w", padx=(6, 0))

        ttk.Label(right_col, text=self.tr("custom_action_label")).grid(row=1, column=0, sticky="w", pady=(6, 0))
        action_keys = ["toggle_hide_face", "screenshot", "toggle_preview", "hotkey", "key",
                       "media_playpause", "volume_up", "volume_down", "mute", "run", "open"]
        action_display = [self.tr(f"action_{k}") for k in action_keys]
        self._action_key_by_display = dict(zip(action_display, action_keys))
        self.action_display_var = tk.StringVar(value=action_display[0])
        action_combo = ttk.Combobox(right_col, textvariable=self.action_display_var, state="readonly",
                                     values=action_display, width=28)
        action_combo.grid(row=1, column=1, sticky="w", padx=(6, 0), pady=(6, 0))

        ttk.Label(right_col, text=self.tr("custom_param_label")).grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.gesture_param_var = tk.StringVar()
        param_entry = ttk.Entry(right_col, textvariable=self.gesture_param_var, width=28)
        param_entry.grid(row=2, column=1, sticky="w", padx=(6, 0), pady=(6, 0))

        self.capture_btn = ttk.Button(right_col, text=self.tr("custom_capture_btn"),
                                       command=self._toggle_key_capture)
        self.capture_btn.grid(row=3, column=1, sticky="w", padx=(6, 0), pady=(4, 0))

        self.gesture_hint_var = tk.StringVar(value=self.tr(f"hint_{action_keys[0]}"))
        ttk.Label(right_col, textvariable=self.gesture_hint_var, foreground="#777").grid(
            row=4, column=1, sticky="w", padx=(6, 0))

        def _on_action_change(event=None):
            key = self._action_key_by_display.get(self.action_display_var.get(), action_keys[0])
            self.gesture_hint_var.set(self.tr(f"hint_{key}"))
            needs_param = key in ("hotkey", "key", "run", "open")
            param_entry.configure(state="normal" if needs_param else "disabled")
            needs_capture = key in ("hotkey", "key")
            self.capture_btn.configure(state="normal" if needs_capture else "disabled")
            if not needs_capture and self._capture_mode is not None:
                self._finish_key_capture(cancel=True)
        action_combo.bind("<<ComboboxSelected>>", _on_action_change)
        _on_action_change()

        ttk.Button(right_col, text=self.tr("custom_add_btn"),
                   command=self._add_gesture_binding).grid(row=5, column=0, columnspan=2, sticky="ew", pady=(10, 0))

        list_frame = ttk.LabelFrame(gest_frame, text=self.tr("custom_frame"), padding=6)
        list_frame.pack(fill="both", expand=True, pady=(14, 0))
        self.custom_gesture_list_frame = ttk.Frame(list_frame)
        self.custom_gesture_list_frame.pack(fill="both", expand=True)
        self._rebuild_custom_gesture_list()

    # -------------------------------------------------------------- Тема ----
    def apply_theme(self):
        style = self._style
        dark = self.dark_mode_var.get()

        if not dark:
            # Возврат к исходной системной теме — настройки цветов, сделанные
            # для 'clam' ниже, привязаны к теме 'clam' и не затрагивают
            # исходную тему при переключении обратно.
            style.theme_use(self._default_theme)
            self.root.configure(bg=self._default_root_bg)
            self.gaze_canvas.configure(bg="#eee", highlightbackground="#999")
            self.side_canvas.configure(bg=self._default_side_canvas_bg)
            self._draw_hand_diagram()
            return

        bg, bg_alt, fg, trough, sel = "#1e1e1e", "#2b2b2b", "#e6e6e6", "#3a3a3a", "#3a7bd5"

        # 'clam' — единственная встроенная тема, которая по-настоящему рисует
        # виджеты сама (а не делегирует нативному Windows/GTK renderer'у),
        # поэтому только в ней цвета из style.configure реально применяются.
        style.theme_use("clam")
        style.configure(".", background=bg, foreground=fg, fieldbackground=bg_alt)
        for cls in ("TFrame", "TLabelframe", "TLabel", "TCheckbutton"):
            style.configure(cls, background=bg, foreground=fg)
        style.configure("TLabelframe.Label", background=bg, foreground=fg)
        style.map("TCheckbutton",
                  background=[("active", bg)],
                  foreground=[("active", fg)],
                  indicatorcolor=[("selected", sel), ("!selected", bg_alt)])
        style.configure("TButton", background=bg_alt, foreground=fg, bordercolor=trough)
        style.map("TButton", background=[("active", sel), ("pressed", sel)])
        style.configure("TScale", background=bg, troughcolor=trough)
        style.configure("Vertical.TScrollbar", background=bg_alt, troughcolor=bg, arrowcolor=fg)
        style.configure("Horizontal.TScrollbar", background=bg_alt, troughcolor=bg, arrowcolor=fg)

        self.root.configure(bg=bg)
        self.gaze_canvas.configure(bg=bg_alt, highlightbackground=fg)
        self.side_canvas.configure(bg=bg)
        self._draw_hand_diagram()

    # -------------------------------------------------------------- Старт/Стоп ----
    def start(self):
        if self.running:
            return
        self.cap = cv2.VideoCapture(0, cv2.CAP_DSHOW if os.name == "nt" else 0)
        if not self.cap.isOpened():
            self.cap.release()
            self.cap = None
            messagebox.showerror(self.tr("err_title"), self.tr("err_camera"))
            return
        req_w, req_h = self._parse_resolution()
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, req_w)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, req_h)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        actual_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.capture_reader = LatestFrameCapture(self.cap)
        self.capture_reader.start()
        self._last_capture_id = 0
        self._face_last_seen = time.monotonic()
        self._last_hand_submit_at = 0.0
        self._last_face_submit_at = 0.0
        self._last_hand_result_used_ts = -1
        self._last_face_result_used_ts = -1
        with self._inference_lock:
            self._latest_hand_result = None
            self._latest_face_result = None
            self._latest_hand_result_ts = -1
            self._latest_face_result_ts = -1
            self._latest_hand_received_at = 0.0
            self._latest_face_received_at = 0.0
        self.running = True
        self._update_generation += 1
        generation = self._update_generation
        note = "" if (actual_w, actual_h) == (req_w, req_h) else \
            self.tr("status_running_mismatch_note", w=req_w, h=req_h)
        self.status_var.set(self.tr("status_running", w=actual_w, h=actual_h, note=note))
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self._update_frame(generation)

    def _parse_resolution(self):
        try:
            w_str, h_str = self.resolution_var.get().split("x")
            return int(w_str), int(h_str)
        except (AttributeError, ValueError):
            logger.warning("Invalid camera resolution; using default", exc_info=True)
            return CAPTURE_WIDTH, CAPTURE_HEIGHT

    def stop(self):
        self.running = False
        self._update_generation += 1
        self.status_var.set(self.tr("status_stopped"))
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        if self.capture_reader is not None:
            self.capture_reader.stop()
            self.capture_reader = None
        elif self.cap is not None:
            self.cap.release()
        self.cap = None
        if self._vcam_sender is not None:
            self._vcam_sender.stop()
            self._vcam_sender = None
        self.draw_points.clear()
        self._was_pinching.clear()
        self.video_label.configure(image="", text=self.tr("standby_stopped"))
        self.video_label.imgtk = None
        self._preview_hidden_shown = False
        self._save_settings()

    def take_screenshot(self):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(SCREENSHOT_DIR, f"screenshot_{ts}.png")
        ImageGrab.grab().save(path)
        self.status_var.set(self.tr("status_screenshot_saved", path=path))

    def open_images_folder(self):
        try:
            if os.name == "nt":
                os.startfile(IMAGES_DIR)
            else:
                subprocess.Popen(["xdg-open", IMAGES_DIR])
        except Exception as e:
            logger.exception("Could not open images folder")
            messagebox.showinfo(self.tr("info_images_folder_title"),
                                 self.tr("info_images_folder_fail", dir=IMAGES_DIR, err=e))

    def reload_stickers(self):
        self.stickers, self.stickers_custom = load_sticker_images()
        self.sticker_transform_cache.clear()
        self._update_sticker_status_label()
        self.status_var.set(self.tr("status_stickers_reloaded"))

    def _update_sticker_status_label(self):
        parts = []
        for n in range(1, 6):
            mark = "✓" if self.stickers_custom.get(n) else "—"
            parts.append(f"{n}:{mark}")
        self.sticker_status_var.set(self.tr("sticker_status_prefix") + "  ".join(parts) +
                                     self.tr("sticker_status_suffix"))

    def _on_preview_resize(self, event):
        # Игнорируем совсем крошечные размеры (например, в момент раскладки окна)
        if event.width > 20 and event.height > 20:
            self._preview_box = (event.width, event.height)

    def _next_timestamp_ms(self):
        ts = int((time.monotonic() - self._start_time) * 1000)
        if ts <= self._last_ts_ms:
            ts = self._last_ts_ms + 1
        self._last_ts_ms = ts
        return ts

    # -------------------------------------------------------- Калибровка взгляда ----
    def start_gaze_calibration(self):
        if not self.running:
            messagebox.showinfo(self.tr("info_need_camera_title"), self.tr("info_need_camera_gaze"))
            return
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.calib_targets = [(int(fx * sw), int(fy * sh)) for fx, fy in GAZE_CALIB_POINTS_FRAC]
        self.calib_index = 0
        self.calib_samples = []
        self._calib_results = []
        self.gaze_calibration_active = True

        self.calib_win = tk.Toplevel(self.root)
        self.calib_win.attributes("-fullscreen", True)
        self.calib_win.configure(bg="black")
        self.calib_win.bind("<Escape>", lambda e: self._cancel_gaze_calibration())
        self.calib_canvas = tk.Canvas(self.calib_win, bg="black", highlightthickness=0)
        self.calib_canvas.pack(fill="both", expand=True)
        self.calib_canvas.create_text(
            sw // 2, sh // 2 - 60, fill="white",
            text=self.tr("gaze_calib_fullscreen_hint"), font=("Arial", 16),
        )
        self._show_calib_point()

    def _show_calib_point(self):
        x, y = self.calib_targets[self.calib_index]
        self.calib_canvas.delete("dot")
        r = 12
        self.calib_canvas.create_oval(x - r, y - r, x + r, y + r, fill="red",
                                       outline="white", width=2, tags="dot")
        self.calib_phase = "wait"
        self.calib_phase_start = time.monotonic()
        self.calib_samples = []

    def _cancel_gaze_calibration(self):
        self.gaze_calibration_active = False
        if self.calib_win is not None:
            self.calib_win.destroy()
            self.calib_win = None
        self.status_var.set(self.tr("status_gaze_calib_cancelled"))

    def _finish_gaze_calibration(self):
        A, bx, by = [], [], []
        for (sx, sy), feats in zip(self.calib_targets, self._calib_results):
            A.append(list(feats) + [1.0])
            bx.append(sx)
            by.append(sy)
        A = np.array(A)
        try:
            coeffs_x, *_ = np.linalg.lstsq(A, np.array(bx), rcond=None)
            coeffs_y, *_ = np.linalg.lstsq(A, np.array(by), rcond=None)
        except np.linalg.LinAlgError:
            messagebox.showerror(self.tr("err_title"), self.tr("err_calib_build"))
            self._cancel_gaze_calibration()
            return

        self.gaze_coeffs_x = coeffs_x.tolist()
        self.gaze_coeffs_y = coeffs_y.tolist()
        self.gaze_calibrated = True
        self.gaze_calib_var.set(self.tr("gaze_calib_done_label"))
        self._save_gaze_calibration()

        self.gaze_calibration_active = False
        if self.calib_win is not None:
            self.calib_win.destroy()
            self.calib_win = None
        self.status_var.set(self.tr("status_gaze_calib_done"))

    def _process_gaze_calibration_step(self, features):
        now = time.monotonic()
        if self.calib_phase == "wait":
            if now - self.calib_phase_start >= GAZE_WAIT_BEFORE_COLLECT:
                self.calib_phase = "collect"
                self.calib_phase_start = now
            return

        if self.calib_phase == "collect":
            if features is not None:
                self.calib_samples.append(features)

            timed_out = (now - self.calib_phase_start) >= GAZE_POINT_TIMEOUT
            enough = len(self.calib_samples) >= GAZE_SAMPLES_PER_POINT

            if enough or (timed_out and len(self.calib_samples) >= 3):
                mean_feats = np.mean(np.array(self.calib_samples), axis=0)
                self._store_calib_point_result(mean_feats)
            elif timed_out:
                messagebox.showwarning(self.tr("warn_face_not_found_title"),
                                        self.tr("warn_face_not_found_msg"))
                self._cancel_gaze_calibration()

    def _store_calib_point_result(self, mean_feats):
        self._calib_results.append(mean_feats)
        self.calib_index += 1
        if self.calib_index >= len(self.calib_targets):
            self._finish_gaze_calibration()
        else:
            self._show_calib_point()

    def reset_gaze_calibration(self):
        self.gaze_calibrated = False
        self.gaze_coeffs_x = None
        self.gaze_coeffs_y = None
        self.gaze_calib_var.set(self.tr("gaze_calib_reset_label"))
        if os.path.exists(GAZE_CALIB_PATH):
            os.remove(GAZE_CALIB_PATH)

    def _save_gaze_calibration(self):
        data = {"coeffs_x": self.gaze_coeffs_x, "coeffs_y": self.gaze_coeffs_y}
        try:
            atomic_json_dump(GAZE_CALIB_PATH, data)
        except Exception:
            pass  # ошибка уже записана atomic_json_dump в лог

    def _load_gaze_calibration(self):
        if not os.path.exists(GAZE_CALIB_PATH):
            return
        try:
            with open(GAZE_CALIB_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.gaze_coeffs_x = data["coeffs_x"]
            self.gaze_coeffs_y = data["coeffs_y"]
            self.gaze_calibrated = True
        except (OSError, ValueError, KeyError, TypeError):
            logger.warning("Ignoring invalid gaze calibration", exc_info=True)
            self.gaze_calibrated = False

    # -------------------------------------------------------------- Настройки приложения ----
    def _save_settings(self):
        try:
            data = {name: getattr(self, name).get() for name, _ in SETTINGS_SPEC}
            atomic_json_dump(SETTINGS_PATH, data)
        except Exception:
            pass  # ошибка уже записана atomic_json_dump в лог

    def _load_settings(self):
        if not os.path.exists(SETTINGS_PATH):
            return
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError, TypeError):
            logger.warning("Ignoring invalid settings file", exc_info=True)
            return
        for name, kind in SETTINGS_SPEC:
            if name not in data:
                continue
            try:
                value = data[name]
                if kind == "bool":
                    value = bool(value)
                elif kind == "float":
                    value = float(value)
                else:
                    value = str(value)
                getattr(self, name).set(value)
            except (AttributeError, TypeError, ValueError, tk.TclError):
                logger.warning("Ignoring invalid setting %s", name, exc_info=True)
                continue

    # ------------------------------------------------------------ Калибровка жестов 1-5 ----
    def start_hand_calibration(self):
        if not self.running:
            messagebox.showinfo(self.tr("info_need_camera_title"), self.tr("info_need_camera_hand"))
            return
        self.hand_calibration_active = True
        self.hand_wizard_step = 1
        self.hand_wizard_templates = {}
        self._start_hand_wizard_step()

    def _start_hand_wizard_step(self):
        self.hand_calib_phase = "countdown"
        self.hand_calib_phase_start = time.monotonic()
        self.hand_calib_samples = []
        n = self.hand_wizard_step
        self.hand_calib_var.set(self.tr("hand_calib_step_prep", n=n))

    def _process_hand_calibration_step(self, lm):
        now = time.monotonic()
        n = self.hand_wizard_step

        if self.hand_calib_phase == "countdown":
            remaining = HAND_WIZARD_COUNTDOWN - (now - self.hand_calib_phase_start)
            if remaining > 0:
                self.hand_calib_var.set(self.tr("hand_calib_step_countdown", n=n, r=remaining))
                return
            self.hand_calib_phase = "collect"
            self.hand_calib_phase_start = now
            self.hand_calib_samples = []

        if self.hand_calib_phase == "collect":
            if lm is not None:
                self.hand_calib_samples.append(normalize_hand_vector(lm))
                self.hand_calib_var.set(self.tr(
                    "hand_calib_step_collect", n=n,
                    c=len(self.hand_calib_samples), t=HAND_SAMPLES_TARGET,
                ))

            timed_out = (now - self.hand_calib_phase_start) >= HAND_CALIB_TIMEOUT
            enough = len(self.hand_calib_samples) >= HAND_SAMPLES_TARGET

            if enough or (timed_out and len(self.hand_calib_samples) >= 5):
                template = np.mean(np.array(self.hand_calib_samples), axis=0)
                self.hand_wizard_templates[n] = template
                if n >= 5:
                    self._finish_hand_wizard()
                else:
                    self.hand_wizard_step += 1
                    self._start_hand_wizard_step()
            elif timed_out:
                messagebox.showwarning(self.tr("warn_hand_calib_interrupted_title"),
                                        self.tr("warn_hand_calib_interrupted_msg", n=n))
                self.cancel_hand_calibration()

    def _finish_hand_wizard(self):
        self.hand_templates = dict(self.hand_wizard_templates)
        self.hand_calibration_active = False
        self.hand_calib_var.set(self.tr("hand_calib_done"))
        self._save_hand_calibration()

    def cancel_hand_calibration(self):
        self.hand_calibration_active = False
        if self.hand_templates:
            done = ", ".join(str(n) for n in sorted(self.hand_templates))
            self.hand_calib_var.set(self.tr("hand_calib_prev_done", list=done))
        else:
            self.hand_calib_var.set(self.tr("hand_calib_reset_label"))

    def reset_hand_calibration(self):
        self.hand_templates = {}
        self.hand_calib_var.set(self.tr("hand_calib_reset_label"))
        if os.path.exists(HAND_CALIB_PATH):
            os.remove(HAND_CALIB_PATH)

    def _save_hand_calibration(self):
        data = {
            "version": HAND_TEMPLATE_VERSION,
            "templates": {str(n): t.tolist() for n, t in self.hand_templates.items()},
        }
        try:
            atomic_json_dump(HAND_CALIB_PATH, data)
        except Exception:
            pass

    def _load_hand_calibration(self):
        self.hand_templates = {}
        if not os.path.exists(HAND_CALIB_PATH):
            return
        try:
            with open(HAND_CALIB_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("version") != HAND_TEMPLATE_VERSION:
                logger.info("Old hand calibration format ignored; recalibration is required")
                return
            templates = data.get("templates")
            if templates:
                self.hand_templates = {
                    int(k): np.asarray(v, dtype=np.float32) for k, v in templates.items()
                }
        except (OSError, ValueError, TypeError, KeyError):
            logger.warning("Ignoring invalid hand calibration", exc_info=True)
            self.hand_templates = {}

    # ------------------------------------------------------------ Мои жесты (вкладка) ----
    def _draw_hand_diagram(self):
        if not hasattr(self, "hand_canvas"):
            return
        c = self.hand_canvas
        c.delete("all")
        dark = self.dark_mode_var.get()
        bg = "#2b2b2b" if dark else "#f5f5f5"
        c.configure(bg=bg, highlightbackground="#e6e6e6" if dark else "#999999")
        pattern = tuple(variable.get() for variable in self.finger_toggle_vars)
        rendered = render_hand_reference(self._hand_reference_base, pattern, dark=dark)
        self._hand_diagram_photo = ImageTk.PhotoImage(rendered)
        offset_x, offset_y = HAND_GUIDE_OFFSET
        c.create_image(offset_x, offset_y, image=self._hand_diagram_photo, anchor="nw")

        scale = HAND_GUIDE_RENDER_SIZE / HAND_GUIDE_SOURCE_SIZE
        for index, (source_x, source_y) in enumerate(HAND_GUIDE_NUMBER_POINTS):
            x = offset_x + source_x * scale
            y = offset_y + source_y * scale
            enabled = pattern[index]
            fill = "#23eb5c" if enabled else ("#555555" if dark else "#222222")
            text_fill = "#07130a" if enabled else "#ffffff"
            c.create_oval(x - 11, y - 11, x + 11, y + 11,
                          fill=fill, outline="#ffffff", width=1)
            c.create_text(x, y, text=str(index + 1), fill=text_fill,
                          font=("Arial", 9, "bold"))

    def _on_hand_canvas_click(self, event):
        offset_x, offset_y = HAND_GUIDE_OFFSET
        source_x = (event.x - offset_x) * HAND_GUIDE_SOURCE_SIZE / HAND_GUIDE_RENDER_SIZE
        source_y = (event.y - offset_y) * HAND_GUIDE_SOURCE_SIZE / HAND_GUIDE_RENDER_SIZE
        candidates = []
        for index, polygon in enumerate(HAND_GUIDE_FINGER_ZONES):
            xs = [point[0] for point in polygon]
            ys = [point[1] for point in polygon]
            if min(xs) <= source_x <= max(xs) and min(ys) <= source_y <= max(ys):
                tip_x, tip_y = HAND_GUIDE_NUMBER_POINTS[index]
                candidates.append(((source_x - tip_x) ** 2 + (source_y - tip_y) ** 2, index))
        if candidates:
            self._toggle_finger(min(candidates)[1])

    def _toggle_finger(self, idx):
        self.finger_toggle_vars[idx].set(not self.finger_toggle_vars[idx].get())
        self._draw_hand_diagram()

    def _toggle_key_capture(self):
        if self._capture_mode is not None:
            self._finish_key_capture(cancel=True)
            return
        key = self._action_key_by_display.get(self.action_display_var.get())
        if key not in ("hotkey", "key"):
            return
        self._start_key_capture(key)

    def _start_key_capture(self, mode):
        self._capture_session += 1
        session = self._capture_session
        self._capture_mode = mode
        self._capture_pressed = set()
        self.capture_btn.configure(text=self.tr("custom_capture_recording"))
        self.root.bind_all("<KeyPress>", self._on_capture_keypress)
        self.root.bind_all("<KeyRelease>", self._on_capture_keyrelease)
        # Подстраховка: если пользователь так и не нажал ни одной клавиши
        # (например, переключился в другое окно), не оставляем глобальные
        # бинды навсегда — отменяем запись сами через 8 секунд.
        self.root.after(8000, lambda: self._capture_timeout(session))

    def _on_capture_keypress(self, event):
        name = keysym_to_pyautogui(event.keysym)
        if event.keysym == "Escape" and not self._capture_pressed:
            self._finish_key_capture(cancel=True)
            return
        self._capture_pressed.add(name)

    def _on_capture_keyrelease(self, event):
        # Финализируем по первому отпусканию: набор клавиш, зажатых на этот
        # момент, и есть желаемая комбинация (дальше не важно, в каком
        # порядке пользователь их отпускает).
        pressed_snapshot = set(self._capture_pressed)
        if not pressed_snapshot:
            return
        if self._capture_mode == "key":
            non_mods = [k for k in pressed_snapshot if k not in MODIFIER_KEY_NAMES]
            value = non_mods[0] if non_mods else next(iter(pressed_snapshot))
        else:
            mods = [m for m in MODIFIER_KEY_NAMES if m in pressed_snapshot]
            others = sorted(k for k in pressed_snapshot if k not in MODIFIER_KEY_NAMES)
            value = "+".join(mods + others)
        self.gesture_param_var.set(value)
        self._finish_key_capture(cancel=False)

    def _capture_timeout(self, session):
        if self._capture_mode is not None and session == self._capture_session:
            self._finish_key_capture(cancel=True)

    def _finish_key_capture(self, cancel):
        self.root.unbind_all("<KeyPress>")
        self.root.unbind_all("<KeyRelease>")
        self._capture_mode = None
        self._capture_pressed = set()
        if hasattr(self, "capture_btn"):
            self.capture_btn.configure(text=self.tr("custom_capture_btn"))

    def _add_gesture_binding(self):
        name = self.gesture_name_var.get().strip()
        if not name:
            messagebox.showwarning(self.tr("err_title"), self.tr("custom_name_empty_msg"))
            return
        key = self._action_key_by_display.get(self.action_display_var.get())
        param = self.gesture_param_var.get().strip()
        needs_param = key in ("hotkey", "key", "run", "open")
        if needs_param and not param:
            messagebox.showwarning(self.tr("err_title"), self.tr("custom_param_empty_msg"))
            return
        needs_pyautogui = key in ("hotkey", "key", "media_playpause", "volume_up", "volume_down", "mute")
        if needs_pyautogui and not PYAUTOGUI_AVAILABLE:
            messagebox.showwarning(self.tr("err_title"), self.tr("custom_pyautogui_missing_msg"))
            return
        pattern = tuple(v.get() for v in self.finger_toggle_vars)
        self.custom_gestures.append({
            "name": name, "pattern": pattern, "action_type": key, "action_param": param,
        })
        self._save_custom_gestures()
        self._rebuild_custom_gesture_list()
        self.gesture_name_var.set("")
        self.gesture_param_var.set("")

    def _delete_custom_gesture(self, idx):
        if 0 <= idx < len(self.custom_gestures):
            del self.custom_gestures[idx]
            self._last_pattern_trigger_time = {}
            self._save_custom_gestures()
            self._rebuild_custom_gesture_list()

    def _rebuild_custom_gesture_list(self):
        if not hasattr(self, "custom_gesture_list_frame"):
            return
        for w in self.custom_gesture_list_frame.winfo_children():
            w.destroy()
        if not self.custom_gestures:
            ttk.Label(self.custom_gesture_list_frame, text=self.tr("custom_empty"),
                      foreground="#777").grid(row=0, column=0, sticky="w")
            return
        finger_names = [self.tr(key) for key in (
            "finger_thumb", "finger_index", "finger_middle", "finger_ring", "finger_pinky"
        )]
        for i, g in enumerate(self.custom_gestures):
            pat_str = ", ".join(
                f"{name}: {'↑' if raised else '↓'}"
                for name, raised in zip(finger_names, g["pattern"])
            )
            action_label = self.tr(f"action_{g['action_type']}")
            row = ttk.Frame(self.custom_gesture_list_frame)
            row.grid(row=i, column=0, sticky="ew", pady=1)
            text = f'{g["name"]}\n{pat_str} → {action_label}'
            ttk.Label(row, text=text, wraplength=520, justify="left").pack(side="left")
            ttk.Button(row, text=self.tr("custom_delete_btn"), width=2,
                       command=lambda idx=i: self._delete_custom_gesture(idx)).pack(side="right")

    def _save_custom_gestures(self):
        try:
            data = [{"name": g["name"], "pattern": list(g["pattern"]),
                     "action_type": g["action_type"], "action_param": g["action_param"]}
                    for g in self.custom_gestures]
            atomic_json_dump(CUSTOM_GESTURES_PATH, data)
        except Exception:
            pass  # ошибка уже записана в лог

    def _load_custom_gestures(self):
        self.custom_gestures = []
        if not os.path.exists(CUSTOM_GESTURES_PATH):
            return
        try:
            with open(CUSTOM_GESTURES_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            for g in data:
                pattern = tuple(bool(x) for x in g["pattern"])
                if len(pattern) != 5:
                    raise ValueError("Gesture pattern must contain five finger states")
                self.custom_gestures.append({
                    "name": str(g["name"]), "pattern": pattern,
                    "action_type": g["action_type"], "action_param": g.get("action_param", ""),
                })
        except (OSError, ValueError, TypeError, KeyError):
            logger.warning("Ignoring invalid custom gestures file", exc_info=True)
            self.custom_gestures = []

    def _execute_gesture_binding(self, g):
        action_type = g["action_type"]
        param = g.get("action_param", "")
        try:
            if action_type == "toggle_hide_face":
                self.hide_face_var.set(not self.hide_face_var.get())
            elif action_type == "screenshot":
                self.take_screenshot()
            elif action_type == "toggle_preview":
                self.preview_visible_var.set(not self.preview_visible_var.get())
            elif not PYAUTOGUI_AVAILABLE and action_type in (
                "hotkey", "key", "media_playpause", "volume_up", "volume_down", "mute"
            ):
                return
            elif action_type == "hotkey":
                keys = [k.strip() for k in param.split("+") if k.strip()]
                if keys:
                    pyautogui.hotkey(*keys)
            elif action_type == "key":
                if param:
                    pyautogui.press(param)
            elif action_type == "media_playpause":
                pyautogui.press("playpause")
            elif action_type == "volume_up":
                pyautogui.press("volumeup")
            elif action_type == "volume_down":
                pyautogui.press("volumedown")
            elif action_type == "mute":
                pyautogui.press("volumemute")
            elif action_type == "run":
                if param:
                    args = param if os.name == "nt" else shlex.split(param)
                    subprocess.Popen(args, shell=False)
            elif action_type == "open":
                if param:
                    if os.name == "nt":
                        os.startfile(param)
                    else:
                        subprocess.Popen(["xdg-open", param])
        except Exception:
            # Не спамим messagebox из горячего видео-цикла, но сохраняем
            # traceback в logs/handtrack.log для нормальной диагностики.
            logger.exception("Gesture action failed: %s", action_type)

    # -------------------------------------------------------------- Виртуальная камера ----
    def _update_vcam(self, rgb_frame, width, height):
        want_vcam = self.vcam_var.get() and VCAM_AVAILABLE
        sender = self._vcam_sender

        if sender is not None and (
            not want_vcam or sender.width != width or sender.height != height
        ):
            sender.stop()
            self._vcam_sender = None
            sender = None

        if want_vcam and sender is None:
            sender = VirtualCameraSender(width, height, fps=30)
            self._vcam_sender = sender
            sender.start()

        if sender is None:
            return

        error_text = None
        while True:
            try:
                event, payload = sender.events.get_nowait()
            except queue.Empty:
                break
            if event == "started":
                self.status_var.set(self.tr(
                    "status_vcam_started", dev=payload, w=width, h=height
                ))
            elif event == "error":
                error_text = payload

        if error_text is None and want_vcam and not sender.alive:
            error_text = "Virtual camera stopped unexpectedly."

        if error_text is not None:
            sender.stop()
            if self._vcam_sender is sender:
                self._vcam_sender = None
            self.vcam_var.set(False)
            messagebox.showerror(
                self.tr("err_vcam_title"), self.tr("err_vcam_msg", err=error_text)
            )
            return

        if want_vcam:
            sender.submit(rgb_frame)

    # -------------------------------------------------------- Асинхронный inference ----
    def _submit_inference(self, frame, now, need_face, face_interval):
        hand_due = (now - self._last_hand_submit_at) >= HAND_INFERENCE_INTERVAL
        face_due = need_face and (now - self._last_face_submit_at) >= face_interval
        if not hand_due and not face_due:
            return

        height, width = frame.shape[:2]
        # Сначала уменьшаем BGR, затем конвертируем: не прогоняем cvtColor по
        # пикселям, которые fast mode всё равно выбросит.
        if self.fast_mode_var.get():
            detect_width = max(160, width // 2)
            detect_height = max(90, height // 2)
            detect_bgr = cv2.resize(
                frame, (detect_width, detect_height), interpolation=cv2.INTER_AREA
            )
            detect_rgb = cv2.cvtColor(detect_bgr, cv2.COLOR_BGR2RGB)
        else:
            detect_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        media_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=detect_rgb)
        timestamp_ms = self._next_timestamp_ms()

        if hand_due:
            self._last_hand_submit_at = now
            try:
                self.hand_landmarker.detect_async(media_image, timestamp_ms)
            except (RuntimeError, ValueError):
                logger.exception("HandLandmarker async submission failed")

        if face_due:
            self._last_face_submit_at = now
            try:
                self.face_landmarker.detect_async(media_image, timestamp_ms)
            except (RuntimeError, ValueError):
                logger.exception("FaceLandmarker async submission failed")

    def _trigger_custom_gesture(self, states, now):
        if states == self._last_hand_pattern:
            return
        self._last_hand_pattern = states
        if not self.custom_gestures_enabled_var.get():
            return
        for gesture_index, gesture in enumerate(self.custom_gestures):
            if gesture["pattern"] != states:
                continue
            last_time = self._last_pattern_trigger_time.get(gesture_index, 0.0)
            if now - last_time > CUSTOM_GESTURE_COOLDOWN:
                self._last_pattern_trigger_time[gesture_index] = now
                self._execute_gesture_binding(gesture)
            break

    def _record_draw_point(self, hand_key, midpoint, width, height, now):
        pixel_x = int(midpoint[0] * width)
        pixel_y = int(midpoint[1] * height)
        points = self.draw_points[hand_key]
        starts_stroke = not self._was_pinching[hand_key]
        should_append = starts_stroke or not points
        if not should_append:
            last_x, last_y, _last_time, _last_start = points[-1]
            should_append = _dist2(pixel_x, pixel_y, last_x, last_y) >= (
                DRAW_MIN_POINT_DISTANCE ** 2
            )
        if should_append:
            points.append((pixel_x, pixel_y, now, starts_stroke))
        self._was_pinching[hand_key] = True

    def _process_hands(self, frame, width, height, hand_result, is_new, show_viz, now):
        entries = self._hand_entries(hand_result)
        counter_text = "-"

        if self.hand_calibration_active:
            landmarks = entries[0][1] if entries else None
            # Один callback MediaPipe = один sample. Между callbacks передаём
            # None только для продвижения countdown/timeout.
            self._process_hand_calibration_step(landmarks if is_new else None)
            if landmarks is not None:
                raw_count = count_raised_fingers(landmarks)
                self.gesture_var.set(self.tr("gesture_calibrating", n=raw_count))
                counter_text = str(raw_count)
                if show_viz:
                    draw_hand_skeleton(frame, landmarks, width, height)
            else:
                self.gesture_var.set(self.tr("gesture_no_hand"))
            for key in list(self._was_pinching):
                self._was_pinching[key] = False
            self._last_hand_pattern = None
            self._last_primary_hand_key = None
            return counter_text

        if not entries:
            self.gesture_var.set(self.tr("gesture_no_hand"))
            self._last_hand_pattern = None
            self._last_primary_hand_key = None
            for key in list(self._was_pinching):
                self._was_pinching[key] = False
            return counter_text

        display_count_primary = None
        active_keys = set()
        for hand_position, (hand_key, landmarks) in enumerate(entries):
            active_keys.add(hand_key)
            states = get_finger_states(landmarks)
            raw_count = sum(states)

            if show_viz:
                draw_hand_skeleton(frame, landmarks, width, height)

            if hand_position == 0 and self.hand_templates:
                template_count, template_distance = classify_by_templates(
                    landmarks, self.hand_templates
                )
                if (template_distance is not None
                        and template_distance < self.threshold_var.get()):
                    display_count = template_count
                    self.gesture_var.set(self.tr(
                        "gesture_templ", n=display_count, d=template_distance
                    ))
                else:
                    display_count = raw_count
                    self.gesture_var.set(self.tr(
                        "gesture_templ_unsure", n=display_count, d=template_distance
                    ))
            else:
                display_count = raw_count
                if hand_position == 0:
                    self.gesture_var.set(self.tr("gesture_basic", n=display_count))

            if hand_position == 0:
                display_count_primary = display_count
                if is_new:
                    if hand_key != self._last_primary_hand_key:
                        self._last_hand_pattern = None
                    self._last_primary_hand_key = hand_key
                    self._trigger_custom_gesture(states, now)

            if self.attach_photo_var.get() and 1 <= display_count <= 5:
                overlay_sticker_on_hand(
                    frame,
                    landmarks,
                    width,
                    height,
                    self.stickers[display_count],
                    scale_factor=self.sticker_scale_var.get(),
                    rotate=self.rotate_sticker_var.get(),
                    sticker_id=display_count,
                    transform_cache=self.sticker_transform_cache,
                )

            if is_new:
                if self.draw_enabled_var.get():
                    pinching, midpoint = is_pinching(landmarks)
                    if pinching:
                        self._record_draw_point(
                            hand_key, midpoint, width, height, now
                        )
                    else:
                        self._was_pinching[hand_key] = False
                else:
                    self._was_pinching[hand_key] = False

        if is_new:
            for key in list(self._was_pinching):
                if key not in active_keys:
                    self._was_pinching[key] = False

        if display_count_primary is not None and 0 <= display_count_primary <= 5:
            counter_text = str(display_count_primary)
        return counter_text

    def _render_drawings(self, frame, now):
        if not self.draw_enabled_var.get():
            self.draw_points.clear()
            self._was_pinching.clear()
            return

        for hand_key, points in list(self.draw_points.items()):
            while points and now - points[0][2] > DRAW_FADE_SECONDS:
                points.popleft()
            if not points:
                del self.draw_points[hand_key]
                continue

            previous = None
            for point_x, point_y, _point_time, starts_stroke in points:
                cv2.circle(frame, (point_x, point_y), 4, DRAW_COLOR_BGR, -1)
                if previous is not None and not starts_stroke:
                    cv2.line(
                        frame,
                        previous,
                        (point_x, point_y),
                        DRAW_COLOR_BGR,
                        6,
                        cv2.LINE_AA,
                    )
                previous = (point_x, point_y)

    def _process_face_and_gaze(
        self,
        frame,
        width,
        height,
        face_result,
        face_is_new,
        show_viz,
        now,
        need_face,
    ):
        face_landmarks = None
        if face_result and face_result.face_landmarks:
            face_landmarks = face_result.face_landmarks[0]
            if face_is_new:
                self._face_last_seen = now

        need_gaze_features = self.gaze_var.get() or self.gaze_calibration_active
        gaze_features = None
        predicted_xy = None

        if face_landmarks is not None and need_gaze_features:
            left_h, left_v = eye_ratio(
                face_landmarks,
                LEFT_IRIS,
                LEFT_CORNER_L,
                LEFT_CORNER_R,
                LEFT_LID_TOP,
                LEFT_LID_BOTTOM,
            )
            right_h, right_v = eye_ratio(
                face_landmarks,
                RIGHT_IRIS,
                RIGHT_CORNER_L,
                RIGHT_CORNER_R,
                RIGHT_LID_TOP,
                RIGHT_LID_BOTTOM,
            )
            gaze_features = [left_h, left_v, right_h, right_v]

            if show_viz:
                for index in (
                    LEFT_IRIS, RIGHT_IRIS, LEFT_CORNER_L, LEFT_CORNER_R,
                    RIGHT_CORNER_L, RIGHT_CORNER_R, LEFT_LID_TOP,
                    LEFT_LID_BOTTOM, RIGHT_LID_TOP, RIGHT_LID_BOTTOM,
                ):
                    point = face_landmarks[index]
                    cv2.circle(
                        frame,
                        (int(point.x * width), int(point.y * height)),
                        2,
                        (0, 255, 0),
                        -1,
                    )

        if self.gaze_calibration_active:
            self._process_gaze_calibration_step(
                gaze_features if face_is_new else None
            )

        if self.gaze_var.get():
            if gaze_features is None:
                self.gaze_status_var.set(self.tr("gaze_status_no_face"))
            elif self.gaze_calibrated and self.gaze_coeffs_x is not None:
                feature_vector = gaze_features + [1.0]
                predicted_x = sum(
                    coefficient * value
                    for coefficient, value in zip(self.gaze_coeffs_x, feature_vector)
                )
                predicted_y = sum(
                    coefficient * value
                    for coefficient, value in zip(self.gaze_coeffs_y, feature_vector)
                )
                screen_width = self.root.winfo_screenwidth()
                screen_height = self.root.winfo_screenheight()
                predicted_x = min(max(predicted_x, 0), screen_width)
                predicted_y = min(max(predicted_y, 0), screen_height)
                predicted_xy = (predicted_x, predicted_y)
                column = min(2, int(predicted_x / screen_width * 3))
                row = min(2, int(predicted_y / screen_height * 3))
                self.gaze_status_var.set(self.tr(
                    "gaze_status_zone", zone=self.tr(GAZE_ZONE_KEYS[row][column])
                ))
            else:
                average_h = (gaze_features[0] + gaze_features[2]) / 2
                direction_key = (
                    "gaze_dir_left" if average_h < 0.4
                    else "gaze_dir_right" if average_h > 0.6
                    else "gaze_dir_center"
                )
                self.gaze_status_var.set(self.tr(
                    "gaze_status_rough",
                    direction=self.tr(direction_key),
                    val=average_h,
                ))
        else:
            self.gaze_status_var.set(self.tr("gaze_status_off"))

        if predicted_xy is not None:
            screen_width = self.root.winfo_screenwidth()
            screen_height = self.root.winfo_screenheight()
            gaze_x = predicted_xy[0] / screen_width * 180
            gaze_y = predicted_xy[1] / screen_height * 100
            self.gaze_canvas.coords(
                self.gaze_dot, gaze_x - 5, gaze_y - 5, gaze_x + 5, gaze_y + 5
            )

        # Приватная маска рисуется ПОСЛЕ вычисления глаз. Поэтому калибровка
        # работает даже при выключенном трекинге взгляда и включённом Hide face.
        if self.hide_face_var.get():
            if face_landmarks is not None:
                xs = [face_landmarks[index].x for index in FACE_MASK_ANCHOR_IDX]
                ys = [face_landmarks[index].y for index in FACE_MASK_ANCHOR_IDX]
                left, right = min(xs) * width, max(xs) * width
                top, bottom = min(ys) * height, max(ys) * height
                pad_x = int((right - left) * 0.2) + 15
                pad_y = int((bottom - top) * 0.2) + 15
                cv2.rectangle(
                    frame,
                    (max(0, int(left - pad_x)), max(0, int(top - pad_y))),
                    (min(width, int(right + pad_x)),
                     min(height, int(bottom + pad_y))),
                    (0, 0, 0),
                    -1,
                )
            else:
                # Fail closed: при потере/задержке трекинга лицо не проскочит.
                frame[:] = 0

        if (self.afk_enabled_var.get()
                and not self.hide_face_var.get()
                and now - self._face_last_seen > self.afk_timeout_var.get()):
            frame[:] = 0
            afk_text = self.tr("afk_text")
            (text_width, text_height), _ = cv2.getTextSize(
                afk_text, cv2.FONT_HERSHEY_SIMPLEX, 2.2, 4
            )
            cv2.putText(
                frame,
                afk_text,
                ((width - text_width) // 2, (height + text_height) // 2),
                cv2.FONT_HERSHEY_SIMPLEX,
                2.2,
                (255, 255, 255),
                4,
                cv2.LINE_AA,
            )
            sub_text = self.tr("afk_subtext")
            (sub_width, sub_height), _ = cv2.getTextSize(
                sub_text, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2
            )
            cv2.putText(
                frame,
                sub_text,
                ((width - sub_width) // 2,
                 (height + text_height) // 2 + sub_height + 20),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (180, 180, 180),
                2,
                cv2.LINE_AA,
            )

    # ----------------------------------------------------------------- Видео-цикл ----
    def _process_camera_frame(self, raw_frame):
        frame = cv2.flip(raw_frame, 1)
        height, width = frame.shape[:2]
        now = time.monotonic()
        show_viz = self.visualize_var.get()

        need_face = (
            self.hide_face_var.get()
            or self.gaze_var.get()
            or self.gaze_calibration_active
            or self.afk_enabled_var.get()
        )
        if self.hide_face_var.get() or self.gaze_calibration_active:
            face_interval = HAND_INFERENCE_INTERVAL
        elif self.gaze_var.get():
            face_interval = FACE_GAZE_INTERVAL
        else:
            face_interval = FACE_AFK_INTERVAL

        self._submit_inference(frame, now, need_face, face_interval)

        (
            hand_result,
            hand_timestamp,
            hand_received_at,
            face_result,
            face_timestamp,
            face_received_at,
        ) = self._inference_snapshot()

        hand_is_new = hand_timestamp != self._last_hand_result_used_ts
        if hand_is_new:
            self._last_hand_result_used_ts = hand_timestamp
        if now - hand_received_at > RESULT_STALE_SECONDS:
            hand_result = None
            hand_is_new = False

        face_is_new = face_timestamp != self._last_face_result_used_ts
        if face_is_new:
            self._last_face_result_used_ts = face_timestamp
        face_stale_limit = 0.15 if self.hide_face_var.get() else RESULT_STALE_SECONDS
        if not need_face or now - face_received_at > face_stale_limit:
            face_result = None
            face_is_new = False

        counter_text = self._process_hands(
            frame,
            width,
            height,
            hand_result,
            hand_is_new,
            show_viz,
            now,
        )
        self._render_drawings(frame, now)
        if self.show_counter_var.get():
            draw_corner_counter(frame, counter_text, width, height)

        self._process_face_and_gaze(
            frame,
            width,
            height,
            face_result,
            face_is_new,
            show_viz,
            now,
            need_face,
        )

        need_rgb_output = (
            self.preview_visible_var.get()
            or (self.vcam_var.get() and VCAM_AVAILABLE)
            or self._vcam_sender is not None
        )
        final_rgb = (
            cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) if need_rgb_output else None
        )

        self._update_vcam(final_rgb, width, height)

        if self.preview_visible_var.get():
            box_width, box_height = self._preview_box
            scale = max(min(box_width / width, box_height / height), 0.05)
            display_width = max(1, int(width * scale))
            display_height = max(1, int(height * scale))
            display_rgb = final_rgb
            if (display_width, display_height) != (width, height):
                interpolation = (
                    cv2.INTER_AREA
                    if display_width < width or display_height < height
                    else cv2.INTER_LINEAR
                )
                display_rgb = cv2.resize(
                    final_rgb,
                    (display_width, display_height),
                    interpolation=interpolation,
                )
            image = Image.fromarray(display_rgb)
            image_tk = ImageTk.PhotoImage(image=image)
            self.video_label.imgtk = image_tk
            self.video_label.configure(image=image_tk, text="")
            self._preview_hidden_shown = False
        elif not self._preview_hidden_shown:
            self.video_label.configure(image="", text=self.tr("preview_hidden"))
            self.video_label.imgtk = None
            self._preview_hidden_shown = True

    def _update_frame(self, generation):
        if (
            not self.running
            or generation != self._update_generation
            or self.capture_reader is None
        ):
            return

        try:
            frame_id, raw_frame = self.capture_reader.get_latest(
                self._last_capture_id
            )
            if raw_frame is not None:
                self._last_capture_id = frame_id
                self._process_camera_frame(raw_frame)
        except Exception:
            logger.exception("Unhandled error in video loop")
        finally:
            if self.running and generation == self._update_generation:
                self.root.after(UI_POLL_MS, self._update_frame, generation)

    def on_close(self):
        self.stop()
        for detector_name in ("hand_landmarker", "face_landmarker"):
            detector = getattr(self, detector_name, None)
            if detector is not None:
                try:
                    detector.close()
                except Exception:
                    logger.exception("Could not close %s", detector_name)
        self.root.destroy()


def main():
    root = tk.Tk()
    root.title(STRINGS[_STARTUP_LANG]["splash_title"])
    root.resizable(False, False)

    splash = ttk.Frame(root, padding=30)
    splash.pack()
    splash_label = ttk.Label(splash, text=STRINGS[_STARTUP_LANG]["splash_checking"])
    splash_label.pack()
    root.update()

    def set_status(msg):
        splash_label.config(text=msg)
        root.update()

    try:
        ensure_models(status_callback=set_status, lang=_STARTUP_LANG)
    except RuntimeError as e:
        messagebox.showerror(STRINGS[_STARTUP_LANG]["err_models_title"], str(e))
        root.destroy()
        return

    splash.destroy()

    app = HandTrackApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
