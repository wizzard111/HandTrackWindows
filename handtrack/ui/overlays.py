"""Full-screen gaze calibration and the startup splash."""

import math

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from handtrack import __version__
from handtrack.ui import theme

GAZE_POINTS = (
    (0.08, 0.08), (0.5, 0.08), (0.92, 0.08),
    (0.08, 0.5), (0.5, 0.5), (0.92, 0.5),
    (0.08, 0.92), (0.5, 0.92), (0.92, 0.92),
)


class GazeCalibrationOverlay(QWidget):
    """Black full-screen canvas. The dot glides between targets and a ring
    fills up while samples are collected for the current point."""

    cancelled = Signal()

    def __init__(self, hint):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setCursor(Qt.CursorShape.BlankCursor)
        self._hint = hint
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)
        self.targets = [QPointF(fx * screen.width(), fy * screen.height()) for fx, fy in GAZE_POINTS]
        self._index = 0
        self._dot = QPointF(self.targets[0])
        self._fill = 0.0
        self._shown_fill = 0.0
        self._phase = 0.0
        self._intro = 0.0
        self._move = QVariantAnimation(self)
        self._move.setDuration(520)
        self._move.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._move.valueChanged.connect(lambda v: setattr(self, "_dot", v))
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def screen_targets(self):
        return [(p.x(), p.y()) for p in self.targets]

    def set_progress(self, index, fill):
        if index != self._index and 0 <= index < len(self.targets):
            self._move.stop()
            self._move.setStartValue(QPointF(self._dot))
            self._move.setEndValue(self.targets[index])
            self._move.start()
            self._index = index
            self._shown_fill = 0.0
        self._fill = min(1.0, fill)

    def _tick(self):
        self._phase = (self._phase + 0.016) % 1.0
        self._intro = min(1.0, self._intro + 0.04)
        self._shown_fill += (self._fill - self._shown_fill) * 0.25
        self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#050507"))
        p.setOpacity(self._intro)

        p.setPen(QColor(255, 255, 255, 150))
        p.setFont(theme.font(13))
        p.drawText(QRectF(0, self.height() / 2 - 120, self.width(), 30),
                   Qt.AlignmentFlag.AlignCenter, self._hint)
        p.setFont(theme.font(11, QFont.Weight.DemiBold))
        p.setPen(QColor(255, 255, 255, 90))
        p.drawText(QRectF(0, self.height() / 2 - 88, self.width(), 26), Qt.AlignmentFlag.AlignCenter,
                   f"{min(self._index + 1, len(self.targets))} / {len(self.targets)}")

        for i, t in enumerate(self.targets):
            if i < self._index:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(theme.c("success", 0.55))
                p.drawEllipse(t, 4, 4)

        center = self._dot
        pulse = 0.5 + 0.5 * math.sin(self._phase * math.tau * 3)
        glow = QRadialGradient(center, 60)
        g = theme.c("accent2")
        g.setAlphaF(0.30 + 0.15 * pulse)
        glow.setColorAt(0, g)
        glow.setColorAt(1, QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(center, 60, 60)

        ring = QRectF(center.x() - 24, center.y() - 24, 48, 48)
        p.setPen(QPen(QColor(255, 255, 255, 40), 4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(ring)
        if self._shown_fill > 0.01:
            pen = QPen(theme.c("accent2"), 4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawArc(ring, 90 * 16, int(-360 * 16 * self._shown_fill))

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("white"))
        r = 7 - 2 * self._shown_fill
        p.drawEllipse(center, r, r)


class Splash(QWidget):
    """Frameless rounded splash with an animated progress sweep."""

    def __init__(self, title, subtitle):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.SplashScreen)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(420, 250)
        self._title, self._subtitle = title, subtitle
        self._status = ""
        self._progress = None
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)
        self._logo = QPixmap(theme_logo_path())
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.center().x() - self.width() // 2, screen.center().y() - self.height() // 2)
        QVBoxLayout(self)

    def set_status(self, text, progress=None):
        self._status = text
        self._progress = progress
        self.update()

    def _tick(self):
        self._phase = (self._phase + 0.012) % 1.0
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(theme.c("border"), 1))
        p.setBrush(theme.c("surface"))
        p.drawRoundedRect(rect, 22, 22)

        angle = self._phase * math.tau
        for i, color in enumerate((theme.c("accent"), theme.c("accent2"))):
            a = angle + i * math.pi
            grad = QRadialGradient(QPointF(rect.center().x() + math.cos(a) * 120, 60 + math.sin(a) * 20), 200)
            c1 = QColor(color)
            c1.setAlphaF(0.16)
            grad.setColorAt(0, c1)
            grad.setColorAt(1, QColor(0, 0, 0, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(grad)
            p.drawRoundedRect(rect, 22, 22)

        if not self._logo.isNull():
            p.drawPixmap(QRectF(rect.center().x() - 32, 36, 64, 64), self._logo, QRectF(self._logo.rect()))
        p.setPen(theme.c("text"))
        p.setFont(theme.font(18, QFont.Weight.Bold))
        p.drawText(QRectF(0, 108, rect.width(), 34), Qt.AlignmentFlag.AlignCenter, self._title)
        p.setPen(theme.c("muted"))
        p.setFont(theme.font(9.5))
        p.drawText(QRectF(0, 140, rect.width(), 20), Qt.AlignmentFlag.AlignCenter,
                   f"{self._subtitle} · v{__version__}")
        p.drawText(QRectF(0, 182, rect.width(), 20), Qt.AlignmentFlag.AlignCenter, self._status)

        bar = QRectF(60, 212, rect.width() - 120, 4)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.c("surface3"))
        p.drawRoundedRect(bar, 2, 2)
        grad = QLinearGradient(bar.topLeft(), bar.topRight())
        grad.setColorAt(0, theme.c("accent"))
        grad.setColorAt(1, theme.c("accent2"))
        p.setBrush(grad)
        if self._progress is None:
            w = bar.width() * 0.3
            x = bar.left() + (bar.width() + w) * ((self._phase * 2.2) % 1.0) - w
            seg = QRectF(max(bar.left(), x), bar.top(), min(x + w, bar.right()) - max(bar.left(), x), 4)
            if seg.width() > 0:
                p.drawRoundedRect(seg, 2, 2)
        else:
            p.drawRoundedRect(QRectF(bar.left(), bar.top(), bar.width() * self._progress / 100, 4), 2, 2)


def theme_logo_path():
    from handtrack import paths
    import os
    return os.path.join(paths.ASSETS_DIR, "icon.png")
