"""Main window: sidebar navigation, pages, and all engine/settings wiring."""

import logging
import os
import sys
import threading
from collections import defaultdict

from PySide6.QtCore import QEvent, QObject, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QIcon, QKeyEvent, QPixmap
from PySide6.QtWidgets import (
    QApplication, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QVBoxLayout, QWidget,
)

from handtrack import __version__, actions, config, paths, vcam
from handtrack.config import ACTIONS_WITH_KEYS, ACTIONS_WITH_PARAM, RESOLUTIONS
from handtrack.i18n import Translator
from handtrack.ui import theme
from handtrack.ui.overlays import GazeCalibrationOverlay
from handtrack.ui.pages import (
    HazardRule,
    FINGER_KEYS, CalibrationPage, CameraPage, EffectsPage, GesturesPage, SettingsPage,
)
from handtrack.ui.visuals import CoveringBadge, PreviewWidget, pattern_icon
from handtrack.ui.widgets import Button, FadeStack, NavList, Toast, heading, label
from handtrack.vision.geometry import fit_gaze

logger = logging.getLogger("handtrack")

# On macOS Qt reports Cmd as Key_Control and Control as Key_Meta.
_MAC = sys.platform == "darwin"
QT_KEY_NAMES = {
    Qt.Key.Key_Control: "command" if _MAC else "ctrl", Qt.Key.Key_Shift: "shift",
    Qt.Key.Key_Alt: "option" if _MAC else "alt", Qt.Key.Key_Meta: "ctrl" if _MAC else "win",
    Qt.Key.Key_Return: "enter", Qt.Key.Key_Enter: "enter",
    Qt.Key.Key_Escape: "esc", Qt.Key.Key_Backspace: "backspace", Qt.Key.Key_Tab: "tab",
    Qt.Key.Key_Space: "space", Qt.Key.Key_Delete: "delete", Qt.Key.Key_Up: "up",
    Qt.Key.Key_Down: "down", Qt.Key.Key_Left: "left", Qt.Key.Key_Right: "right",
    Qt.Key.Key_PageUp: "pageup", Qt.Key.Key_PageDown: "pagedown", Qt.Key.Key_Home: "home",
    Qt.Key.Key_End: "end", Qt.Key.Key_Insert: "insert", Qt.Key.Key_CapsLock: "capslock",
    Qt.Key.Key_Print: "printscreen", Qt.Key.Key_Pause: "pause",
}
MODIFIERS = ("ctrl", "alt", "option", "shift", "win", "command")


def qt_key_name(key):
    if key in QT_KEY_NAMES:
        return QT_KEY_NAMES[key]
    if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F24:
        return f"f{key - Qt.Key.Key_F1 + 1}"
    if 0x20 < key < 0x7F:
        return chr(key).lower()
    return None


def set_dark_title_bar(widget, dark):
    if sys.platform != "win32":
        return
    try:
        import ctypes
        value = ctypes.c_int(1 if dark else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(int(widget.winId()), 20,
                                                   ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass


class KeyRecorder(QObject):
    """Captures a key combination from the parameter field."""

    finished = Signal(str)

    def __init__(self, target, mode):
        super().__init__(target)
        self.mode = mode
        self.pressed = []
        target.installEventFilter(self)
        target.setFocus()
        QTimer.singleShot(8000, lambda: self.finished.emit(""))

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            if event.isAutoRepeat():
                return True
            name = qt_key_name(event.key())
            if name == "esc" and not self.pressed:
                self.finished.emit("")
            elif name and name not in self.pressed:
                self.pressed.append(name)
            return True
        if event.type() == QEvent.Type.KeyRelease and isinstance(event, QKeyEvent):
            if event.isAutoRepeat() or not self.pressed:
                return True
            if self.mode == "key":
                others = [k for k in self.pressed if k not in MODIFIERS]
                value = (others or self.pressed)[0]
            else:
                mods = [m for m in MODIFIERS if m in self.pressed]
                value = "+".join(mods + [k for k in self.pressed if k not in MODIFIERS])
            self.finished.emit(value)
            return True
        return False


class MainWindow(QMainWindow):
    def __init__(self, settings, engine):
        super().__init__()
        self.settings = settings
        self.engine = engine
        self.tr = Translator()
        self.custom_gestures = config.load_custom_gestures()
        self.engine.custom_gestures = list(self.custom_gestures)
        self.engine.classifier.set_templates(config.load_hand_templates())
        self.engine.gaze_coeffs = config.load_gaze_calibration()
        self.engine.set_afk_text(self.tr("afk_text"), self.tr("afk_subtext"))

        self._toggles = defaultdict(list)
        self._page_index = 0
        self._camera_state = "stopped"
        self._vcam_info = None
        self._gaze_overlay = None
        self._recorder = None
        self._driver_ok = vcam.driver_installed()
        self._pattern = (False,) * 5
        self._last_fingers = None
        self._hand_done = sorted(self.engine.classifier.templates)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(500)
        self._save_timer.timeout.connect(self.settings.save)

        self.setWindowTitle(f"HandTrack {__version__}")
        if paths.ICON_PATH:
            self.setWindowIcon(QIcon(paths.ICON_PATH))
        self.resize(1360, 840)
        self.setMinimumSize(1080, 680)

        e = self.engine
        e.started.connect(self._on_started)
        e.stopped.connect(self._on_stopped)
        e.failed.connect(self._on_failed)
        e.frame_ready.connect(self._on_frame)
        e.stats.connect(self._on_stats)
        e.vcam_state.connect(self._on_vcam_state)
        e.gesture_triggered.connect(self._on_gesture)
        e.hand_calib_progress.connect(self._on_hand_progress)
        e.hand_calib_finished.connect(self._on_hand_finished)
        e.gaze_calib_progress.connect(self._on_gaze_progress)
        e.gaze_calib_finished.connect(self._on_gaze_finished)

        self._build()
        set_dark_title_bar(self, settings.dark_mode)
        # Calls see the standby picture, not the driver's error pattern, as
        # long as HandTrack runs with streaming on.
        self.engine.sync_vcam()

    # ================================================================ build ====
    def _build(self):
        self._toggles.clear()
        tr, s = self.tr, self.settings
        root = QWidget()
        root.setObjectName("Root")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(232)
        sidebar.setStyleSheet(f"#Sidebar {{ background: {theme.hex_('sidebar')}; "
                              f"border-right: 1px solid {theme.hex_('border')}; }}")
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(16, 22, 16, 18)
        side.setSpacing(6)
        brand = QHBoxLayout()
        logo = QLabel()
        logo.setFixedSize(36, 36)
        logo.setScaledContents(True)
        logo.setPixmap(QPixmap(paths.LOGO_PATH))
        brand.addWidget(logo)
        names = QVBoxLayout()
        names.setSpacing(0)
        title = heading("HandTrack", 15, 3)
        sub = label(tr("app_subtitle"), "faint")
        names.addWidget(title)
        names.addWidget(sub)
        brand.addLayout(names, 1)
        side.addLayout(brand)
        side.addSpacing(10)
        side.addWidget(HazardRule(200))
        side.addSpacing(14)

        self.nav = NavList()
        for key, icon in (("nav_camera", "camera"), ("nav_effects", "effects"),
                          ("nav_gestures", "gestures"), ("nav_calibration", "calibration"),
                          ("nav_settings", "settings")):
            self.nav.add(tr(key), icon)
        side.addWidget(self.nav)
        side.addStretch(1)

        self.side_status = QLabel()
        self.side_status.setWordWrap(True)
        self.side_status.setProperty("role", "faint")
        side.addWidget(self.side_status)
        self.covering_badge = CoveringBadge(tr("covering"), tr("covering_sub"))
        side.addWidget(self.covering_badge)
        theme_btn = Button("", "sun" if s.dark_mode else "moon", "ghost")
        theme_btn.setFixedWidth(44)
        theme_btn.setToolTip(tr("theme_dark"))
        theme_btn.clicked.connect(lambda: self._set_theme(not self.settings.dark_mode))
        bottom = QHBoxLayout()
        bottom.addWidget(theme_btn)
        bottom.addStretch(1)
        side.addLayout(bottom)
        layout.addWidget(sidebar)

        self.stack = FadeStack()
        self.camera = CameraPage(tr, s)
        self.effects = EffectsPage(tr, s, self.engine.stickers, self.engine.stickers_custom)
        self.gestures = GesturesPage(tr, s)
        self.calib = CalibrationPage(tr, s)
        self.prefs = SettingsPage(tr, s)
        for page in (self.camera, self.effects, self.gestures, self.calib, self.prefs):
            self.stack.addWidget(page)
        layout.addWidget(self.stack, 1)
        self.nav.currentChanged.connect(self._on_nav)

        self.setCentralWidget(root)
        self.toast = Toast(root)
        self._wire()
        self.stack.setCurrentIndex(self._page_index)
        self.nav.set_current(self._page_index, animate=False)
        self._refresh_all()

    def _wire(self):
        s = self.settings
        cam, fx, g, cal, pref = self.camera, self.effects, self.gestures, self.calib, self.prefs

        for name, rows in {
            "hide_face": (cam.hide_face_row, fx.hide_face_row),
            "afk_enabled": (cam.afk_row, fx.afk_row),
            "draw_enabled": (cam.draw_row, fx.draw_row),
            "vcam": (cam.vcam_row,),
            "visualize": (fx.visualize_row,),
            "gaze": (fx.gaze_row,),
            "show_counter": (fx.counter_row,),
            "preview_visible": (fx.preview_row,),
            "fast_mode": (fx.fast_row,),
            "attach_photo": (fx.attach_row,),
            "rotate_sticker": (fx.rotate_row,),
        }.items():
            for row in rows:
                self._bind(name, row.toggle)
        self._bind("custom_gestures_enabled", g.enabled_toggle)

        fx.afk_slider.valueChanged.connect(lambda v: self._set("afk_timeout", v))
        fx.scale_slider.valueChanged.connect(lambda v: self._set("sticker_scale", v))
        fx.thickness_slider.valueChanged.connect(lambda v: self._set("draw_thickness", int(round(v))))
        fx.lifetime_slider.valueChanged.connect(lambda v: self._set("draw_lifetime", v))
        fx.swatches.changed.connect(lambda i: self._set("draw_color", i))
        fx.clear_btn.clicked.connect(self._clear_drawing)
        cam.clear_btn.clicked.connect(self._clear_drawing)
        cal.threshold.valueChanged.connect(lambda v: self._set("threshold", v))

        cam.start_btn.clicked.connect(self._toggle_running)
        cam.screenshot_btn.clicked.connect(self._screenshot)
        cam.camera_combo.currentIndexChanged.connect(self._on_camera_changed)
        cam.res_combo.currentIndexChanged.connect(self._on_resolution_changed)
        cam.preview.sizeChanged.connect(lambda w, h: setattr(self.engine, "preview_size", (w, h)))
        # Direct: only clears a flag, and must never depend on the engine's thread.
        cam.preview.framePainted.connect(self.engine.preview_consumed, Qt.ConnectionType.DirectConnection)
        cam.driver_btn.clicked.connect(self._install_driver)
        pref.driver_btn.clicked.connect(self._install_driver)

        fx.open_folder_btn.clicked.connect(lambda: self._open(paths.IMAGES_DIR))
        fx.reload_btn.clicked.connect(self._reload_stickers)

        g.diagram.fingerToggled.connect(self._toggle_finger)
        g.chips.fingerToggled.connect(self._toggle_finger)
        g.action_combo.currentIndexChanged.connect(self._on_action_changed)
        g.record_btn.clicked.connect(self._toggle_recording)
        g.add_btn.clicked.connect(self._add_gesture)
        g.diagram.set_pattern(self._pattern, animate=False)
        g.chips.set_pattern(self._pattern)
        self._on_action_changed()
        self._rebuild_gesture_list()

        cal.gaze_btn.clicked.connect(self._start_gaze_calibration)
        cal.gaze_reset_btn.clicked.connect(self._reset_gaze_calibration)
        cal.hand_btn.clicked.connect(self._toggle_hand_calibration)
        cal.hand_reset_btn.clicked.connect(self._reset_hand_calibration)

        pref.theme_row.toggle.toggled.connect(self._set_theme)
        pref.open_data_btn.clicked.connect(lambda: self._open(paths.DATA_DIR))

    # ===================================================== settings binding ====
    def _bind(self, name, toggle):
        self._toggles[name].append(toggle)
        toggle.toggled.connect(lambda checked, n=name: self._set(n, checked))

    def _set(self, name, value):
        if getattr(self.settings, name) == value:
            return
        setattr(self.settings, name, value)
        for toggle in self._toggles.get(name, ()):
            if toggle.isChecked() != value:
                toggle.set_silent(value)
        if name == "preview_visible":
            self._refresh_preview_state()
        elif name == "hide_face":
            self._refresh_covering()
        elif name == "vcam":
            self.engine.sync_vcam()
            self._refresh_vcam()
        elif name == "gaze" and not value:
            self.camera.gaze_map.set_point(None)
        self._save_timer.start()

    def _refresh_covering(self):
        on = self.settings.hide_face
        self.camera.preview.set_covering(on and self._camera_state == "live")
        self.covering_badge.set_active(on)

    def _clear_drawing(self):
        self.engine.clear_drawing()
        self.toast.show_message(self.tr("status_drawing_cleared"), "accent", "eraser")

    # ============================================================ navigation ====
    def _on_nav(self, index):
        self._page_index = index
        self.stack.set_index_animated(index)

    def _crossfade_rebuild(self):
        """Snapshot the window, rebuild underneath, then fade the snapshot out."""
        snapshot = self.grab()
        self._build()
        cover = QLabel(self)
        cover.setPixmap(snapshot)
        cover.setGeometry(0, 0, self.width(), self.height())
        cover.show()
        effect = QGraphicsOpacityEffect(cover)
        cover.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", cover)
        anim.setDuration(380)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.finished.connect(cover.deleteLater)
        anim.start()

    def _set_theme(self, dark):
        if dark == self.settings.dark_mode:
            return
        self.settings.dark_mode = dark
        theme.set_dark(dark)
        QApplication.instance().setStyleSheet(theme.stylesheet())
        set_dark_title_bar(self, dark)
        self._save_timer.start()
        QTimer.singleShot(0, self._crossfade_rebuild)

    # =========================================================== refreshers ====
    def _refresh_all(self):
        self._refresh_running_ui()
        self._refresh_preview_state()
        self._refresh_vcam()
        self._refresh_calibration()

    def _refresh_running_ui(self):
        self._refresh_covering()
        tr, cam = self.tr, self.camera
        running = self._camera_state != "stopped"
        cam.start_btn.setText(tr("stop_btn") if running else tr("start_btn"))
        cam.start_btn.set_icon("stop" if running else "play")
        cam.start_btn.set_kind("danger" if running else "primary")
        if self._camera_state == "live":
            cam.status_pill.set_state(self._status_text, "success", pulse=True)
            self.side_status.setText(f"● {self._status_text}")
        elif self._camera_state == "starting":
            cam.status_pill.set_state("…", "warning", pulse=True)
            self.side_status.setText("")
        else:
            cam.status_pill.set_state(tr("status_stopped"), "muted")
            self.side_status.setText("")
            cam.gesture_label.setText(tr("gesture_no_hand"))
            cam.gaze_label.setText(tr("gaze_status_off"))
            cam.fingers_view.clear()
            cam.gaze_map.set_point(None)

    _status_text = ""

    def _refresh_preview_state(self):
        preview = self.camera.preview
        if self._camera_state == "stopped":
            preview.set_state(PreviewWidget.STANDBY)
        elif not self.settings.preview_visible:
            preview.set_state(PreviewWidget.HIDDEN)
        elif self._camera_state == "starting":
            preview.set_state(PreviewWidget.STARTING)
        self.engine.preview_consumed()

    def _refresh_vcam(self):
        tr, cam, pref = self.tr, self.camera, self.prefs
        driver = self._driver_ok
        cam.driver_hint.setVisible(not driver)
        cam.driver_btn.setVisible(not driver and vcam.driver_files_available())
        pref.driver_btn.setVisible(vcam.driver_files_available())
        pref.driver_pill.set_state(tr("vcam_driver_ok") if driver else tr("vcam_status_missing"),
                                   "success" if driver else "warning")
        if self._vcam_info and self.settings.vcam:
            info = self._vcam_info
            if info.get("active"):
                cam.vcam_pill.set_state(f"{info['w']}×{info['h']}", "success", pulse=True)
            else:
                cam.vcam_pill.set_state(tr("vcam_status_waiting"), "accent")
            cam.vcam_row.toggle.setToolTip(tr("vcam_status_on", dev=info["dev"], w=info["w"], h=info["h"]))
        elif not driver:
            cam.vcam_pill.set_state(tr("vcam_status_missing"), "warning")
        else:
            cam.vcam_pill.set_state(tr("vcam_status_off"), "muted")

    def _refresh_calibration(self):
        tr, cal = self.tr, self.calib
        if self.engine.gaze_coeffs is not None:
            cal.gaze_pill.set_state(tr("gaze_calib_done_label"), "success")
        else:
            cal.gaze_pill.set_state(tr("not_calibrated"), "muted")
        calibrating = self.engine.hand_calibrating
        cal.hand_btn.setText(tr("hand_calib_cancel_btn") if calibrating else tr("hand_calib_btn"))
        cal.hand_btn.set_kind("danger" if calibrating else "primary")
        cal.hand_btn.set_icon("stop" if calibrating else "play")
        if not calibrating:
            done = self._hand_done
            if done:
                cal.hand_pill.set_state(tr("hand_calib_prev_done", list=", ".join(map(str, done))), "success")
                cal.steps.set_state(0, len(done))
            else:
                cal.hand_pill.set_state(tr("not_calibrated"), "muted")
                cal.steps.set_state(0, 0)
            cal.hand_status.setText(tr("hand_calib_reset_label") if not done else "")

    # ================================================================ camera ====
    def _toggle_running(self):
        if self._camera_state == "stopped":
            self._camera_state = "starting"
            self.engine.start()
        else:
            self.engine.stop()
        self._refresh_running_ui()
        self._refresh_preview_state()

    def _restart_if_running(self):
        if self._camera_state != "stopped":
            self.engine.stop()
            self._camera_state = "starting"
            self.engine.start()
            self._refresh_running_ui()
            self._refresh_preview_state()

    def _on_camera_changed(self, index):
        if index != self.settings.camera_index:
            self.settings.camera_index = index
            self._save_timer.start()
            self._restart_if_running()

    def _on_resolution_changed(self, index):
        value = RESOLUTIONS[index]
        if value != self.settings.resolution:
            self.settings.resolution = value
            self._save_timer.start()
            self._restart_if_running()

    def _on_started(self, w, h, rw, rh):
        note = "" if (w, h) == (rw, rh) else self.tr("status_running_mismatch_note", w=rw, h=rh)
        self._status_text = self.tr("status_running", w=w, h=h, note=note)
        self._camera_state = "live"
        self._refresh_running_ui()
        self._refresh_preview_state()

    def _on_stopped(self, ident):
        # Ignore a late signal from a worker that a restart already replaced.
        current = self.engine.worker_ident
        if current is not None and current != ident:
            return
        self._camera_state = "stopped"
        self._vcam_info = None
        self.engine.sync_vcam()
        if self._gaze_overlay is not None:
            self._close_gaze_overlay()
        self._refresh_all()

    def _on_failed(self, key, kwargs):
        QMessageBox.critical(self, self.tr("err_title"), self.tr(key, **kwargs))

    def _on_frame(self, array):
        if self.settings.preview_visible:
            self.camera.preview.set_frame(array)
        else:
            self.engine.preview_consumed()

    def _on_stats(self, stats):
        tr, cam = self.tr, self.camera
        cam.preview.set_fps(stats.get("fps", 0.0))
        gesture = stats.get("gesture")
        if gesture:
            cam.gesture_label.setText(tr(gesture[0], **gesture[1]))
        fingers = stats.get("fingers")
        if fingers != self._last_fingers:
            self._last_fingers = fingers
            if fingers:
                cam.fingers_view.setPixmap(pattern_icon(fingers))
            else:
                cam.fingers_view.clear()
        gaze = stats.get("gaze")
        if gaze:
            key, kw = gaze
            kw = dict(kw)
            if "zone_key" in kw:
                kw["zone"] = tr(kw.pop("zone_key"))
            if "direction_key" in kw:
                kw["direction"] = tr(kw.pop("direction_key"))
            cam.gaze_label.setText(tr(key, **kw))
        if self.settings.gaze:
            cam.gaze_map.set_point(stats.get("gaze_point"))

    def _screenshot(self):
        try:
            actions.take_screenshot()
            self.toast.show_message(self.tr("status_screenshot_saved"), "success", "check")
        except Exception:
            logger.exception("Screenshot failed")

    # ======================================================= virtual camera ====
    def _on_vcam_state(self, state, info):
        if state == "on":
            self._vcam_info = info
        elif state == "off":
            self._vcam_info = None
        elif state == "error":
            self._vcam_info = None
            for toggle in self._toggles["vcam"]:
                toggle.set_silent(False)
            self._save_timer.start()
            self._driver_ok = vcam.driver_installed()
            QMessageBox.warning(self, self.tr("err_vcam_title"),
                                self.tr("err_vcam_msg", err=info.get("err", "")))
        self._refresh_vcam()

    def _install_driver(self):
        ok, err = vcam.install_driver()
        self._driver_ok = vcam.driver_installed()
        if err == "OBS":  # macOS: the OBS download page was opened
            self.toast.show_message(self.tr("vcam_obs_opened"), "accent", "info", 5000)
        elif ok and self._driver_ok:
            self.toast.show_message(self.tr("vcam_install_ok"), "success", "check", 4500)
        else:
            QMessageBox.warning(self, self.tr("err_vcam_title"),
                                self.tr("vcam_install_fail", err=err or "?"))
        self._refresh_vcam()

    # ============================================================= stickers ====
    def _reload_stickers(self):
        self.engine.reload_stickers()
        QTimer.singleShot(150, lambda: self.effects.set_stickers(self.engine.stickers,
                                                                 self.engine.stickers_custom))
        self.toast.show_message(self.tr("status_stickers_reloaded"), "success", "check")

    def _open(self, path):
        try:
            paths.ensure_dirs()
            actions.open_path(path)
        except Exception:
            logger.exception("Could not open %s", path)

    # ============================================================= gestures ====
    def _toggle_finger(self, index):
        pattern = list(self._pattern)
        pattern[index] = not pattern[index]
        self._pattern = tuple(pattern)
        self.gestures.diagram.set_pattern(self._pattern)
        self.gestures.chips.set_pattern(self._pattern)

    def _current_action(self):
        return self.gestures.action_combo.currentData()

    def _on_action_changed(self, *_):
        key = self._current_action()
        g = self.gestures
        needs_param = key in ACTIONS_WITH_PARAM
        g.param_edit.setEnabled(needs_param)
        g.record_btn.setEnabled(key in ("hotkey", "key"))
        hint = f"hint_{key}" if needs_param else "hint_none"
        g.hint_label.setText(self.tr(hint))
        g.param_edit.setPlaceholderText(self.tr(hint) if needs_param else "")
        if not needs_param:
            g.param_edit.clear()
        self._stop_recording()

    def _toggle_recording(self):
        if self._recorder is not None:
            self._stop_recording()
            return
        g = self.gestures
        self._recorder = KeyRecorder(g.param_edit, self._current_action())
        self._recorder.finished.connect(self._recorded)
        g.record_btn.setText(self.tr("custom_capture_recording"))
        g.record_btn.set_kind("danger")

    def _recorded(self, value):
        if value:
            self.gestures.param_edit.setText(value)
        self._stop_recording()

    def _stop_recording(self):
        recorder, self._recorder = self._recorder, None
        if recorder is not None:
            try:
                self.gestures.param_edit.removeEventFilter(recorder)
            except RuntimeError:
                pass
            recorder.deleteLater()
        try:
            self.gestures.record_btn.setText(self.tr("custom_capture_btn"))
            self.gestures.record_btn.set_kind("secondary")
        except RuntimeError:
            pass

    def _add_gesture(self):
        g, tr = self.gestures, self.tr
        name = g.name_edit.text().strip()
        key = self._current_action()
        param = g.param_edit.text().strip()
        if not name:
            QMessageBox.warning(self, tr("err_title"), tr("custom_name_empty_msg"))
            return
        if key in ACTIONS_WITH_PARAM and not param:
            QMessageBox.warning(self, tr("err_title"), tr("custom_param_empty_msg"))
            return
        if key in ACTIONS_WITH_KEYS and not actions.PYAUTOGUI_AVAILABLE:
            QMessageBox.warning(self, tr("err_title"), tr("custom_pyautogui_missing_msg"))
            return
        self.custom_gestures.append({"name": name, "pattern": self._pattern,
                                     "action_type": key, "action_param": param})
        self._gestures_changed(animate_last=True)
        g.name_edit.clear()
        g.param_edit.clear()
        self.toast.show_message(tr("custom_added", name=name), "success", "check")

    def _delete_gesture(self, index, row):
        effect = QGraphicsOpacityEffect(row)
        row.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", row)
        anim.setDuration(180)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)

        def done():
            if 0 <= index < len(self.custom_gestures):
                del self.custom_gestures[index]
                self._gestures_changed()
        anim.finished.connect(done)
        anim.start()

    def _gestures_changed(self, animate_last=False):
        config.save_custom_gestures(self.custom_gestures)
        self.engine.custom_gestures = list(self.custom_gestures)
        self._rebuild_gesture_list(animate_last)

    def _rebuild_gesture_list(self, animate_last=False):
        layout, tr = self.gestures.list_layout, self.tr
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self.custom_gestures:
            empty = label(tr("custom_empty"), "muted")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setMinimumHeight(70)
            layout.addWidget(empty)
            return
        finger_names = [tr(k) for k in FINGER_KEYS]
        for i, gdef in enumerate(self.custom_gestures):
            row = QFrame()
            row.setObjectName("GestureRow")
            row.setStyleSheet(f"#GestureRow {{ background: {theme.hex_('surface2')}; border: 1px solid {theme.hex_('border')}; }}")
            h = QHBoxLayout(row)
            h.setContentsMargins(12, 10, 10, 10)
            h.setSpacing(12)
            icon = QLabel()
            icon.setPixmap(pattern_icon(gdef["pattern"]))
            icon.setFixedSize(34, 34)
            h.addWidget(icon)
            texts = QVBoxLayout()
            texts.setSpacing(1)
            title = label(gdef["name"])
            title.setFont(theme.font(10.5, QFont.Weight.DemiBold))
            texts.addWidget(title)
            raised = [n for n, up in zip(finger_names, gdef["pattern"]) if up] or ["—"]
            action = tr(f"action_{gdef['action_type']}")
            if gdef["action_param"]:
                action += f" · {gdef['action_param']}"
            texts.addWidget(label(f"{', '.join(raised)}  →  {action}", "faint"))
            h.addLayout(texts, 1)
            delete = Button("", "delete", "ghost")
            delete.setFixedWidth(40)
            delete.clicked.connect(lambda _=False, idx=i, r=row: self._delete_gesture(idx, r))
            h.addWidget(delete)
            layout.addWidget(row)
            if animate_last and i == len(self.custom_gestures) - 1:
                effect = QGraphicsOpacityEffect(row)
                row.setGraphicsEffect(effect)
                anim = QPropertyAnimation(effect, b"opacity", row)
                anim.setDuration(350)
                anim.setStartValue(0.0)
                anim.setEndValue(1.0)
                anim.finished.connect(lambda r=row: r.setGraphicsEffect(None))
                anim.start()

    def _on_gesture(self, gdef):
        action = gdef["action_type"]
        if action == "toggle_hide_face":
            self._set("hide_face", not self.settings.hide_face)
        elif action == "toggle_preview":
            self._set("preview_visible", not self.settings.preview_visible)
        elif action == "clear_drawing":
            self.engine.clear_drawing()
        elif action == "screenshot":
            self._screenshot()
        else:
            threading.Thread(target=actions.run_system_action,
                             args=(action, gdef.get("action_param", "")),
                             name="GestureAction", daemon=True).start()
        self.toast.show_message(self.tr("custom_triggered", name=gdef["name"],
                                        action=self.tr(f"action_{action}")), "accent", "gestures")

    # ========================================================== calibration ====
    def _need_camera(self):
        if self._camera_state == "stopped":
            QMessageBox.information(self, self.tr("info_need_camera_title"), self.tr("info_need_camera"))
            return True
        return False

    def _toggle_hand_calibration(self):
        if self.engine.hand_calibrating:
            self.engine.cancel_hand_calibration()
            self._refresh_calibration()
            return
        if self._need_camera():
            return
        self.engine.start_hand_calibration()
        self.calib.steps.set_state(1, 0)
        self._on_hand_progress("hand_calib_step_prep", {"n": 1})
        self._refresh_calibration()

    def _on_hand_progress(self, key, kwargs):
        cal = self.calib
        n = kwargs.get("n", 1)
        cal.steps.set_state(n, n - 1)
        cal.hand_status.setText(self.tr(key, **kwargs))
        cal.hand_pill.set_state(f"{n}/5", "accent", pulse=True)

    def _on_hand_finished(self, ok, data):
        if ok:
            self.engine.classifier.set_templates(data)
            config.save_hand_templates(data)
            self._hand_done = sorted(data)
            self.toast.show_message(self.tr("hand_calib_done"), "success", "check")
        else:
            QMessageBox.warning(self, self.tr("warn_hand_calib_interrupted_title"),
                                self.tr("warn_hand_calib_interrupted_msg", n=data.get("n", "?")))
        self._refresh_calibration()

    def _reset_hand_calibration(self):
        self.engine.cancel_hand_calibration()
        self.engine.classifier.set_templates({})
        config.save_hand_templates({})
        self._hand_done = []
        self._refresh_calibration()

    def _start_gaze_calibration(self):
        if self._need_camera() or self._gaze_overlay is not None:
            return
        overlay = GazeCalibrationOverlay(self.tr("gaze_calib_fullscreen_hint"))
        overlay.cancelled.connect(self._cancel_gaze_calibration)
        self._gaze_overlay = overlay
        geo = overlay.geometry()
        self.engine.screen_size = (geo.width(), geo.height())
        overlay.showFullScreen()
        overlay.activateWindow()
        overlay.setFocus()
        self.engine.start_gaze_calibration(len(overlay.targets))

    def _on_gaze_progress(self, index, fill):
        if self._gaze_overlay is not None:
            self._gaze_overlay.set_progress(index, fill)

    def _on_gaze_finished(self, ok, results):
        overlay = self._gaze_overlay
        if overlay is None:
            return
        targets = overlay.screen_targets()
        self._close_gaze_overlay()
        if not ok:
            QMessageBox.warning(self, self.tr("warn_face_not_found_title"),
                                self.tr("warn_face_not_found_msg"))
            return
        try:
            coeffs = fit_gaze(results, targets)
        except Exception:
            logger.exception("Gaze fit failed")
            QMessageBox.critical(self, self.tr("err_title"), self.tr("err_calib_build"))
            return
        self.engine.gaze_coeffs = coeffs
        config.save_gaze_calibration(coeffs)
        self._refresh_calibration()
        self.toast.show_message(self.tr("status_gaze_calib_done"), "success", "check")

    def _cancel_gaze_calibration(self):
        self.engine.cancel_gaze_calibration()
        self._close_gaze_overlay()
        self.toast.show_message(self.tr("status_gaze_calib_cancelled"), "warning", "info")

    def _close_gaze_overlay(self):
        overlay, self._gaze_overlay = self._gaze_overlay, None
        if overlay is not None:
            overlay.close()

    def _reset_gaze_calibration(self):
        self.engine.gaze_coeffs = None
        config.save_gaze_calibration(None)
        self._refresh_calibration()

    # ================================================================ close ====
    def showEvent(self, event):
        super().showEvent(event)
        screen = self.screen().geometry()
        self.engine.screen_size = (screen.width(), screen.height())

    def closeEvent(self, event):
        self._close_gaze_overlay()
        self.engine.shutdown()
        self._save_timer.stop()
        self.settings.save()
        super().closeEvent(event)
