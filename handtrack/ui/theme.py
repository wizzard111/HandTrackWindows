"""Colour tokens, fonts, icon glyphs and the application stylesheet."""

from PySide6.QtGui import QColor, QFont, QFontDatabase

DARK = {
    "bg": "#0d0e12",
    "sidebar": "#111218",
    "surface": "#16181f",
    "surface2": "#1e2029",
    "surface3": "#262935",
    "border": "#2a2d3a",
    "text": "#eceef4",
    "muted": "#8b91a3",
    "faint": "#5b6072",
    "accent": "#8b6cff",
    "accent2": "#22d3ee",
    "accent_text": "#ffffff",
    "success": "#34d399",
    "danger": "#fb5c7c",
    "warning": "#fbbf24",
    "shadow": "#000000",
}

LIGHT = {
    "bg": "#f3f4f8",
    "sidebar": "#ebecf2",
    "surface": "#ffffff",
    "surface2": "#f1f2f7",
    "surface3": "#e5e7ef",
    "border": "#dfe2ea",
    "text": "#14161c",
    "muted": "#646a7c",
    "faint": "#9aa0b0",
    "accent": "#6c47ff",
    "accent2": "#0ea5c6",
    "accent_text": "#ffffff",
    "success": "#10b981",
    "danger": "#e11d48",
    "warning": "#d97706",
    "shadow": "#8088a0",
}

ICONS = {
    "camera": "", "effects": "", "gestures": "",
    "calibration": "", "settings": "", "play": "",
    "stop": "", "screenshot": "", "moon": "", "sun": "",
    "folder": "", "refresh": "", "delete": "", "add": "",
    "eye": "", "shield": "", "warning": "", "info": "",
    "record": "", "pencil": "", "sliders": "", "photo": "",
    "check": "", "globe": "",
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


def c(name, alpha=None):
    color = QColor(_current[name])
    if alpha is not None:
        color.setAlphaF(alpha)
    return color


def hex_(name):
    return _current[name]


def mix(a, b, t):
    """Linear blend of two QColors."""
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
        round(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


_UI_FAMILY = None
_ICON_FAMILY = None


def ui_family():
    global _UI_FAMILY
    if _UI_FAMILY is None:
        families = set(QFontDatabase.families())
        for name in ("Segoe UI Variable Text", "Segoe UI", "Inter", "Ubuntu", "Cantarell"):
            if name in families:
                _UI_FAMILY = name
                break
        else:
            _UI_FAMILY = QFont().defaultFamily()
    return _UI_FAMILY


def icon_family():
    global _ICON_FAMILY
    if _ICON_FAMILY is None:
        families = set(QFontDatabase.families())
        _ICON_FAMILY = next((n for n in ("Segoe Fluent Icons", "Segoe MDL2 Assets")
                             if n in families), "")
    return _ICON_FAMILY


def font(size=10, weight=QFont.Weight.Normal):
    f = QFont(ui_family())
    f.setPointSizeF(size)
    f.setWeight(weight)
    return f


def icon_font(size=12):
    f = QFont(icon_family())
    f.setPointSizeF(size)
    return f


def stylesheet():
    t = _current
    return f"""
    QWidget {{
        color: {t['text']};
        font-family: "{ui_family()}";
        font-size: 10pt;
    }}
    QMainWindow, #Root {{ background: {t['bg']}; }}
    QToolTip {{
        background: {t['surface3']}; color: {t['text']};
        border: 1px solid {t['border']}; padding: 6px 8px; border-radius: 6px;
    }}
    QLabel {{ background: transparent; }}
    QLabel[role="title"] {{ font-size: 20pt; font-weight: 650; }}
    QLabel[role="subtitle"] {{ color: {t['muted']}; font-size: 10pt; }}
    QLabel[role="section"] {{ font-size: 11.5pt; font-weight: 600; }}
    QLabel[role="muted"] {{ color: {t['muted']}; }}
    QLabel[role="faint"] {{ color: {t['faint']}; font-size: 9pt; }}
    QLabel[role="mono"] {{ font-family: "Cascadia Mono", Consolas, monospace; color: {t['muted']}; }}

    QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px; }}
    QScrollBar::handle:vertical {{
        background: {t['surface3']}; border-radius: 3px; min-height: 40px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {t['faint']}; }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
        height: 0; background: none;
    }}

    QComboBox, QLineEdit {{
        background: {t['surface2']}; border: 1px solid {t['border']};
        border-radius: 9px; padding: 7px 11px; min-height: 20px;
        selection-background-color: {t['accent']};
    }}
    QComboBox:hover, QLineEdit:hover {{ border-color: {t['faint']}; }}
    QComboBox:focus, QLineEdit:focus {{ border-color: {t['accent']}; }}
    QLineEdit:disabled, QComboBox:disabled {{ color: {t['faint']}; }}
    QComboBox::drop-down {{ border: none; width: 26px; }}
    QComboBox::down-arrow {{ image: none; }}
    QComboBox QAbstractItemView {{
        background: {t['surface2']}; border: 1px solid {t['border']};
        border-radius: 9px; padding: 4px; outline: none;
        selection-background-color: {t['surface3']}; selection-color: {t['text']};
    }}

    QSlider::groove:horizontal {{ height: 4px; background: {t['surface3']}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {t['accent']}, stop:1 {t['accent2']});
        border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        background: #ffffff; width: 16px; height: 16px; margin: -6px 0;
        border-radius: 8px; border: 2px solid {t['accent']};
    }}
    QSlider::handle:horizontal:hover {{ border-width: 3px; }}

    QMessageBox {{ background: {t['surface']}; }}
    QMessageBox QPushButton {{
        background: {t['surface3']}; border: none; border-radius: 8px;
        padding: 7px 18px; min-width: 70px;
    }}
    QMessageBox QPushButton:hover {{ background: {t['accent']}; color: white; }}
    """
