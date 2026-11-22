"""Custom-painted widgets shared by all pages.

Utilitarian look: square corners, 1 px rules, monospace labels, numbered
panels, state shown as text (ON / OFF, tags) rather than decoration.
"""

from PySide6.QtCore import (
    QEasingCurve, QParallelAnimationGroup, QPoint, QPointF, QPropertyAnimation, QRectF, QSize,
    Qt, QTimer, QVariantAnimation, Property, Signal,
)
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QSizePolicy, QSlider,
    QStackedWidget, QVBoxLayout, QWidget,
)

from handtrack.ui import theme

EASE = QEasingCurve.Type.OutCubic


def label(text="", role=None, wrap=False):
    lbl = QLabel(text)
    if role:
        lbl.setProperty("role", role)
    lbl.setWordWrap(wrap)
    return lbl


def heading(text, size=20, spacing=1.0):
    lbl = QLabel(text)
    f = theme.display_font(size, spacing)
    lbl.setFont(f)
    # The app stylesheet sets family/size on every widget; restate them here
    # (caps and letter spacing are not stylesheet properties and survive).
    lbl.setStyleSheet(f"font-family: '{f.family()}'; font-size: {size}pt; font-weight: 700;")
    return lbl


def tag_label(text, color="muted", size=8):
    """Small monospace caption, e.g. a section code."""
    lbl = QLabel(text)
    lbl.setFont(theme.mono(size, False, 0.8))
    lbl.setStyleSheet(f"font-family: '{theme.mono_family()}'; font-size: {size}pt; "
                      f"color: {theme.hex_(color)};")
    return lbl


def _animator(widget, attr, duration=140, curve=EASE):
    anim = QVariantAnimation(widget)
    anim.setDuration(duration)
    anim.setEasingCurve(curve)
    anim.valueChanged.connect(lambda v: (setattr(widget, attr, float(v)), widget.update()))
    return anim


def _animate(anim, start, end):
    anim.stop()
    anim.setStartValue(start)
    anim.setEndValue(end)
    anim.start()


class Icon(QLabel):
    def __init__(self, name, size=16, color="muted"):
        super().__init__()
        self._name, self._size, self._color = name, size, color
        self.setFixedSize(size + 4, size + 4)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.refresh()

    def set_color(self, color):
        self._color = color
        self.refresh()

    def refresh(self):
        self.setPixmap(theme.icon_pixmap(self._name, self._color, self._size,
                                         max(2.0, self.devicePixelRatioF())))


# ------------------------------------------------------------------ toggle ----
class Toggle(QAbstractButton):
    """Two-cell switch labelled OFF / ON; the active cell fills."""

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(64, 22)
        self._pos = 1.0 if checked else 0.0
        self._hover = 0.0
        self._font = theme.mono(7.5, True, 0.5)
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(120)
        self._anim.setEasingCurve(EASE)
        self._hover_anim = _animator(self, "_hover")
        self.toggled.connect(lambda on: _animate(self._anim, self._pos, 1.0 if on else 0.0))

    def _get_knob(self):
        return self._pos

    def _set_knob(self, value):
        self._pos = value
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def set_silent(self, checked):
        self.blockSignals(True)
        self.setChecked(checked)
        self._pos = 1.0 if checked else 0.0
        self.blockSignals(False)
        self.update()

    def enterEvent(self, event):
        _animate(self._hover_anim, self._hover, 1.0)

    def leaveEvent(self, event):
        _animate(self._hover_anim, self._hover, 0.0)

    def sizeHint(self):
        return QSize(64, 22)

    def paintEvent(self, event):
        p = QPainter(self)
        if not self.isEnabled():
            p.setOpacity(0.4)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        half = rect.width() / 2
        p.setPen(QPen(theme.mix(theme.c("border"), theme.c("faint"), self._hover), 1))
        p.setBrush(theme.c("surface2"))
        p.drawRect(rect)
        # Sliding fill block.
        x = rect.left() + half * self._pos
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.mix(theme.c("surface3"), theme.c("accent"), self._pos))
        p.drawRect(QRectF(x + 2, rect.top() + 2, half - 4, rect.height() - 4))
        p.setFont(self._font)
        on = self._pos > 0.5
        p.setPen(theme.c("faint") if on else theme.c("text"))
        p.drawText(QRectF(rect.left(), rect.top(), half, rect.height()), Qt.AlignmentFlag.AlignCenter, "OFF")
        p.setPen(theme.c("accent_text") if on else theme.c("faint"))
        p.drawText(QRectF(rect.left() + half, rect.top(), half, rect.height()),
                   Qt.AlignmentFlag.AlignCenter, "ON")


# ------------------------------------------------------------------ button ----
class Button(QAbstractButton):
    """Square button with an icon and monospace caption.

    kind: primary (solid red), secondary (outlined), ghost (text only), danger.
    """

    def __init__(self, text="", icon=None, kind="secondary", parent=None):
        super().__init__(parent)
        self.setText(text)
        self._icon = icon
        self.kind = kind
        self._hover = 0.0
        self._press = 0.0
        self._hover_anim = _animator(self, "_hover")
        self._press_anim = _animator(self, "_press", 90)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._font = theme.mono(9, True, 0.8)

    def set_icon(self, name):
        self._icon = name
        self.updateGeometry()
        self.update()

    def set_kind(self, kind):
        self.kind = kind
        self.update()

    def sizeHint(self):
        w = QFontMetrics(self._font).horizontalAdvance(self.text().upper()) + 30
        if self._icon:
            w += 22 if self.text() else 6
        return QSize(max(w, 36), 34)

    def enterEvent(self, event):
        _animate(self._hover_anim, self._hover, 1.0)

    def leaveEvent(self, event):
        _animate(self._hover_anim, self._hover, 0.0)

    def mousePressEvent(self, event):
        _animate(self._press_anim, self._press, 1.0)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        _animate(self._press_anim, self._press, 0.0)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        if not self.isEnabled():
            p.setOpacity(0.4)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        h = self._hover
        black = QColor("black")
        if self.kind in ("primary", "danger"):
            base = theme.c("danger" if self.kind == "danger" else "accent")
            p.setBrush(theme.mix(base, black, 0.18 * self._press + 0.0 * h))
            p.setPen(QPen(theme.mix(base, QColor("white"), 0.25 * h), 1))
            fg = theme.c("accent_text")
        elif self.kind == "ghost":
            p.setBrush(theme.c("surface3", 0.8 * h))
            p.setPen(Qt.PenStyle.NoPen)
            fg = theme.mix(theme.c("muted"), theme.c("text"), h)
        else:
            p.setBrush(theme.mix(theme.c("surface2"), theme.c("surface3"), h))
            p.setPen(QPen(theme.mix(theme.c("border"), theme.c("text"), 0.5 * h), 1))
            fg = theme.c("text")
        p.drawRect(rect)

        text = self.text().upper()
        fm = QFontMetrics(self._font)
        icon_w = 15 if self._icon else 0
        gap = 8 if (self._icon and text) else 0
        total = icon_w + gap + fm.horizontalAdvance(text)
        x = rect.center().x() - total / 2
        if self._icon:
            theme.draw_icon(p, self._icon, QRectF(x, rect.center().y() - 7.5, 15, 15), fg)
        if text:
            p.setPen(fg)
            p.setFont(self._font)
            p.drawText(QRectF(x + icon_w + gap, rect.top(), total + 4, rect.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)


# -------------------------------------------------------------------- card ----
class Card(QFrame):
    """Panel: 1 px frame, header strip with a red marker, title, optional
    section code on the right, and a rule under the header."""

    def __init__(self, title=None, icon=None, parent=None, spacing=12, code=None):
        super().__init__(parent)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(16, 12, 16, 16)
        self.body.setSpacing(spacing)
        self.header = None
        self._has_header = bool(title)
        if title:
            self.header = QHBoxLayout()
            self.header.setSpacing(8)
            if icon:
                self.header.addWidget(Icon(icon, 14, "muted"))
            self.title_label = heading(title, 9.5, 1.2)
            self.header.addWidget(self.title_label)
            self.header.addStretch(1)
            self.code_label = tag_label(code or "", "faint")
            self.header.addWidget(self.code_label)
            self.body.addLayout(self.header)
            self.body.addSpacing(4)

    def set_code(self, code):
        if self._has_header:
            self.code_label.setText(code)

    def paintEvent(self, event):
        p = QPainter(self)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(theme.c("surface"))
        p.setPen(QPen(theme.c("border"), 1))
        p.drawRect(rect)
        if self._has_header:
            y = self.header.geometry().bottom() + 8.5
            p.setPen(QPen(theme.c("border"), 1))
            p.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            # Red marker on the header edge.
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.c("accent"))
            p.drawRect(QRectF(rect.left(), rect.top(), 3, y - rect.top()))


# ------------------------------------------------------------- setting row ----
class SettingRow(QWidget):
    toggled = Signal(bool)

    def __init__(self, title, description=None, checked=False, icon=None):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 2, 0, 2)
        row.setSpacing(12)
        if icon:
            row.addWidget(Icon(icon, 14, "muted"), 0, Qt.AlignmentFlag.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        self.title = label(title, wrap=True)
        texts.addWidget(self.title)
        if description:
            self.desc = label(description, "faint", wrap=True)
            texts.addWidget(self.desc)
        row.addLayout(texts, 1)
        self.toggle = Toggle(checked)
        self.toggle.toggled.connect(self.toggled)
        row.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignVCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.toggle.isEnabled():
            self.toggle.toggle()


class SliderRow(QWidget):
    valueChanged = Signal(float)

    def __init__(self, title, minimum, maximum, value, step=0.05, fmt=None):
        super().__init__()
        self._min, self._step = minimum, step
        self._fmt = fmt or (lambda v: f"{v:.2f}")
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 2, 0, 2)
        col.setSpacing(6)
        top = QHBoxLayout()
        top.addWidget(label(title))
        top.addStretch(1)
        self.value_label = label("", "mono")
        top.addWidget(self.value_label)
        col.addLayout(top)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, round((maximum - minimum) / step))
        self.slider.setValue(round((value - minimum) / step))
        self.slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.slider.valueChanged.connect(self._changed)
        col.addWidget(self.slider)
        self._update_label()

    def value(self):
        return self._min + self.slider.value() * self._step

    def _changed(self, _):
        self._update_label()
        self.valueChanged.emit(self.value())

    def _update_label(self):
        self.value_label.setText(f"[ {self._fmt(self.value())} ]")


# -------------------------------------------------------------------- pill ----
class Pill(QWidget):
    """Status tag: a square indicator (blinks while active) and mono text."""

    def __init__(self, text="", color="muted", pulse=False):
        super().__init__()
        self._text, self._color, self._blink = text, color, True
        self._font = theme.mono(7.5, True, 0.8)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.set_state(text, color, pulse)

    def set_state(self, text, color="muted", pulse=False):
        self._text, self._color = text, color
        if pulse and not self._timer.isActive():
            self._timer.start(600)
        elif not pulse:
            self._timer.stop()
            self._blink = True
        self.updateGeometry()
        self.update()

    def _tick(self):
        self._blink = not self._blink
        self.update()

    def sizeHint(self):
        return QSize(QFontMetrics(self._font).horizontalAdvance(self._text.upper()) + 28, 20)

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, event):
        p = QPainter(self)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        color = theme.c(self._color)
        p.setPen(QPen(theme.c(self._color, 0.6), 1))
        p.setBrush(theme.c(self._color, 0.08))
        p.drawRect(rect)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color if self._blink else theme.c(self._color, 0.25))
        p.drawRect(QRectF(7, rect.center().y() - 3, 6, 6))
        p.setPen(color)
        p.setFont(self._font)
        p.drawText(QRectF(19, 0, rect.width() - 22, rect.height()),
                   Qt.AlignmentFlag.AlignVCenter, self._text.upper())


# ----------------------------------------------------------------- sidebar ----
class NavButton(QAbstractButton):
    def __init__(self, text, icon, index):
        super().__init__()
        self.setText(text)
        self._icon = icon
        self._index = f"{index:02d}"
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(40)
        self._hover = 0.0
        self._hover_anim = _animator(self, "_hover")
        self._font = theme.mono(9, True, 1.0)
        self._num_font = theme.mono(8, False, 0.4)

    def enterEvent(self, event):
        _animate(self._hover_anim, self._hover, 1.0)

    def leaveEvent(self, event):
        _animate(self._hover_anim, self._hover, 0.0)

    def paintEvent(self, event):
        p = QPainter(self)
        rect = QRectF(self.rect())
        active = self.isChecked()
        if not active and self._hover > 0:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.c("surface2", self._hover))
            p.drawRect(rect)
        fg = theme.c("text") if active else theme.mix(theme.c("muted"), theme.c("text"), self._hover)
        p.setFont(self._num_font)
        p.setPen(theme.c("accent") if active else theme.c("faint"))
        p.drawText(QRectF(12, 0, 22, rect.height()), Qt.AlignmentFlag.AlignVCenter, self._index)
        theme.draw_icon(p, self._icon, QRectF(38, rect.center().y() - 8, 16, 16), fg)
        p.setPen(fg)
        p.setFont(self._font)
        p.drawText(QRectF(64, 0, rect.width() - 68, rect.height()),
                   Qt.AlignmentFlag.AlignVCenter, self.text().upper())


class NavIndicator(QWidget):
    """Highlight behind the active nav item; slides between items."""

    def paintEvent(self, event):
        p = QPainter(self)
        rect = QRectF(self.rect())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.c("surface3"))
        p.drawRect(rect)
        p.setBrush(theme.c("accent"))
        p.drawRect(QRectF(0, 0, 3, rect.height()))


class NavList(QWidget):
    currentChanged = Signal(int)

    def __init__(self):
        super().__init__()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)
        self._buttons = []
        self._current = -1
        self._indicator = NavIndicator(self)
        self._indicator.lower()
        self._anim = QPropertyAnimation(self._indicator, b"geometry", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(EASE)

    def add(self, text, icon):
        index = len(self._buttons)
        btn = NavButton(text, icon, index + 1)
        btn.clicked.connect(lambda: self.set_current(index))
        self._buttons.append(btn)
        self._layout.addWidget(btn)
        return btn

    def set_current(self, index, animate=True):
        if index == self._current:
            self._buttons[index].setChecked(True)
            return
        self._current = index
        for i, b in enumerate(self._buttons):
            b.setChecked(i == index)
        target = self._buttons[index].geometry()
        if animate and self._indicator.isVisible() and target.isValid() and target.height() > 0:
            _animate(self._anim, self._indicator.geometry(), target)
        else:
            self._indicator.setGeometry(target)
        self.currentChanged.emit(index)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._current >= 0 and self._anim.state() != QPropertyAnimation.State.Running:
            self._indicator.setGeometry(self._buttons[self._current].geometry())

    def showEvent(self, event):
        super().showEvent(event)
        if self._current >= 0:
            QTimer.singleShot(0, lambda: self._indicator.setGeometry(
                self._buttons[self._current].geometry()))


# -------------------------------------------------------------- page stack ----
class FadeStack(QStackedWidget):
    """Pages fade and slide in a little when switched."""

    def __init__(self):
        super().__init__()
        self._group = None

    def set_index_animated(self, index):
        if index == self.currentIndex():
            return
        forward = index > self.currentIndex()
        page = self.widget(index)
        self.setCurrentIndex(index)
        effect = QGraphicsOpacityEffect(page)
        page.setGraphicsEffect(effect)
        fade = QPropertyAnimation(effect, b"opacity", page)
        fade.setDuration(160)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        end = page.pos()
        slide = QPropertyAnimation(page, b"pos", page)
        slide.setDuration(200)
        slide.setStartValue(end + QPoint(14 if forward else -14, 0))
        slide.setEndValue(end)
        slide.setEasingCurve(EASE)
        if self._group is not None:
            self._group.stop()
        group = QParallelAnimationGroup(self)
        group.addAnimation(fade)
        group.addAnimation(slide)
        # Drop the effect afterwards: it would force software rendering of the live preview.
        group.finished.connect(lambda: page.setGraphicsEffect(None))
        self._group = group
        group.start()


# ------------------------------------------------------------------- toast ----
class Toast(QWidget):
    """Notification bar that slides up from the bottom of its parent."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._text = ""
        self._kind = "accent"
        self._icon = "info"
        self._opacity = 0.0
        self._font = theme.mono(9, False, 0.3, upper=False)
        self.hide()
        self._anim = _animator(self, "_opacity", 180)
        self._anim.valueChanged.connect(lambda _v: self._place())
        self._anim.finished.connect(lambda: self.hide() if self._opacity <= 0.01 else None)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(lambda: _animate(self._anim, self._opacity, 0.0))

    def show_message(self, text, kind="accent", icon="info", msec=2600):
        self._text, self._kind, self._icon = text, kind, icon
        w = min(QFontMetrics(self._font).horizontalAdvance(text) + 66, self.parent().width() - 40)
        self.resize(w, 40)
        self.raise_()
        self.show()
        _animate(self._anim, self._opacity, 1.0)
        self._hide_timer.start(msec)

    def _place(self):
        parent = self.parent()
        self.move((parent.width() - self.width()) // 2,
                  parent.height() - self.height() - 20 + int((1 - self._opacity) * 16))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setOpacity(self._opacity)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(theme.c("border"), 1))
        p.setBrush(theme.c("surface2"))
        p.drawRect(rect)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.c(self._kind))
        p.drawRect(QRectF(rect.left(), rect.top(), 3, rect.height()))
        theme.draw_icon(p, self._icon, QRectF(14, rect.center().y() - 8, 16, 16), theme.c(self._kind))
        p.setPen(theme.c("text"))
        p.setFont(self._font)
        p.drawText(QRectF(40, 0, rect.width() - 48, rect.height()),
                   Qt.AlignmentFlag.AlignVCenter, self._text)


# ---------------------------------------------------------- segmented ctrl ----
class Segmented(QWidget):
    changed = Signal(int)

    def __init__(self, options, index=0):
        super().__init__()
        self._options = list(options)
        self._index = index
        self._pos = float(index)
        self.setFixedHeight(30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._font = theme.mono(8.5, True, 0.8)
        self._anim = _animator(self, "_pos", 160)

    def set_index(self, index):
        self._index = index
        _animate(self._anim, self._pos, float(index))

    def sizeHint(self):
        w = max(QFontMetrics(self._font).horizontalAdvance(o.upper()) for o in self._options) + 28
        return QSize(w * len(self._options) + 4, 30)

    def mouseReleaseEvent(self, event):
        seg = (self.width() - 4) / len(self._options)
        index = int(max(0, min(len(self._options) - 1, (event.position().x() - 2) // seg)))
        if index != self._index:
            self.set_index(index)
            self.changed.emit(index)

    def paintEvent(self, event):
        p = QPainter(self)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(theme.c("border"), 1))
        p.setBrush(theme.c("surface2"))
        p.drawRect(rect)
        seg = (rect.width() - 4) / len(self._options)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.c("accent"))
        p.drawRect(QRectF(2 + seg * self._pos, 2, seg, rect.height() - 4))
        p.setFont(self._font)
        for i, text in enumerate(self._options):
            closeness = max(0.0, 1 - abs(self._pos - i))
            p.setPen(theme.mix(theme.c("muted"), theme.c("accent_text"), closeness))
            p.drawText(QRectF(2 + seg * i, 0, seg, rect.height()), Qt.AlignmentFlag.AlignCenter,
                       text.upper())


class Swatches(QWidget):
    """Row of colour squares; the selected one is framed."""

    changed = Signal(int)

    def __init__(self, colors, index=0):
        super().__init__()
        self.colors = [QColor(c) for c in colors]
        self.index = index
        self.setFixedHeight(26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self):
        return QSize(len(self.colors) * 30, 26)

    def mouseReleaseEvent(self, event):
        i = int(event.position().x() // 30)
        if 0 <= i < len(self.colors) and i != self.index:
            self.index = i
            self.update()
            self.changed.emit(i)

    def paintEvent(self, event):
        p = QPainter(self)
        for i, color in enumerate(self.colors):
            r = QRectF(i * 30 + 3.5, 3.5, 19, 19)
            p.setPen(QPen(theme.c("text") if i == self.index else theme.c("border"),
                          2 if i == self.index else 1))
            p.setBrush(color)
            p.drawRect(r)


def hline():
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {theme.hex_('border')};")
    return line
