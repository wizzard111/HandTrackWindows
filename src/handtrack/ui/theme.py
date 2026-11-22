"""Colour tokens, fonts, SVG icons, chamfered shapes and the stylesheet.

Look: black and white with blood red and deep purple, hard chamfered
corners, uppercase display headings.
"""

import os

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPainterPath, QPixmap
from PySide6.QtSvg import QSvgRenderer

from handtrack import paths

DARK = {
    "bg": "#060509",
    "sidebar": "#0a080e",
    "surface": "#100d15",
    "surface2": "#17121e",
    "surface3": "#221a2c",
    "border": "#2b2236",
    "text": "#f5f3f8",
    "muted": "#9a92a8",
    "faint": "#5f5769",
    "accent": "#ff1f45",      # red
    "accent2": "#5b1fb8",     # deep purple
    "accent_text": "#ffffff",
    "success": "#ff1f45",     # "on" states are red, too
    "ok": "#f5f3f8",
    "danger": "#ff1f45",
    "warning": "#a855f7",
    "stage": "#000000",
}

LIGHT = {
    "bg": "#efeef2",
    "sidebar": "#e5e3ea",
    "surface": "#ffffff",
    "surface2": "#f2f1f5",
    "surface3": "#e2dfe8",
    "border": "#d4d0dc",
    "text": "#0b0a0e",
    "muted": "#5a5366",
    "faint": "#958ea1",
    "accent": "#e0102f",
    "accent2": "#4a168f",
    "accent_text": "#ffffff",
    "success": "#e0102f",
    "ok": "#0b0a0e",
    "danger": "#e0102f",
    "warning": "#6d28d9",
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

CHAMFER = 9

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
_DISPLAY_FAMILY = None


def load_fonts():
    """Register the bundled display font. Call once after QApplication exists."""
    global _DISPLAY_FAMILY
    path = os.path.join(paths.FONTS_DIR, "RussoOne-Regular.ttf")
    font_id = QFontDatabase.addApplicationFont(path) if os.path.isfile(path) else -1
    families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
    _DISPLAY_FAMILY = families[0] if families else ui_family()


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


def font(size=10, weight=QFont.Weight.Normal):
    f = QFont(ui_family())
    f.setPointSizeF(size)
    f.setWeight(weight)
    return f


def display_font(size=12, spacing=1.5):
    f = QFont(_DISPLAY_FAMILY or ui_family())
    f.setPointSizeF(size)
    f.setCapitalization(QFont.Capitalization.AllUppercase)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return f


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
        # Sharper strokes for the aggressive look.
        data = data.replace('stroke-linecap="round"', 'stroke-linecap="square"') \
                   .replace('stroke-linejoin="round"', 'stroke-linejoin="miter"')
        _SVG_CACHE[name] = data
    return data


def icon_pixmap(name, color, size=18, ratio=2.0, stroke=2.2):
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


def draw_icon(painter, name, rect, color, stroke=2.2):
    size = int(min(rect.width(), rect.height()))
    ratio = max(1.0, painter.device().devicePixelRatioF()) if painter.device() else 2.0
    pix = icon_pixmap(name, color, size, ratio, stroke)
    painter.drawPixmap(QPointF(rect.center().x() - size / 2, rect.center().y() - size / 2), pix)


# ------------------------------------------------------------------ shapes ----
def chamfer_path(rect, cut=CHAMFER, corners="tl,br"):
    """Rectangle with diagonally cut corners."""
    r = QRectF(rect)
    cuts = {k: (cut if k in corners else 0) for k in ("tl", "tr", "br", "bl")}
    path = QPainterPath()
    path.moveTo(r.left() + cuts["tl"], r.top())
    path.lineTo(r.right() - cuts["tr"], r.top())
    path.lineTo(r.right(), r.top() + cuts["tr"])
    path.lineTo(r.right(), r.bottom() - cuts["br"])
    path.lineTo(r.right() - cuts["br"], r.bottom())
    path.lineTo(r.left() + cuts["bl"], r.bottom())
    path.lineTo(r.left(), r.bottom() - cuts["bl"])
    path.lineTo(r.left(), r.top() + cuts["tl"])
    path.closeSubpath()
    return path


def stylesheet():
    t = _current
    arrow = os.path.join(paths.ICONS_DIR, "combo-arrow.svg").replace("\\", "/")
    return f"""
    QWidget {{ color: {t['text']}; font-family: "{ui_family()}"; font-size: 10pt; }}
    QMainWindow, #Root {{ background: {t['bg']}; }}
    QToolTip {{
        background: {t['surface3']}; color: {t['text']};
        border: 1px solid {t['accent']}; padding: 6px 8px;
    }}
    QLabel {{ background: transparent; }}
    QLabel[role="subtitle"] {{ color: {t['muted']}; font-size: 10pt; }}
    QLabel[role="muted"] {{ color: {t['muted']}; }}
    QLabel[role="faint"] {{ color: {t['faint']}; font-size: 9pt; }}
    QLabel[role="mono"] {{ font-family: "Cascadia Mono", "SF Mono", Menlo, "DejaVu Sans Mono", monospace;
                           color: {t['muted']}; }}

    QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 4px 1px; }}
    QScrollBar::handle:vertical {{ background: {t['surface3']}; min-height: 40px; }}
    QScrollBar::handle:vertical:hover {{ background: {t['accent']}; }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
        height: 0; background: none;
    }}

    QComboBox, QLineEdit {{
        background: {t['surface2']}; border: 1px solid {t['border']};
        border-radius: 0; padding: 7px 11px; min-height: 20px;
        selection-background-color: {t['accent']};
    }}
    QComboBox:hover, QLineEdit:hover {{ border-color: {t['faint']}; }}
    QComboBox:focus, QLineEdit:focus {{ border-color: {t['accent']}; }}
    QLineEdit:disabled, QComboBox:disabled {{ color: {t['faint']}; }}
    QComboBox::drop-down {{ border: none; width: 26px; }}
    QComboBox::down-arrow {{ image: url("{arrow}"); width: 12px; height: 8px; margin-right: 10px; }}
    QComboBox QAbstractItemView {{
        background: {t['surface2']}; border: 1px solid {t['accent']}; padding: 2px; outline: none;
        selection-background-color: {t['accent']}; selection-color: white;
    }}

    QSlider::groove:horizontal {{ height: 3px; background: {t['surface3']}; }}
    QSlider::sub-page:horizontal {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {t['accent2']}, stop:1 {t['accent']});
    }}
    QSlider::handle:horizontal {{
        background: {t['text']}; width: 10px; height: 18px; margin: -8px 0;
        border: 2px solid {t['accent']};
    }}
    QSlider::handle:horizontal:hover {{ background: {t['accent']}; }}

    QMessageBox {{ background: {t['surface']}; }}
    QMessageBox QPushButton {{
        background: {t['surface3']}; border: 1px solid {t['border']};
        padding: 7px 18px; min-width: 70px;
    }}
    QMessageBox QPushButton:hover {{ background: {t['accent']}; color: white; border-color: {t['accent']}; }}
    """
