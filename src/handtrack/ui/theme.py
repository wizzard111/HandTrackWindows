"""Colour tokens, fonts, SVG icons, shapes and the stylesheet.

Look: a strict instrument panel. Neutral greys; white marks what is on or
selected; red is a signal only (camera live, face hidden, errors). Square
corners, 1 px rules, monospace labels, numbered sections, thin grey tapes and
crosshairs. Nothing blinks or pulses. No gradients, no glow.
"""

import os

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer

from handtrack import paths

DARK = {
    "bg": "#0a0a0b",
    "sidebar": "#0d0d0e",
    "surface": "#121214",
    "surface2": "#18181b",
    "surface3": "#232327",
    "border": "#2c2c31",
    "text": "#e6e6e8",
    "muted": "#8f8f97",
    "faint": "#5a5a61",
    "tape": "#3a3a41",        # grey hatching
    "on": "#e6e6e8",          # switched on / selected
    "on_text": "#0a0a0b",
    "accent": "#a3112a",      # signal red: live, face hidden, errors
    "accent2": "#5a5a61",
    "accent_text": "#ffffff",
    "success": "#e6e6e8",
    "ok": "#e6e6e8",
    "danger": "#a3112a",
    "warning": "#a3112a",
    "stage": "#000000",
}

LIGHT = {
    "bg": "#ececee",
    "sidebar": "#e3e3e6",
    "surface": "#f8f8f9",
    "surface2": "#efeff1",
    "surface3": "#dedee2",
    "border": "#c9c9cf",
    "text": "#0b0b0c",
    "muted": "#55555d",
    "faint": "#8f8f97",
    "tape": "#b9b9c0",
    "on": "#111113",
    "on_text": "#ffffff",
    "accent": "#a3112a",
    "accent2": "#8f8f97",
    "accent_text": "#ffffff",
    "success": "#111113",
    "ok": "#0b0b0c",
    "danger": "#a3112a",
    "warning": "#a3112a",
    "stage": "#000000",
}

# Lucide icon file names (assets/icons, ISC license).
ICONS = {
    "camera": "video", "effects": "zap", "gestures": "hand", "calibration": "crosshair",
    "settings": "settings", "play": "play", "stop": "square", "screenshot": "camera",
    "moon": "moon", "sun": "sun", "folder": "folder-open", "refresh": "refresh-cw",
    "delete": "trash-2", "add": "plus", "eye": "eye", "shield": "shield",
    "info": "info", "record": "circle-dot", "pencil": "pencil",
    "sliders": "sliders-horizontal", "photo": "image", "check": "check", "globe": "globe",
    "eraser": "eraser", "brush": "brush",
}

_current = dict(DARK)
_dark = True


def is_dark():
    return _dark


def set_dark(dark):
    global _dark
    _dark = dark
    _current.clear()
    _current.update(DARK if dark else LIGHT)
    _ICON_CACHE.clear()


def c(name, alpha=None):
    color = QColor(_current[name])
    if alpha is not None:
        color.setAlphaF(alpha)
    return color


def hex_(name):
    return _current[name]


def mix(a, b, t):
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
        round(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


# ------------------------------------------------------------------- fonts ----
_UI_FAMILY = None
_MONO_FAMILY = None


def load_fonts():
    """Register the bundled monospace font. Call once after QApplication exists."""
    global _MONO_FAMILY
    families = []
    for name in ("JetBrainsMono-Regular.ttf", "JetBrainsMono-Bold.ttf"):
        path = os.path.join(paths.FONTS_DIR, name)
        if os.path.isfile(path):
            font_id = QFontDatabase.addApplicationFont(path)
            if font_id >= 0:
                families += QFontDatabase.applicationFontFamilies(font_id)
    _MONO_FAMILY = families[0] if families else mono_fallback()


def mono_fallback():
    available = set(QFontDatabase.families())
    for name in ("Cascadia Mono", "Consolas", "SF Mono", "Menlo", "DejaVu Sans Mono"):
        if name in available:
            return name
    return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()


def ui_family():
    global _UI_FAMILY
    if _UI_FAMILY is None:
        available = set(QFontDatabase.families())
        for name in ("Segoe UI Variable Text", "Segoe UI", "SF Pro Text", ".AppleSystemUIFont",
                     "Helvetica Neue", "Inter", "Ubuntu", "Cantarell", "Noto Sans", "DejaVu Sans"):
            if name in available:
                _UI_FAMILY = name
                break
        else:
            _UI_FAMILY = QFont().defaultFamily()
    return _UI_FAMILY


def mono_family():
    return _MONO_FAMILY or mono_fallback()


def font(size=10, weight=QFont.Weight.Normal):
    f = QFont(ui_family())
    f.setPointSizeF(size)
    f.setWeight(weight)
    return f


def mono(size=9, bold=True, spacing=0.6, upper=True):
    """Monospace label / read-out font."""
    f = QFont(mono_family())
    f.setPointSizeF(size)
    f.setWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal)
    if upper:
        f.setCapitalization(QFont.Capitalization.AllUppercase)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return f


def display_font(size=12, spacing=1.0):
    """Headings use the bold mono face, upper case, with restrained tracking."""
    return mono(size, True, min(spacing, 1.0) * 0.7)


# ------------------------------------------------------------------- icons ----
_SVG_CACHE = {}
_ICON_CACHE = {}


def _svg(name):
    data = _SVG_CACHE.get(name)
    if data is None:
        try:
            with open(os.path.join(paths.ICONS_DIR, ICONS.get(name, name) + ".svg"), encoding="utf-8") as f:
                data = f.read()
        except OSError:
            data = ""
        data = data.replace('stroke-linecap="round"', 'stroke-linecap="square"') \
                   .replace('stroke-linejoin="round"', 'stroke-linejoin="miter"')
        _SVG_CACHE[name] = data
    return data


def icon_pixmap(name, color, size=18, ratio=2.0, stroke=1.8):
    """Render an SVG icon in the given colour (QColor or token name)."""
    if not isinstance(color, QColor):
        color = c(color)
    key = (name, color.rgba(), size, ratio, stroke)
    pix = _ICON_CACHE.get(key)
    if pix is not None:
        return pix
    svg = _svg(name).replace("currentColor", color.name()).replace(
        'stroke-width="2"', f'stroke-width="{stroke}"')
    px = max(1, int(size * ratio))
    pix = QPixmap(px, px)
    pix.fill(Qt.GlobalColor.transparent)
    if svg:
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if color.alphaF() < 1:
            p.setOpacity(color.alphaF())
        QSvgRenderer(QByteArray(svg.encode())).render(p, QRectF(0, 0, px, px))
        p.end()
    pix.setDevicePixelRatio(ratio)
    _ICON_CACHE[key] = pix
    return pix


def draw_icon(painter, name, rect, color, stroke=1.8):
    size = int(min(rect.width(), rect.height()))
    ratio = max(1.0, painter.device().devicePixelRatioF()) if painter.device() else 2.0
    pix = icon_pixmap(name, color, size, ratio, stroke)
    painter.drawPixmap(QPointF(rect.center().x() - size / 2, rect.center().y() - size / 2), pix)


# ------------------------------------------------------------------ shapes ----
def chamfer_path(rect, cut=0, corners="tl,br"):
    """Plain rectangle. Every panel, button and tag is square-cornered; the
    ``cut`` argument is accepted for call-site compatibility and ignored."""
    path = QPainterPath()
    path.addRect(QRectF(rect))
    return path


def draw_corner_marks(painter, rect, color, length=8, width=1.5):
    """Registration marks in the four corners of ``rect``."""
    painter.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap))
    r = QRectF(rect)
    for x, y, dx, dy in ((r.left(), r.top(), 1, 1), (r.right(), r.top(), -1, 1),
                         (r.left(), r.bottom(), 1, -1), (r.right(), r.bottom(), -1, -1)):
        painter.drawLine(QPointF(x, y), QPointF(x + dx * length, y))
        painter.drawLine(QPointF(x, y), QPointF(x, y + dy * length))


def draw_hazard(painter, rect, color, step=8, back=None):
    """Diagonal warning-tape stripes clipped to ``rect``."""
    r = QRectF(rect)
    painter.save()
    painter.setClipRect(r)
    if back is not None:
        painter.fillRect(r, back)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    x = r.left() - r.height()
    while x < r.right():
        path = QPainterPath()
        path.moveTo(x, r.bottom())
        path.lineTo(x + step / 2, r.bottom())
        path.lineTo(x + step / 2 + r.height(), r.top())
        path.lineTo(x + r.height(), r.top())
        path.closeSubpath()
        painter.drawPath(path)
        x += step
    painter.restore()


def stylesheet():
    t = _current
    arrow = os.path.join(paths.ICONS_DIR, "combo-arrow.svg").replace("\\", "/")
    mono_f = mono_family()
    return f"""
    QWidget {{ color: {t['text']}; font-family: "{ui_family()}"; font-size: 10pt; }}
    QMainWindow, #Root {{ background: {t['bg']}; }}
    QToolTip {{
        background: {t['surface3']}; color: {t['text']}; border: 1px solid {t['border']};
        padding: 5px 7px; font-family: "{mono_f}"; font-size: 9pt;
    }}
    QLabel {{ background: transparent; }}
    QLabel[role="subtitle"] {{ color: {t['muted']}; font-size: 10pt; }}
    QLabel[role="muted"] {{ color: {t['muted']}; }}
    QLabel[role="faint"] {{ color: {t['faint']}; font-size: 9pt; }}
    QLabel[role="mono"] {{ font-family: "{mono_f}"; font-size: 9pt; color: {t['muted']}; }}

    QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
    QScrollBar:vertical {{ background: transparent; width: 6px; margin: 2px 0; }}
    QScrollBar::handle:vertical {{ background: {t['surface3']}; min-height: 40px; }}
    QScrollBar::handle:vertical:hover {{ background: {t['faint']}; }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
        height: 0; background: none;
    }}

    QComboBox, QLineEdit {{
        background: {t['surface2']}; border: 1px solid {t['border']}; border-radius: 0;
        padding: 6px 10px; min-height: 20px; font-family: "{mono_f}"; font-size: 9.5pt;
        selection-background-color: {t['surface3']}; selection-color: {t['text']};
    }}
    QComboBox:hover, QLineEdit:hover {{ border-color: {t['faint']}; }}
    QComboBox:focus, QLineEdit:focus {{ border-color: {t['muted']}; }}
    QLineEdit:disabled, QComboBox:disabled {{ color: {t['faint']}; }}
    QComboBox::drop-down {{ border: none; border-left: 1px solid {t['border']}; width: 26px; }}
    QComboBox::down-arrow {{ image: url("{arrow}"); width: 10px; height: 7px; }}
    QComboBox QAbstractItemView {{
        background: {t['surface2']}; border: 1px solid {t['border']}; padding: 0; outline: none;
        selection-background-color: {t['surface3']}; selection-color: {t['text']};
        font-family: "{mono_f}";
    }}

    QSlider::groove:horizontal {{ height: 2px; background: {t['surface3']}; }}
    QSlider::sub-page:horizontal {{ background: {t['on']}; }}
    QSlider::handle:horizontal {{
        background: {t['text']}; width: 8px; height: 16px; margin: -7px 0;
    }}
    QSlider::handle:horizontal:hover {{ background: {t['muted']}; }}

    QMessageBox {{ background: {t['surface']}; }}
    QMessageBox QPushButton {{
        background: {t['surface3']}; border: 1px solid {t['border']}; padding: 6px 16px;
        min-width: 70px; font-family: "{mono_f}";
    }}
    QMessageBox QPushButton:hover {{ background: {t['on']}; color: {t['on_text']}; border-color: {t['on']}; }}
    """
