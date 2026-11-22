"""The five pages of the main window. They only build widgets; MainWindow
wires them to settings and to the engine."""

import cv2
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QVBoxLayout, QWidget,
)

from handtrack import VCAM_DEVICE_NAME, __version__, paths
from handtrack.config import ACTION_KEYS, RESOLUTIONS
from handtrack.ui import theme
from handtrack.ui.visuals import FingerChips, GazeMap, HandDiagram, PreviewWidget
from handtrack.ui.widgets import (
    Button, Card, Pill, Segmented, SettingRow, SliderRow, Swatches, Toggle, heading, hline, label,
    tag_label,
)


class HazardRule(QWidget):
    """Short warning-tape bar under a page title."""

    def __init__(self, width=120):
        super().__init__()
        self.setFixedSize(width, 6)

    def paintEvent(self, event):
        p = QPainter(self)
        theme.draw_hazard(p, QRectF(self.rect()), theme.c("accent"), 8, theme.c("stage"))


def number_cards(page, code):
    """Give the page's panels running codes like 02.01, 02.02 …"""
    for i, card in enumerate(page.findChildren(Card), 1):
        card.set_code(f"{code}.{i:02d}")
from handtrack.vision.render import DRAW_COLORS

FINGER_KEYS = ("finger_thumb", "finger_index", "finger_middle", "finger_ring", "finger_pinky")


def scroll(widget):
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setWidget(widget)
    return area


def page_header(title, subtitle=None, code=None):
    box = QVBoxLayout()
    box.setSpacing(2)
    if code:
        box.addWidget(tag_label(f"HANDTRACK // SECTION {code}", "accent", 8))
    box.addWidget(heading(title, 24, 3))
    box.addWidget(HazardRule())
    if subtitle:
        box.addWidget(label(subtitle, "subtitle", wrap=True))
    return box


def page_container():
    inner = QWidget()
    col = QVBoxLayout(inner)
    col.setContentsMargins(32, 28, 32, 32)
    col.setSpacing(18)
    return inner, col


def vcam_desc(tr):
    if paths.IS_MAC:
        return tr("vcam_desc_mac")
    return tr("vcam_desc", device=VCAM_DEVICE_NAME)


def driver_button_text(tr):
    return tr("vcam_install_obs_btn") if paths.IS_MAC else tr("vcam_install_btn")


# ------------------------------------------------------------------ camera ----
class CameraPage(QWidget):
    def __init__(self, tr, s):
        super().__init__()
        root = QHBoxLayout(self)
        root.setContentsMargins(24, 24, 16, 24)
        root.setSpacing(20)

        left = QVBoxLayout()
        left.setSpacing(14)
        self.preview = PreviewWidget()
        self.preview.set_texts(tr("standby_title"), tr("standby_hint"), tr("preview_hidden"), tr("live"),
                               tr("covering"), tr("covering_sub"))
        left.addWidget(self.preview, 1)

        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.start_btn = Button(tr("start_btn"), "play", "primary")
        self.start_btn.setMinimumWidth(140)
        bar.addWidget(self.start_btn)
        self.camera_combo = QComboBox()
        self.camera_combo.addItems([tr("camera_n", n=i + 1) for i in range(5)])
        self.camera_combo.setCurrentIndex(min(max(s.camera_index, 0), 4))
        bar.addWidget(self.camera_combo)
        self.res_combo = QComboBox()
        self.res_combo.addItems([r.replace("x", " × ") for r in RESOLUTIONS])
        self.res_combo.setCurrentIndex(RESOLUTIONS.index(s.resolution))
        bar.addWidget(self.res_combo)
        bar.addStretch(1)
        self.clear_btn = Button(tr("draw_clear_btn"), "eraser", "ghost")
        bar.addWidget(self.clear_btn)
        self.screenshot_btn = Button(tr("screenshot_btn"), "screenshot", "ghost")
        bar.addWidget(self.screenshot_btn)
        left.addLayout(bar)
        root.addLayout(left, 1)

        side = QWidget()
        side.setFixedWidth(340)
        col = QVBoxLayout(side)
        col.setContentsMargins(0, 0, 8, 0)
        col.setSpacing(14)

        status = Card(tr("sec_status"), "info")
        self.status_pill = Pill(tr("status_stopped"))
        status.header.addWidget(self.status_pill)
        self.gesture_label = label(tr("gesture_no_hand"))
        self.gaze_label = label(tr("gaze_status_off"), "muted")
        self.fingers_view = QLabel()
        self.fingers_view.setFixedSize(34, 34)
        row = QHBoxLayout()
        row.addWidget(self.gesture_label, 1)
        row.addWidget(self.fingers_view)
        status.body.addLayout(row)
        status.body.addWidget(self.gaze_label)
        col.addWidget(status)

        gaze = Card(tr("sec_gaze_map"), "eye")
        self.gaze_map = GazeMap()
        gaze.body.addWidget(self.gaze_map)
        col.addWidget(gaze)

        vcam = Card(tr("sec_vcam"), "camera")
        self.vcam_pill = Pill(tr("vcam_status_off"))
        pill_row = QHBoxLayout()
        pill_row.addWidget(self.vcam_pill)
        pill_row.addStretch(1)
        vcam.body.addLayout(pill_row)
        self.vcam_row = SettingRow(tr("vcam_cb"), vcam_desc(tr), s.vcam)
        vcam.body.addWidget(self.vcam_row)
        self.driver_hint = label(tr("vcam_missing_hint_mac") if paths.IS_MAC else tr("vcam_missing_hint"),
                                 "faint", wrap=True)
        self.driver_btn = Button(driver_button_text(tr), "add", "secondary")
        vcam.body.addWidget(self.driver_hint)
        vcam.body.addWidget(self.driver_btn)
        col.addWidget(vcam)

        quick = Card(tr("sec_privacy"), "shield")
        self.hide_face_row = SettingRow(tr("hide_face_cb"), None, s.hide_face)
        self.afk_row = SettingRow(tr("afk_cb"), None, s.afk_enabled)
        self.draw_row = SettingRow(tr("draw_cb"), None, s.draw_enabled)
        for w in (self.hide_face_row, self.afk_row, self.draw_row):
            quick.body.addWidget(w)
        col.addWidget(quick)
        col.addStretch(1)
        side_area = scroll(side)
        side_area.setFixedWidth(340 + 12)
        root.addWidget(side_area)
        number_cards(self, "01")


# ----------------------------------------------------------------- effects ----
class EffectsPage(QWidget):
    def __init__(self, tr, s, stickers, stickers_custom):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        inner, col = page_container()
        col.addLayout(page_header(tr("nav_effects"), code="02"))
        self._tr = tr

        grid = QGridLayout()
        grid.setSpacing(16)

        tracking = Card(tr("sec_tracking"), "sliders")
        self.visualize_row = SettingRow(tr("visualize_cb"), tr("visualize_desc"), s.visualize)
        self.gaze_row = SettingRow(tr("gaze_cb"), None, s.gaze)
        self.counter_row = SettingRow(tr("counter_cb"), None, s.show_counter)
        self.preview_row = SettingRow(tr("preview_cb"), None, s.preview_visible)
        self.fast_row = SettingRow(tr("fastmode_cb"), tr("fastmode_desc"), s.fast_mode)
        for w in (self.visualize_row, self.gaze_row, self.counter_row, self.preview_row, self.fast_row):
            tracking.body.addWidget(w)
        tracking.body.addStretch(1)
        grid.addWidget(tracking, 0, 0)

        privacy = Card(tr("sec_privacy"), "shield")
        self.hide_face_row = SettingRow(tr("hide_face_cb"), tr("hide_face_desc"), s.hide_face)
        self.afk_row = SettingRow(tr("afk_cb"), tr("afk_desc"), s.afk_enabled)
        self.afk_slider = SliderRow(tr("afk_timeout_label"), 2, 30, s.afk_timeout, 1,
                                    lambda v: tr("seconds", v=v))
        for w in (self.hide_face_row, self.afk_row, self.afk_slider):
            privacy.body.addWidget(w)
        privacy.body.addStretch(1)
        grid.addWidget(privacy, 0, 1)

        draw = Card(tr("sec_drawing"), "brush")
        self.draw_row = SettingRow(tr("draw_cb"), tr("draw_desc"), s.draw_enabled, "pencil")
        draw.body.addWidget(self.draw_row)
        colors = QHBoxLayout()
        colors.addWidget(label(tr("draw_color")))
        colors.addStretch(1)
        self.swatches = Swatches(["#%02x%02x%02x" % (r, g, b) for b, g, r in DRAW_COLORS], s.draw_color)
        colors.addWidget(self.swatches)
        draw.body.addLayout(colors)
        self.thickness_slider = SliderRow(tr("draw_thickness"), 2, 20, s.draw_thickness, 1,
                                          lambda v: f"{v:.0f} px")
        self.lifetime_slider = SliderRow(tr("draw_lifetime"), 0, 60, s.draw_lifetime, 1,
                                         lambda v: "∞" if v < 0.5 else tr("seconds", v=v))
        for w in (self.thickness_slider, self.lifetime_slider):
            draw.body.addWidget(w)
        b = QHBoxLayout()
        self.clear_btn = Button(tr("draw_clear_btn"), "eraser", "secondary")
        b.addWidget(self.clear_btn)
        b.addStretch(1)
        draw.body.addLayout(b)
        grid.addWidget(draw, 1, 0)

        st = Card(tr("sec_stickers"), "photo")
        self.attach_row = SettingRow(tr("attach_cb"), None, s.attach_photo)
        self.rotate_row = SettingRow(tr("rotate_cb"), None, s.rotate_sticker)
        self.scale_slider = SliderRow(tr("sticker_size_label"), 0.4, 3.0, s.sticker_scale, 0.05,
                                      lambda v: f"×{v:.2f}")
        for w in (self.attach_row, self.rotate_row, self.scale_slider):
            st.body.addWidget(w)
        self.thumbs = QHBoxLayout()
        self.thumbs.setSpacing(8)
        st.body.addLayout(self.thumbs)
        st.body.addWidget(label(tr("sticker_hint"), "faint", wrap=True))
        btns = QHBoxLayout()
        self.open_folder_btn = Button(tr("open_folder_btn"), "folder", "secondary")
        self.reload_btn = Button(tr("reload_stickers_btn"), "refresh", "ghost")
        btns.addWidget(self.open_folder_btn)
        btns.addWidget(self.reload_btn)
        btns.addStretch(1)
        st.body.addLayout(btns)
        grid.addWidget(st, 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        col.addLayout(grid)
        col.addStretch(1)
        outer.addWidget(scroll(inner))
        self.set_stickers(stickers, stickers_custom)
        number_cards(self, "02")

    def set_stickers(self, stickers, custom):
        while self.thumbs.count():
            item = self.thumbs.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for n in range(1, 6):
            img = QLabel()
            img.setFixedSize(52, 52)
            rgba = cv2.cvtColor(cv2.resize(stickers[n], (104, 104), interpolation=cv2.INTER_AREA),
                                cv2.COLOR_BGRA2RGBA)
            qimg = QImage(rgba.data, 104, 104, 104 * 4, QImage.Format.Format_RGBA8888).copy()
            pix = QPixmap.fromImage(qimg)
            pix.setDevicePixelRatio(2.0)
            img.setPixmap(pix)
            border = theme.hex_("accent") if custom[n] else theme.hex_("border")
            img.setStyleSheet(f"background: {theme.hex_('stage')}; border: 1px solid {border};")
            img.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img.setToolTip(f"gesture_{n} · " + (self._tr("sticker_custom") if custom[n]
                                                 else self._tr("sticker_placeholder")))
            self.thumbs.addWidget(img)
        self.thumbs.addStretch(1)


# ---------------------------------------------------------------- gestures ----
class GesturesPage(QWidget):
    def __init__(self, tr, s):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        inner, col = page_container()
        head = QHBoxLayout()
        head.addLayout(page_header(tr("nav_gestures"), tr("gesture_designer_intro"), "03"), 1)
        enabled_box = QHBoxLayout()
        enabled_box.setSpacing(10)
        enabled_box.addWidget(label(tr("custom_enabled_cb"), "muted"))
        self.enabled_toggle = Toggle(s.custom_gestures_enabled)
        enabled_box.addWidget(self.enabled_toggle)
        head.addLayout(enabled_box)
        col.addLayout(head)

        top = QHBoxLayout()
        top.setSpacing(16)
        designer = Card(tr("gesture_designer_title"), "gestures")
        self.diagram = HandDiagram(290)
        designer.body.addWidget(self.diagram, 0, Qt.AlignmentFlag.AlignHCenter)
        self.chips = FingerChips([tr(k + "_short") for k in FINGER_KEYS])
        designer.body.addWidget(self.chips)
        designer.setFixedWidth(360)
        top.addWidget(designer)

        form = Card(tr("custom_add_btn"), "add")
        form.body.setSpacing(8)
        form.body.addWidget(label(tr("custom_name_label"), "muted"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(tr("custom_name_placeholder"))
        form.body.addWidget(self.name_edit)
        form.body.addSpacing(4)
        form.body.addWidget(label(tr("custom_action_label"), "muted"))
        self.action_combo = QComboBox()
        for key in ACTION_KEYS:
            self.action_combo.addItem(tr(f"action_{key}"), key)
        form.body.addWidget(self.action_combo)
        form.body.addSpacing(4)
        form.body.addWidget(label(tr("custom_param_label"), "muted"))
        prow = QHBoxLayout()
        self.param_edit = QLineEdit()
        prow.addWidget(self.param_edit, 1)
        self.record_btn = Button(tr("custom_capture_btn"), "record", "secondary")
        prow.addWidget(self.record_btn)
        form.body.addLayout(prow)
        self.hint_label = label("", "faint")
        form.body.addWidget(self.hint_label)
        form.body.addStretch(1)
        self.add_btn = Button(tr("custom_add_btn"), "add", "primary")
        form.body.addWidget(self.add_btn)
        top.addWidget(form, 1)
        col.addLayout(top)

        self.list_card = Card(tr("custom_frame"), "sliders", spacing=8)
        self.list_layout = QVBoxLayout()
        self.list_layout.setSpacing(8)
        self.list_card.body.addLayout(self.list_layout)
        col.addWidget(self.list_card)
        col.addStretch(1)
        outer.addWidget(scroll(inner))
        number_cards(self, "03")


# ------------------------------------------------------------- calibration ----
class StepDots(QWidget):
    """Five numbered steps: done, current and pending."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(40)
        self.current, self.done = 0, 0

    def set_state(self, current, done):
        self.current, self.done = current, done
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        n = 5
        gap = (self.width() - 2 * 18) / (n - 1)
        y = self.height() / 2
        p.setPen(QPen(theme.c("surface3"), 3))
        p.drawLine(18, int(y), int(self.width() - 18), int(y))
        if self.done > 0:
            p.setPen(QPen(theme.c("accent"), 3))
            p.drawLine(18, int(y), int(18 + gap * min(self.done, n - 1)), int(y))
        p.setFont(theme.display_font(9, 0))
        for i in range(n):
            x = 18 + gap * i
            current = i + 1 == self.current
            if i < self.done:
                p.setBrush(theme.c("accent"))
                fg = theme.c("accent_text")
            elif current:
                p.setBrush(theme.c("accent2"))
                fg = theme.c("accent_text")
            else:
                p.setBrush(theme.c("surface3"))
                fg = theme.c("muted")
            p.setPen(QPen(theme.c("accent"), 2) if current else Qt.PenStyle.NoPen)
            r = 14 if current else 12
            box = QRectF(x - r, y - r, 2 * r, 2 * r)
            p.drawPath(theme.chamfer_path(box, 5, "tl,tr,br,bl"))
            p.setPen(fg)
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, str(i + 1))


class CalibrationPage(QWidget):
    def __init__(self, tr, s):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        inner, col = page_container()
        col.addLayout(page_header(tr("nav_calibration"), code="04"))

        row = QHBoxLayout()
        row.setSpacing(16)
        gaze = Card(tr("gaze_calib_title"), "eye")
        self.gaze_pill = Pill("")
        gaze.header.addWidget(self.gaze_pill)
        gaze.body.addWidget(label(tr("gaze_calib_desc"), "muted", wrap=True))
        gaze.body.addStretch(1)
        gbtn = QHBoxLayout()
        self.gaze_btn = Button(tr("gaze_calib_btn"), "calibration", "primary")
        self.gaze_reset_btn = Button(tr("gaze_calib_reset_btn"), "refresh", "ghost")
        gbtn.addWidget(self.gaze_btn)
        gbtn.addWidget(self.gaze_reset_btn)
        gbtn.addStretch(1)
        gaze.body.addLayout(gbtn)
        row.addWidget(gaze, 1)

        hand = Card(tr("hand_calib_title"), "gestures")
        self.hand_pill = Pill("")
        hand.header.addWidget(self.hand_pill)
        hand.body.addWidget(label(tr("hand_calib_desc"), "muted", wrap=True))
        self.steps = StepDots()
        hand.body.addWidget(self.steps)
        self.hand_status = label("", "faint")
        hand.body.addWidget(self.hand_status)
        hbtn = QHBoxLayout()
        self.hand_btn = Button(tr("hand_calib_btn"), "play", "primary")
        self.hand_reset_btn = Button(tr("hand_calib_reset_btn"), "refresh", "ghost")
        hbtn.addWidget(self.hand_btn)
        hbtn.addWidget(self.hand_reset_btn)
        hbtn.addStretch(1)
        hand.body.addLayout(hbtn)
        row.addWidget(hand, 1)
        col.addLayout(row)

        thr = Card(tr("sec_recognition"), "sliders")
        self.threshold = SliderRow(tr("threshold_label"), 0.2, 1.2, s.threshold, 0.01)
        thr.body.addWidget(self.threshold)
        col.addWidget(thr)
        col.addStretch(1)
        outer.addWidget(scroll(inner))
        number_cards(self, "04")


# ---------------------------------------------------------------- settings ----
class SettingsPage(QWidget):
    def __init__(self, tr, s):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        inner, col = page_container()
        col.addLayout(page_header(tr("nav_settings"), code="05"))

        look = Card(tr("sec_appearance"), "moon")
        self.theme_row = SettingRow(tr("theme_dark"), None, s.dark_mode)
        look.body.addWidget(self.theme_row)
        lang = QHBoxLayout()
        lang.addWidget(label(tr("language")))
        lang.addStretch(1)
        self.lang_switch = Segmented(["Русский", "English"], 0 if s.lang == "ru" else 1)
        lang.addWidget(self.lang_switch)
        look.body.addLayout(lang)
        col.addWidget(look)

        drv = Card(tr("sec_vcam"), "camera")
        self.driver_pill = Pill("")
        drv.header.addWidget(self.driver_pill)
        drv.body.addWidget(label(vcam_desc(tr), "muted", wrap=True))
        self.driver_btn = Button(driver_button_text(tr), "add", "secondary")
        b = QHBoxLayout()
        b.addWidget(self.driver_btn)
        b.addStretch(1)
        drv.body.addLayout(b)
        col.addWidget(drv)

        data = Card(tr("settings_data_dir"), "folder")
        r = QHBoxLayout()
        path = label(paths.DATA_DIR, "mono")
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        r.addWidget(path, 1)
        self.open_data_btn = Button(tr("settings_open_data"), "folder", "ghost")
        r.addWidget(self.open_data_btn)
        data.body.addLayout(r)
        col.addWidget(data)

        about = Card(tr("settings_about"), "info")
        about.body.addWidget(label(tr("settings_about_text", version=__version__), "muted"))
        about.body.addWidget(hline())
        about.body.addWidget(label(tr("settings_uninstall_hint"), "faint", wrap=True))
        col.addWidget(about)
        col.addStretch(1)
        outer.addWidget(scroll(inner))
        number_cards(self, "05")
