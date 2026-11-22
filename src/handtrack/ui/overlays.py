"""Full-screen gaze calibration and the startup splash."""

import math

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QApplication, QWidget

from handtrack import __version__, paths
from handtrack.ui import theme

GAZE_POINTS = (
    (0.08, 0.08), (0.5, 0.08), (0.92, 0.08),
    (0.08, 0.5), (0.5, 0.5), (0.92, 0.5),
    (0.08, 0.92), (0.5, 0.92), (0.92, 0.92),
)


class GazeCalibrationOverlay(QWidget):
    """Black full-screen canvas; a red target glides between points and a
    ring fills while samples are collected."""

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
        self._fill = self._shown_fill = 0.0
        self._phase = 0.0
        self._intro = 0.0
        self._move = QVariantAnimation(self)
        self._move.setDuration(480)
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
        p.fillRect(self.rect(), QColor("#030203"))
        p.setOpacity(self._intro)
        red = theme.c("accent")

        p.setPen(QColor(255, 255, 255, 160))
        p.setFont(theme.font(13))
        p.drawText(QRectF(0, self.height() / 2 - 120, self.width(), 30), Qt.AlignmentFlag.AlignCenter, self._hint)
        p.setFont(theme.display_font(14, 4))
        p.setPen(red)
        p.drawText(QRectF(0, self.height() / 2 - 86, self.width(), 30), Qt.AlignmentFlag.AlignCenter,
                   f"{min(self._index + 1, len(self.targets))} / {len(self.targets)}")

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.c("accent", 0.6))
        for i, t in enumerate(self.targets):
            if i < self._index:
                p.drawRect(QRectF(t.x() - 3, t.y() - 3, 6, 6))

        c = self._dot
        beat = 0.5 + 0.5 * math.sin(self._phase * math.tau * 3)
        glow = QRadialGradient(c, 70)
        glow.setColorAt(0, theme.c("accent", 0.30 + 0.2 * beat))
        glow.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(glow)
        p.drawEllipse(c, 70, 70)
        ring = QRectF(c.x() - 26, c.y() - 26, 52, 52)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 40), 4))
        p.drawEllipse(ring)
        if self._shown_fill > 0.01:
            p.setPen(QPen(red, 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
            p.drawArc(ring, 90 * 16, int(-360 * 16 * self._shown_fill))
        p.setPen(QPen(red, 2))
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            p.drawLine(QPointF(c.x() + dx * 34, c.y() + dy * 34), QPointF(c.x() + dx * 44, c.y() + dy * 44))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("white"))
        r = 6 - 2 * self._shown_fill
        p.drawRect(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r))


class Splash(QWidget):
    """Frameless chamfered splash with a red progress sweep."""

    def __init__(self, title, subtitle):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.SplashScreen)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(440, 250)
        self._title, self._subtitle = title, subtitle
        self._status = ""
        self._progress = None
        self._phase = 0.0
        self._logo = QPixmap(paths.LOGO_PATH)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.center().x() - self.width() // 2, screen.center().y() - self.height() // 2)

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
        path = theme.chamfer_path(rect, 22)
        p.setPen(QPen(theme.c("border"), 1))
        p.setBrush(theme.c("surface"))
        p.drawPath(path)
        p.setClipPath(path)
        a = self._phase * math.tau
        grad = QRadialGradient(QPointF(rect.center().x() + math.cos(a) * 120, 40), 230)
        grad.setColorAt(0, theme.c("accent2", 0.35))
        grad.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(rect, grad)
        p.setClipping(False)
        p.setPen(QPen(theme.c("accent"), 2))
        p.drawLine(QPointF(rect.left() + 1, rect.top() + 22), QPointF(rect.left() + 22, rect.top() + 1))

        if not self._logo.isNull():
            p.drawPixmap(QRectF(rect.center().x() - 30, 30, 60, 60), self._logo, QRectF(self._logo.rect()))
        p.setPen(theme.c("text"))
        p.setFont(theme.display_font(22, 6))
        p.drawText(QRectF(0, 100, rect.width(), 40), Qt.AlignmentFlag.AlignCenter, self._title)
        p.setPen(theme.c("muted"))
        p.setFont(theme.font(9.5))
        p.drawText(QRectF(0, 140, rect.width(), 20), Qt.AlignmentFlag.AlignCenter,
                   f"{self._subtitle} · v{__version__}")
        p.drawText(QRectF(0, 184, rect.width(), 20), Qt.AlignmentFlag.AlignCenter, self._status)

        bar = QRectF(60, 214, rect.width() - 120, 3)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.c("surface3"))
        p.drawRect(bar)
        grad = QLinearGradient(bar.topLeft(), bar.topRight())
        grad.setColorAt(0, theme.c("accent2"))
        grad.setColorAt(1, theme.c("accent"))
        p.setBrush(grad)
        if self._progress is None:
            w = bar.width() * 0.3
            x = bar.left() + (bar.width() + w) * ((self._phase * 2.2) % 1.0) - w
            left, right = max(bar.left(), x), min(x + w, bar.right())
            if right > left:
                p.drawRect(QRectF(left, bar.top(), right - left, bar.height()))
        else:
            p.drawRect(QRectF(bar.left(), bar.top(), bar.width() * self._progress / 100, bar.height()))
