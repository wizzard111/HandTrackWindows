"""Custom-painted, animated widgets shared by all pages."""

from PySide6.QtCore import (
    QEasingCurve, QParallelAnimationGroup, QPoint, QPointF, QPropertyAnimation, QRectF, QSize,
    Qt, QTimer, QVariantAnimation, Property, Signal,
)
from PySide6.QtGui import QFontMetrics, QColor, QFont, QLinearGradient, QPainter, QPen
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


def heading(text, size=20, spacing=2.0):
    lbl = QLabel(text)
    f = theme.display_font(size, spacing)
    lbl.setFont(f)
    # The app stylesheet sets family/size on every widget; restate them here
    # (caps and letter spacing are not stylesheet properties and survive).
    lbl.setStyleSheet(f"font-family: '{f.family()}'; font-size: {size}pt;")
    return lbl


def _animator(widget, attr, duration=160, curve=EASE):
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
    """Squared switch: a block slides across and the track floods red."""

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(46, 22)
        self._pos = 1.0 if checked else 0.0
        self._hover = 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(200)
        self._anim.setEasingCurve(QEasingCurve.Type.OutQuint)
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
        return QSize(46, 22)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.4)
        t = max(0.0, min(1.0, self._pos))
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        off = theme.mix(theme.c("surface3"), theme.c("faint"), self._hover * 0.4)
        track = theme.chamfer_path(rect, 5, "tl,br")
        p.setPen(QPen(theme.mix(theme.c("border"), theme.c("accent"), t), 1))
        if t > 0:
            grad = QLinearGradient(rect.topLeft(), rect.topRight())
            grad.setColorAt(0, theme.mix(off, theme.c("accent2"), t))
            grad.setColorAt(1, theme.mix(off, theme.c("accent"), t))
            p.setBrush(grad)
        else:
            p.setBrush(off)
        p.drawPath(track)
        knob_w = rect.height() - 6
        x = rect.left() + 3 + (rect.width() - knob_w - 6) * self._pos
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ffffff") if t > 0.5 else theme.c("muted"))
        p.drawRect(QRectF(x, rect.top() + 3, knob_w, knob_w))


# ------------------------------------------------------------------ button ----
class Button(QAbstractButton):
    """Chamfered button with an icon and animated hover/press.

    kind: primary (purple→red), secondary, ghost, danger.
    """

    def __init__(self, text="", icon=None, kind="secondary", parent=None):
        super().__init__(parent)
        self.setText(text)
        self._icon = icon
        self.kind = kind
        self._hover = 0.0
        self._press = 0.0
        self._hover_anim = _animator(self, "_hover")
        self._press_anim = _animator(self, "_press", 110)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._font = theme.display_font(9.5, 1.2)

    def set_icon(self, name):
        self._icon = name
        self.updateGeometry()
        self.update()

    def set_kind(self, kind):
        self.kind = kind
        self.update()

    def sizeHint(self):
        w = QFontMetrics(self._font).horizontalAdvance(self.text().upper()) + 34
        if self._icon:
            w += 24 if self.text() else 6
        return QSize(max(w, 40), 38)

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
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.4)
        shrink = self._press * 1.5
        rect = QRectF(self.rect()).adjusted(0.5 + shrink, 0.5 + shrink, -0.5 - shrink, -0.5 - shrink)
        path = theme.chamfer_path(rect, 8)
        h = self._hover
        white = QColor("white")
        if self.kind == "primary":
            grad = QLinearGradient(rect.topLeft(), rect.topRight())
            grad.setColorAt(0, theme.mix(theme.c("accent2"), theme.c("accent"), 0.15 + 0.35 * h))
            grad.setColorAt(1, theme.mix(theme.c("accent"), white, 0.12 * h))
            p.setBrush(grad)
            p.setPen(Qt.PenStyle.NoPen)
            fg = theme.c("accent_text")
        elif self.kind == "danger":
            p.setBrush(theme.mix(theme.c("accent"), white, 0.14 * h))
            p.setPen(Qt.PenStyle.NoPen)
            fg = white
        elif self.kind == "ghost":
            p.setBrush(theme.c("surface3", 0.9 * h))
            p.setPen(QPen(theme.c("accent", 0.8 * h), 1))
            fg = theme.mix(theme.c("muted"), theme.c("text"), h)
        else:
            p.setBrush(theme.mix(theme.c("surface3"), theme.c("surface2"), 0.4 * h))
            p.setPen(QPen(theme.mix(theme.c("border"), theme.c("accent"), h), 1))
            fg = theme.c("text")
        p.drawPath(path)

        text = self.text().upper()
        fm = QFontMetrics(self._font)
        icon_w = 16 if self._icon else 0
        gap = 9 if (self._icon and text) else 0
        total = icon_w + gap + fm.horizontalAdvance(text)
        x = rect.center().x() - total / 2
        if self._icon:
            theme.draw_icon(p, self._icon, QRectF(x, rect.center().y() - 8, 16, 16), fg)
        if text:
            p.setPen(fg)
            p.setFont(self._font)
            p.drawText(QRectF(x + icon_w + gap, rect.top(), total + 4, rect.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)


# -------------------------------------------------------------------- card ----
class Card(QFrame):
    """Surface panel with chamfered corners and a red tick on the title."""

    def __init__(self, title=None, icon=None, parent=None, spacing=12):
        super().__init__(parent)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(20, 16, 20, 18)
        self.body.setSpacing(spacing)
        self.header = None
        if title:
            self.header = QHBoxLayout()
            self.header.setSpacing(10)
            if icon:
                self.header.addWidget(Icon(icon, 16, "accent"))
            self.title_label = heading(title, 10.5, 1.6)
            self.header.addWidget(self.title_label)
            self.header.addStretch(1)
            self.body.addLayout(self.header)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(theme.c("surface"))
        p.setPen(QPen(theme.c("border"), 1))
        p.drawPath(theme.chamfer_path(rect, 14))
        # Accent bracket on the cut corner.
        p.setPen(QPen(theme.c("accent"), 2))
        p.drawLine(QPointF(rect.left() + 1, rect.top() + 14), QPointF(rect.left() + 14, rect.top() + 1))
        p.drawLine(QPointF(rect.left() + 14, rect.top() + 1), QPointF(rect.left() + 40, rect.top() + 1))


# ------------------------------------------------------------- setting row ----
class SettingRow(QWidget):
    toggled = Signal(bool)

    def __init__(self, title, description=None, checked=False, icon=None):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 2, 0, 2)
        row.setSpacing(12)
        if icon:
            row.addWidget(Icon(icon, 15, "muted"), 0, Qt.AlignmentFlag.AlignTop)
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
        self.value_label.setText(self._fmt(self.value()))


# -------------------------------------------------------------------- pill ----
class Pill(QWidget):
    """Angular status tag: a square marker (optionally pulsing) and text."""

    def __init__(self, text="", color="muted", pulse=False):
        super().__init__()
        self._text, self._color, self._phase = text, color, 0.0
        self._font = theme.display_font(8, 1.2)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.set_state(text, color, pulse)

    def set_state(self, text, color="muted", pulse=False):
        self._text, self._color = text, color
        if pulse and not self._timer.isActive():
            self._timer.start(40)
        elif not pulse:
            self._timer.stop()
            self._phase = 0.0
        self.updateGeometry()
        self.update()

    def _tick(self):
        self._phase = (self._phase + 0.05) % 1.0
        self.update()

    def sizeHint(self):
        return QSize(QFontMetrics(self._font).horizontalAdvance(self._text.upper()) + 34, 24)

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        color = theme.c(self._color)
        p.setPen(QPen(theme.c(self._color, 0.45), 1))
        p.setBrush(theme.c(self._color, 0.10))
        p.drawPath(theme.chamfer_path(rect, 6, "tl,br"))
        cy = rect.center().y()
        if self._timer.isActive():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.c(self._color, 0.5 * (1 - self._phase)))
            r = 3 + 5 * self._phase
            p.drawRect(QRectF(13 - r, cy - r, 2 * r, 2 * r))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawRect(QRectF(10, cy - 3, 6, 6))
        p.setPen(color)
        p.setFont(self._font)
        p.drawText(QRectF(23, 0, rect.width() - 26, rect.height()),
                   Qt.AlignmentFlag.AlignVCenter, self._text.upper())


# ----------------------------------------------------------------- sidebar ----
class NavButton(QAbstractButton):
    def __init__(self, text, icon):
        super().__init__()
        self.setText(text)
        self._icon = icon
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(44)
        self._hover = 0.0
        self._hover_anim = _animator(self, "_hover")
        self._font = theme.display_font(9.5, 1.6)

    def enterEvent(self, event):
        _animate(self._hover_anim, self._hover, 1.0)

    def leaveEvent(self, event):
        _animate(self._hover_anim, self._hover, 0.0)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        active = self.isChecked()
        if not active and self._hover > 0:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.c("surface2", self._hover))
            p.drawPath(theme.chamfer_path(rect, 8))
        fg = theme.c("text") if active else theme.mix(theme.c("muted"), theme.c("text"), self._hover)
        theme.draw_icon(p, self._icon, QRectF(16, rect.center().y() - 9, 18, 18),
                        theme.c("accent") if active else fg)
        p.setPen(fg)
        p.setFont(self._font)
        p.drawText(QRectF(48, 0, rect.width() - 52, rect.height()),
                   Qt.AlignmentFlag.AlignVCenter, self.text().upper())


class NavIndicator(QWidget):
    """Highlight behind the active nav item; slides between items."""

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        grad = QLinearGradient(rect.topLeft(), rect.topRight())
        grad.setColorAt(0, theme.c("accent", 0.28))
        grad.setColorAt(1, theme.c("accent2", 0.05))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawPath(theme.chamfer_path(rect, 8))
        p.setBrush(theme.c("accent"))
        p.drawRect(QRectF(0, 6, 3, rect.height() - 12))


class NavList(QWidget):
    currentChanged = Signal(int)

    def __init__(self):
        super().__init__()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)
        self._buttons = []
        self._current = -1
        self._indicator = NavIndicator(self)
        self._indicator.lower()
        self._anim = QPropertyAnimation(self._indicator, b"geometry", self)
        self._anim.setDuration(300)
        self._anim.setEasingCurve(QEasingCurve.Type.OutQuint)

    def add(self, text, icon):
        btn = NavButton(text, icon)
        index = len(self._buttons)
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
    """Pages fade and slide sideways in when switched."""

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
        fade.setDuration(220)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        end = page.pos()
        slide = QPropertyAnimation(page, b"pos", page)
        slide.setDuration(280)
        slide.setStartValue(end + QPoint(28 if forward else -28, 0))
        slide.setEndValue(end)
        slide.setEasingCurve(QEasingCurve.Type.OutQuint)
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
    """Notification that slides up from the bottom of its parent."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._text = ""
        self._kind = "accent"
        self._icon = "info"
        self._opacity = 0.0
        self._font = theme.font(10, QFont.Weight.DemiBold)
        self.hide()
        self._anim = _animator(self, "_opacity", 240)
        self._anim.valueChanged.connect(lambda _v: self._place())
        self._anim.finished.connect(lambda: self.hide() if self._opacity <= 0.01 else None)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(lambda: _animate(self._anim, self._opacity, 0.0))

    def show_message(self, text, kind="accent", icon="info", msec=2600):
        self._text, self._kind, self._icon = text, kind, icon
        w = min(QFontMetrics(self._font).horizontalAdvance(text) + 76, self.parent().width() - 40)
        self.resize(w, 46)
        self.raise_()
        self.show()
        _animate(self._anim, self._opacity, 1.0)
        self._hide_timer.start(msec)

    def _place(self):
        parent = self.parent()
        self.move((parent.width() - self.width()) // 2,
                  parent.height() - self.height() - 24 + int((1 - self._opacity) * 24))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self._opacity)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(theme.c(self._kind), 1))
        p.setBrush(theme.c("surface2"))
        p.drawPath(theme.chamfer_path(rect, 10))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.c(self._kind))
        p.drawRect(QRectF(rect.left(), rect.top() + 10, 3, rect.height() - 20))
        theme.draw_icon(p, self._icon, QRectF(18, rect.center().y() - 9, 18, 18), theme.c(self._kind))
        p.setPen(theme.c("text"))
        p.setFont(self._font)
        p.drawText(QRectF(48, 0, rect.width() - 58, rect.height()),
                   Qt.AlignmentFlag.AlignVCenter, self._text)


# ---------------------------------------------------------- segmented ctrl ----
class Segmented(QWidget):
    changed = Signal(int)

    def __init__(self, options, index=0):
        super().__init__()
        self._options = list(options)
        self._index = index
        self._pos = float(index)
        self.setFixedHeight(34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._font = theme.display_font(9, 1.2)
        self._anim = _animator(self, "_pos", 240, QEasingCurve.Type.OutQuint)

    def set_index(self, index):
        self._index = index
        _animate(self._anim, self._pos, float(index))

    def sizeHint(self):
        w = max(QFontMetrics(self._font).horizontalAdvance(o.upper()) for o in self._options) + 30
        return QSize(w * len(self._options) + 8, 34)

    def mouseReleaseEvent(self, event):
        seg = (self.width() - 8) / len(self._options)
        index = int(max(0, min(len(self._options) - 1, (event.position().x() - 4) // seg)))
        if index != self._index:
            self.set_index(index)
            self.changed.emit(index)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(theme.c("border"), 1))
        p.setBrush(theme.c("surface2"))
        p.drawPath(theme.chamfer_path(rect, 8))
        seg = (rect.width() - 8) / len(self._options)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.c("accent"))
        p.drawPath(theme.chamfer_path(QRectF(4 + seg * self._pos, 4, seg, rect.height() - 8), 6))
        p.setFont(self._font)
        for i, text in enumerate(self._options):
            closeness = max(0.0, 1 - abs(self._pos - i))
            p.setPen(theme.mix(theme.c("muted"), QColor("white"), closeness))
            p.drawText(QRectF(4 + seg * i, 0, seg, rect.height()), Qt.AlignmentFlag.AlignCenter,
                       text.upper())


class Swatches(QWidget):
    """Row of colour squares; the selected one gets a red frame."""

    changed = Signal(int)

    def __init__(self, colors, index=0):
        super().__init__()
        self.colors = [QColor(c) for c in colors]
        self.index = index
        self.setFixedHeight(30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self):
        return QSize(len(self.colors) * 36, 30)

    def mouseReleaseEvent(self, event):
        i = int(event.position().x() // 36)
        if 0 <= i < len(self.colors) and i != self.index:
            self.index = i
            self.update()
            self.changed.emit(i)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for i, color in enumerate(self.colors):
            r = QRectF(i * 36 + 3, 3, 24, 24)
            if i == self.index:
                p.setPen(QPen(theme.c("text"), 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(theme.chamfer_path(r.adjusted(-3, -3, 3, 3), 6))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawPath(theme.chamfer_path(r, 5))


def hline():
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {theme.hex_('border')};")
    return line
