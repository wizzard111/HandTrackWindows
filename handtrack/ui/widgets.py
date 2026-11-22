"""Custom-painted, animated widgets shared by all pages."""

from PySide6.QtCore import (
    QEasingCurve, QParallelAnimationGroup, QPoint, QPointF, QPropertyAnimation,
    QRectF, QSize, Qt, QTimer, QVariantAnimation, Property, Signal,
)
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractButton, QFrame, QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QHBoxLayout,
    QLabel, QSizePolicy, QSlider, QStackedWidget, QVBoxLayout, QWidget,
)

from handtrack.ui import theme

EASE = QEasingCurve.Type.OutCubic


def label(text="", role=None, wrap=False):
    lbl = QLabel(text)
    if role:
        lbl.setProperty("role", role)
    lbl.setWordWrap(wrap)
    return lbl


class Icon(QLabel):
    def __init__(self, name, size=13, color="muted"):
        super().__init__(theme.ICONS.get(name, ""))
        self._color = color
        self._size = size
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.refresh()

    def set_color(self, color):
        self._color = color
        self.refresh()

    def refresh(self):
        # The app stylesheet sets a text font on every QWidget, so the icon
        # font has to be set here too or the glyph falls back to Segoe UI.
        self.setStyleSheet(f"color: {theme.hex_(self._color)}; background: transparent; "
                           f"font-family: '{theme.icon_family()}'; font-size: {self._size}pt;")


def _hover_anim(widget, duration=160):
    anim = QVariantAnimation(widget)
    anim.setDuration(duration)
    anim.setEasingCurve(EASE)
    anim.valueChanged.connect(lambda v: (setattr(widget, "_hover", float(v)), widget.update()))
    return anim


def _animate(anim, start, end):
    anim.stop()
    anim.setStartValue(start)
    anim.setEndValue(end)
    anim.start()


# ------------------------------------------------------------------ toggle ----
class Toggle(QAbstractButton):
    """iOS-style switch with an animated knob and track colour."""

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(44, 24)
        self._pos = 1.0 if checked else 0.0
        self._hover = 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.Type.OutBack)
        self._hover_anim = _hover_anim(self)
        self.toggled.connect(self._on_toggled)

    def _get_knob(self):
        return self._pos

    def _set_knob(self, value):
        self._pos = value
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def set_silent(self, checked):
        """Update the state without emitting toggled and without animating."""
        self.blockSignals(True)
        super().setChecked(checked)
        self._pos = 1.0 if checked else 0.0
        self.blockSignals(False)
        self.update()

    def _on_toggled(self, checked):
        _animate(self._anim, self._pos, 1.0 if checked else 0.0)

    def enterEvent(self, event):
        _animate(self._hover_anim, self._hover, 1.0)

    def leaveEvent(self, event):
        _animate(self._hover_anim, self._hover, 0.0)

    def sizeHint(self):
        return QSize(44, 24)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = max(0.0, min(1.0, self._pos))
        rect = QRectF(1, 1, self.width() - 2, self.height() - 2)
        off = theme.mix(theme.c("surface3"), theme.c("faint"), self._hover * 0.35)
        if t > 0:
            grad = QLinearGradient(rect.topLeft(), rect.topRight())
            grad.setColorAt(0, theme.mix(off, theme.c("accent"), t))
            grad.setColorAt(1, theme.mix(off, theme.c("accent2"), t))
            p.setBrush(grad)
        else:
            p.setBrush(off)
        p.setPen(Qt.PenStyle.NoPen)
        if not self.isEnabled():
            p.setOpacity(0.4)
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        d = rect.height() - 6
        x = rect.left() + 3 + (rect.width() - d - 6) * self._pos
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(x, rect.top() + 3, d, d))


# ------------------------------------------------------------------ button ----
class Button(QAbstractButton):
    """Rounded button with an icon glyph and an animated hover/press state.

    kind: primary (gradient), secondary, ghost, danger.
    """

    def __init__(self, text="", icon=None, kind="secondary", parent=None):
        super().__init__(parent)
        self.setText(text)
        self._icon = theme.ICONS.get(icon, "") if icon else ""
        self.kind = kind
        self._hover = 0.0
        self._press = 0.0
        self._hover_anim = _hover_anim(self)
        self._press_anim = QVariantAnimation(self)
        self._press_anim.setDuration(120)
        self._press_anim.valueChanged.connect(lambda v: (setattr(self, "_press", float(v)), self.update()))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setFont(theme.font(10, QFont.Weight.DemiBold))

    def set_icon(self, name):
        self._icon = theme.ICONS.get(name, "")
        self.updateGeometry()
        self.update()

    def set_kind(self, kind):
        self.kind = kind
        self.update()

    def sizeHint(self):
        fm = self.fontMetrics()
        w = fm.horizontalAdvance(self.text()) + 32
        if self._icon:
            w += 24 if self.text() else 8
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
            p.setOpacity(0.45)
        shrink = self._press * 1.5
        rect = QRectF(self.rect()).adjusted(shrink, shrink, -shrink, -shrink)
        radius = 10
        h = self._hover
        if self.kind == "primary":
            grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
            light = 0.12 * h
            grad.setColorAt(0, theme.mix(theme.c("accent"), QColor("white"), light))
            grad.setColorAt(1, theme.mix(theme.c("accent2"), QColor("white"), light))
            p.setBrush(grad)
            fg = theme.c("accent_text")
        elif self.kind == "danger":
            p.setBrush(theme.mix(theme.c("danger"), QColor("white"), 0.12 * h))
            fg = QColor("white")
        elif self.kind == "ghost":
            p.setBrush(theme.c("surface3", 0.9 * h))
            fg = theme.mix(theme.c("muted"), theme.c("text"), h)
        else:
            p.setBrush(theme.mix(theme.c("surface3"), theme.c("faint"), 0.35 * h))
            fg = theme.c("text")
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, radius, radius)

        p.setPen(fg)
        text = self.text()
        fm = self.fontMetrics()
        icon_w = 18 if self._icon else 0
        gap = 8 if (self._icon and text) else 0
        total = icon_w + gap + fm.horizontalAdvance(text)
        x = rect.center().x() - total / 2
        if self._icon:
            p.setFont(theme.icon_font(11))
            p.drawText(QRectF(x, rect.top(), icon_w, rect.height()),
                       Qt.AlignmentFlag.AlignCenter, self._icon)
        if text:
            p.setFont(self.font())
            p.drawText(QRectF(x + icon_w + gap, rect.top(), total, rect.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)


# -------------------------------------------------------------------- card ----
class Card(QFrame):
    def __init__(self, title=None, icon=None, parent=None, spacing=12):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(18, 16, 18, 18)
        self.body.setSpacing(spacing)
        self.header = None
        if title:
            self.header = QHBoxLayout()
            self.header.setSpacing(10)
            if icon:
                self.header.addWidget(Icon(icon, 13, "accent"))
            self.title_label = label(title, "section")
            self.header.addWidget(self.title_label)
            self.header.addStretch(1)
            self.body.addLayout(self.header)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(theme.c("surface"))
        p.setPen(QPen(theme.c("border"), 1))
        p.drawRoundedRect(rect, 16, 16)


# ------------------------------------------------------------- setting row ----
class SettingRow(QWidget):
    """Title + optional description on the left, a Toggle on the right."""

    toggled = Signal(bool)

    def __init__(self, title, description=None, checked=False, icon=None):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 2, 0, 2)
        row.setSpacing(12)
        if icon:
            ic = Icon(icon, 12, "muted")
            ic.setFixedWidth(20)
            row.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        self.title = label(title)
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
    """Label, live value and a slider mapping ints to a float range."""

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
    """Status chip: a coloured dot (optionally pulsing) and text."""

    def __init__(self, text="", color="muted", pulse=False):
        super().__init__()
        self._text, self._color, self._phase = text, color, 0.0
        self.setFont(theme.font(9, QFont.Weight.DemiBold))
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.set_state(text, color, pulse)

    def set_state(self, text, color="muted", pulse=False):
        self._text, self._color = text, color
        if pulse and not self._timer.isActive():
            self._timer.start(33)
        elif not pulse:
            self._timer.stop()
            self._phase = 0.0
        self.updateGeometry()
        self.update()

    def _tick(self):
        self._phase = (self._phase + 0.045) % 1.0
        self.update()

    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self._text) + 34, 26)

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        color = theme.c(self._color)
        bg = QColor(color)
        bg.setAlphaF(0.14)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        cx, cy = 14, rect.center().y()
        if self._timer.isActive():
            ring = QColor(color)
            ring.setAlphaF(0.5 * (1 - self._phase))
            p.setBrush(ring)
            r = 3.5 + 5 * self._phase
            p.drawEllipse(QPointF(cx, cy), r, r)
        p.setBrush(color)
        p.drawEllipse(QPointF(cx, cy), 3.5, 3.5)
        p.setPen(color)
        p.setFont(self.font())
        p.drawText(QRectF(24, 0, rect.width() - 28, rect.height()),
                   Qt.AlignmentFlag.AlignVCenter, self._text)


# ----------------------------------------------------------------- spinner ----
class Spinner(QWidget):
    def __init__(self, size=28, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def _tick(self):
        self._angle = (self._angle + 6) % 360
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        p.setPen(QPen(theme.c("surface3"), 3))
        p.drawEllipse(rect)
        pen = QPen(theme.c("accent"), 3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, int(-self._angle * 16), int(100 * 16))


# ----------------------------------------------------------------- sidebar ----
class NavButton(QAbstractButton):
    def __init__(self, text, icon):
        super().__init__()
        self.setText(text)
        self._icon = theme.ICONS[icon]
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(42)
        self._hover = 0.0
        self._hover_anim = _hover_anim(self)
        self.setFont(theme.font(10, QFont.Weight.Medium))

    def enterEvent(self, event):
        _animate(self._hover_anim, self._hover, 1.0)

    def leaveEvent(self, event):
        _animate(self._hover_anim, self._hover, 0.0)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        if not self.isChecked() and self._hover > 0:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.c("surface2", self._hover))
            p.drawRoundedRect(rect, 10, 10)
        active = self.isChecked()
        fg = theme.c("text") if active else theme.mix(theme.c("muted"), theme.c("text"), self._hover)
        p.setPen(theme.c("accent") if active else fg)
        p.setFont(theme.icon_font(12))
        p.drawText(QRectF(14, 0, 24, rect.height()), Qt.AlignmentFlag.AlignCenter, self._icon)
        p.setPen(fg)
        p.setFont(self.font())
        p.drawText(QRectF(48, 0, rect.width() - 52, rect.height()),
                   Qt.AlignmentFlag.AlignVCenter, self.text())


class NavIndicator(QWidget):
    """Highlight pill behind the active nav button; slides between items."""

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.c("surface3"))
        p.drawRoundedRect(rect, 10, 10)
        grad = QLinearGradient(0, 0, 0, rect.height())
        grad.setColorAt(0, theme.c("accent"))
        grad.setColorAt(1, theme.c("accent2"))
        p.setBrush(grad)
        p.drawRoundedRect(QRectF(0, 10, 3.5, rect.height() - 20), 2, 2)


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
        self._anim.setDuration(320)
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
            self._anim.stop()
            self._anim.setStartValue(self._indicator.geometry())
            self._anim.setEndValue(target)
            self._anim.start()
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
    """Stacked pages that fade and slide in when switched."""

    def __init__(self):
        super().__init__()
        self._group = None

    def set_index_animated(self, index):
        if index == self.currentIndex():
            return
        page = self.widget(index)
        self.setCurrentIndex(index)
        effect = QGraphicsOpacityEffect(page)
        page.setGraphicsEffect(effect)
        fade = QPropertyAnimation(effect, b"opacity", page)
        fade.setDuration(260)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(EASE)
        end = page.pos()
        slide = QPropertyAnimation(page, b"pos", page)
        slide.setDuration(320)
        slide.setStartValue(end + QPoint(0, 18))
        slide.setEndValue(end)
        slide.setEasingCurve(QEasingCurve.Type.OutQuint)
        if self._group is not None:
            self._group.stop()
        group = QParallelAnimationGroup(self)
        group.addAnimation(fade)
        group.addAnimation(slide)
        # Drop the effect afterwards: it would force software rendering of
        # the live preview on every frame.
        group.finished.connect(lambda: page.setGraphicsEffect(None))
        self._group = group
        group.start()


# ------------------------------------------------------------------- toast ----
class Toast(QWidget):
    """A small notification that slides up from the bottom of its parent."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._text = ""
        self._kind = "accent"
        self._opacity = 0.0
        self.setFont(theme.font(10, QFont.Weight.Medium))
        self.hide()
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(260)
        self._anim.setEasingCurve(EASE)
        self._anim.valueChanged.connect(self._step)
        self._anim.finished.connect(self._done)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(lambda: self._run(0.0))
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(30)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 110))
        self.setGraphicsEffect(shadow)

    def show_message(self, text, kind="accent", icon="info", msec=2600):
        self._text = text
        self._kind = kind
        self._icon = theme.ICONS.get(icon, "")
        fm = self.fontMetrics()
        w = min(fm.horizontalAdvance(text) + 70, self.parent().width() - 40)
        self.resize(w, 48)
        self.raise_()
        self.show()
        self._run(1.0)
        self._hide_timer.start(msec)

    def _run(self, target):
        self._anim.stop()
        self._anim.setStartValue(self._opacity)
        self._anim.setEndValue(target)
        self._anim.start()

    def _step(self, value):
        self._opacity = float(value)
        parent = self.parent()
        x = (parent.width() - self.width()) // 2
        y = parent.height() - self.height() - 24 + int((1 - self._opacity) * 24)
        self.move(x, y)
        self.update()

    def _done(self):
        if self._opacity <= 0.01:
            self.hide()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self._opacity)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(theme.c("border"), 1))
        p.setBrush(theme.c("surface3"))
        p.drawRoundedRect(rect, 14, 14)
        p.setPen(theme.c(self._kind))
        p.setFont(theme.icon_font(12))
        p.drawText(QRectF(16, 0, 22, rect.height()), Qt.AlignmentFlag.AlignCenter, self._icon)
        p.setPen(theme.c("text"))
        p.setFont(self.font())
        p.drawText(QRectF(46, 0, rect.width() - 56, rect.height()),
                   Qt.AlignmentFlag.AlignVCenter, self._text)


# ---------------------------------------------------------- segmented ctrl ----
class Segmented(QWidget):
    """Two-or-more option switch with a sliding selection pill."""

    changed = Signal(int)

    def __init__(self, options, index=0):
        super().__init__()
        self._options = list(options)
        self._index = index
        self._pos = float(index)
        self.setFixedHeight(34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(theme.font(9.5, QFont.Weight.DemiBold))
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(260)
        self._anim.setEasingCurve(QEasingCurve.Type.OutQuint)
        self._anim.valueChanged.connect(lambda v: (setattr(self, "_pos", float(v)), self.update()))

    def sizeHint(self):
        fm = self.fontMetrics()
        w = max(fm.horizontalAdvance(o) for o in self._options) + 28
        return QSize(w * len(self._options) + 8, 34)

    def mouseReleaseEvent(self, event):
        seg = (self.width() - 8) / len(self._options)
        index = int(max(0, min(len(self._options) - 1, (event.position().x() - 4) // seg)))
        if index != self._index:
            self._index = index
            _animate(self._anim, self._pos, float(index))
            self.changed.emit(index)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.c("surface2"))
        p.drawRoundedRect(rect, 10, 10)
        seg = (rect.width() - 8) / len(self._options)
        grad = QLinearGradient(0, 0, rect.width(), 0)
        grad.setColorAt(0, theme.c("accent"))
        grad.setColorAt(1, theme.c("accent2"))
        p.setBrush(grad)
        p.drawRoundedRect(QRectF(4 + seg * self._pos, 4, seg, rect.height() - 8), 7, 7)
        p.setFont(self.font())
        for i, text in enumerate(self._options):
            closeness = max(0.0, 1 - abs(self._pos - i))
            p.setPen(theme.mix(theme.c("muted"), QColor("white"), closeness))
            p.drawText(QRectF(4 + seg * i, 0, seg, rect.height()), Qt.AlignmentFlag.AlignCenter, text)


def hline():
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {theme.hex_('border')};")
    return line


def ring_path(rect, start_deg, span_deg):
    path = QPainterPath()
    path.arcMoveTo(rect, start_deg)
    path.arcTo(rect, start_deg, span_deg)
    return path
