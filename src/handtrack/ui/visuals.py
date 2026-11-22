"""Preview surface, covering badge, gaze map and the clickable hand diagram."""

import logging
import math

import cv2
import numpy as np
from PySide6.QtCore import (
    QEasingCurve, QElapsedTimer, QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal,
)
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from handtrack import paths
from handtrack.ui import theme

logger = logging.getLogger("handtrack")

SHIELD = ((0.0, -1.0), (0.82, -0.68), (0.72, 0.25), (0.0, 1.0), (-0.72, 0.25), (-0.82, -0.68))


def shield_path(cx, cy, r):
    path = QPainterPath()
    path.addPolygon(QPolygonF([QPointF(cx + x * r, cy + y * r) for x, y in SHIELD]))
    path.closeSubpath()
    return path


def paint_covering(p, rect, phase, title, subtitle):
    """Flat status plate: red shield, blinking marker and 'COVERING…'."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    red = theme.c("accent")
    p.setPen(QPen(red, 1))
    p.setBrush(QColor(0, 0, 0, 225))
    p.drawRect(rect)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(red)
    p.drawRect(QRectF(rect.left(), rect.top(), 3, rect.height()))

    cx, cy = rect.left() + 26, rect.center().y()
    on = int(phase * 4) % 2 == 0           # ~2 blinks per second
    p.setBrush(red if on else theme.c("accent", 0.45))
    p.drawPath(shield_path(cx, cy, 11))
    p.setPen(QPen(QColor("white"), 1.6))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(QPointF(cx - 4, cy), QPointF(cx - 1, cy + 3))
    p.drawLine(QPointF(cx - 1, cy + 3), QPointF(cx + 4, cy - 3))

    dots = "." * (1 + int(phase * 6) % 3)
    p.setPen(red)
    p.setFont(theme.mono(10, True, 1.5))
    p.drawText(QRectF(cx + 20, rect.top() + 5, rect.width() - 56, 20),
               Qt.AlignmentFlag.AlignVCenter, title + dots)
    p.setPen(QColor(255, 255, 255, 160))
    p.setFont(theme.mono(8, False, 0.3, upper=False))
    p.drawText(QRectF(cx + 20, rect.top() + 24, rect.width() - 56, 18),
               Qt.AlignmentFlag.AlignVCenter, subtitle)
    p.restore()


class CoveringBadge(QWidget):
    """Stand-alone badge (sidebar), visible while the face is hidden."""

    def __init__(self, title, subtitle):
        super().__init__()
        self._texts = (title, subtitle)
        self._phase = 0.0
        self.setFixedHeight(48)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def set_active(self, active):
        if active:
            self.show()
            self._timer.start(125)
        else:
            self._timer.stop()
            self.hide()

    def _tick(self):
        self._phase = (self._phase + 0.0625) % 1.0
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        paint_covering(p, QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), self._phase, *self._texts)


# ----------------------------------------------------------------- preview ----
class PreviewWidget(QWidget):
    """Processed frames framed like a camera viewfinder; NO SIGNAL while stopped."""

    sizeChanged = Signal(int, int)
    framePainted = Signal()

    STANDBY, STARTING, LIVE, HIDDEN = range(4)

    def __init__(self):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(360, 220)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self._state = self.STANDBY
        self._image = None
        self._array = None
        self._fps = 0.0
        self._texts = ("", "", "", "LIVE", "COVERING", "")
        self._covering = False
        self._phase = 0.0
        self._live_since = 0.0
        self._clock = QElapsedTimer()
        self._clock.start()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(125)

    def set_texts(self, standby_title, standby_hint, hidden, live, covering, covering_sub):
        self._texts = (standby_title, standby_hint, hidden, live, covering, covering_sub)
        self.update()

    def set_covering(self, on):
        self._covering = on
        self.update()

    def set_state(self, state):
        if state == self._state:
            return
        self._state = state
        if state == self.LIVE:
            self._live_since = self._clock.elapsed() / 1000.0
        if state in (self.STANDBY, self.STARTING):
            self._image = self._array = None
        if state == self.HIDDEN:
            self._timer.stop()
        elif not self._timer.isActive():
            self._timer.start(125)
        self.update()

    def set_frame(self, array):
        h, w = array.shape[:2]
        self._array = array  # keeps the buffer alive for the QImage
        self._image = QImage(array.data, w, h, array.strides[0], QImage.Format.Format_BGR888)
        if self._state != self.LIVE:
            self.set_state(self.LIVE)
        self.update()

    def set_fps(self, fps):
        self._fps = fps

    def _tick(self):
        self._phase = (self._phase + 0.0625) % 1.0
        if self._state != self.LIVE:
            self.update()
        elif self._covering:
            self.update(0, self.height() - 80, 320, 80)
        # Live frames repaint the widget anyway; the read-out rides along.

    def resizeEvent(self, event):
        super().resizeEvent(event)
        ratio = self.devicePixelRatioF()
        self.sizeChanged.emit(int(self.width() * ratio), int(self.height() * ratio))

    def paintEvent(self, event):
        p = QPainter(self)
        rect = QRectF(self.rect())
        p.fillRect(rect, theme.c("stage"))
        target = rect.adjusted(16, 16, -16, -16)
        if self._state == self.LIVE and self._image is not None:
            img = self._image
            scale = min(rect.width() / img.width(), rect.height() / img.height())
            w, h = img.width() * scale, img.height() * scale
            target = QRectF((rect.width() - w) / 2, (rect.height() - h) / 2, w, h)
            if abs(scale - 1.0) > 0.01:
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawImage(target, img)
            self._paint_live_overlay(p, rect, target)
            self.framePainted.emit()
        elif self._state == self.HIDDEN:
            theme.draw_icon(p, "eye", QRectF(rect.center().x() - 14, rect.center().y() - 48, 28, 28),
                            QColor(255, 255, 255, 140))
            p.setPen(QColor(255, 255, 255, 150))
            p.setFont(theme.mono(9, False, 0.3, upper=False))
            p.drawText(QRectF(40, rect.center().y(), rect.width() - 80, 60),
                       Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap, self._texts[2])
        else:
            self._paint_standby(p, rect)
        p.setPen(QPen(theme.c("border"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(rect.adjusted(0.5, 0.5, -0.5, -0.5))
        theme.draw_corner_marks(p, target.adjusted(6, 6, -6, -6), QColor(255, 255, 255, 170), 14, 1.5)

    def _readout(self, p, x, y, text, color=None, align_right=False, box=True):
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(text) + 14
        r = QRectF(x - w if align_right else x, y, w, 20)
        if box:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 190))
            p.drawRect(r)
        p.setPen(color or QColor(255, 255, 255, 220))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)
        return r

    def _paint_live_overlay(self, p, rect, target):
        p.setFont(theme.mono(8.5, True, 1.0))
        top = max(10.0, target.top() + 14)
        left, right = target.left() + 14, target.right() - 14
        on = int(self._phase * 4) % 2 == 0
        r = self._readout(p, left, top, "   " + self._texts[3].upper())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.c("accent") if on else theme.c("accent", 0.35))
        p.drawRect(QRectF(r.left() + 7, r.center().y() - 3.5, 7, 7))
        secs = int(self._clock.elapsed() / 1000.0 - self._live_since)
        self._readout(p, r.right() + 6, top, f"{secs // 3600:02d}:{secs // 60 % 60:02d}:{secs % 60:02d}")
        if self._image is not None:
            res = f"{self._array.shape[1]}x{self._array.shape[0]}" if self._array is not None else ""
            fps = f"{self._fps:4.1f} FPS" if self._fps else "-- FPS"
            self._readout(p, right, top, f"{res}  {fps}", align_right=True)
        if self._covering:
            paint_covering(p, QRectF(left, target.bottom() - 62, 260, 48), self._phase,
                           self._texts[4], self._texts[5])

    def _paint_standby(self, p, rect):
        cx, cy = rect.center().x(), rect.center().y() - 16
        # Fine grid, centre crosshair, bars of a test pattern.
        p.setPen(QPen(QColor(255, 255, 255, 9), 1))
        step = 40
        for x in range(int(rect.width() / 2) % step, int(rect.width()), step):
            p.drawLine(x, 0, x, int(rect.height()))
        for y in range(int(rect.height() / 2) % step, int(rect.height()), step):
            p.drawLine(0, y, int(rect.width()), y)
        p.setPen(QPen(QColor(255, 255, 255, 60), 1))
        p.drawLine(QPointF(cx - 40, cy), QPointF(cx - 12, cy))
        p.drawLine(QPointF(cx + 12, cy), QPointF(cx + 40, cy))
        p.drawLine(QPointF(cx, cy - 40), QPointF(cx, cy - 12))
        p.drawLine(QPointF(cx, cy + 12), QPointF(cx, cy + 40))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(cx - 4, cy - 4, 8, 8))

        p.setFont(theme.mono(15, True, 4))
        title = self._texts[0]
        if self._state == self.STARTING:
            title += "." * (1 + int(self._phase * 8) % 3)
        p.setPen(QColor(255, 255, 255, 230))
        p.drawText(QRectF(0, cy + 52, rect.width(), 30), Qt.AlignmentFlag.AlignCenter, title)
        p.setPen(QColor(255, 255, 255, 110))
        p.setFont(theme.mono(8.5, False, 0.4, upper=False))
        p.drawText(QRectF(0, cy + 84, rect.width(), 22), Qt.AlignmentFlag.AlignCenter, self._texts[1])
        # Signal-loss marker in the corner.
        on = int(self._phase * 4) % 2 == 0
        p.setFont(theme.mono(8.5, True, 1.0))
        r = self._readout(p, 30, 30, "   NO SIGNAL", QColor(255, 255, 255, 200))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.c("accent") if on else theme.c("accent", 0.3))
        p.drawRect(QRectF(r.left() + 7, r.center().y() - 3.5, 7, 7))


# ---------------------------------------------------------------- gaze map ----
class GazeMap(QWidget):
    """Screen-shaped map with a gliding crosshair."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(150)
        self._target = None
        self._pos = QPointF(0.5, 0.5)
        self._visible = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def set_point(self, point):
        self._target = None if point is None else QPointF(*point)
        if not self._timer.isActive():
            self._timer.start(16)

    def _tick(self):
        goal = 1.0 if self._target is not None else 0.0
        self._visible += (goal - self._visible) * 0.15
        if self._target is not None:
            self._pos += (self._target - self._pos) * 0.22
        moving = self._target is not None and (
            abs(self._target.x() - self._pos.x()) + abs(self._target.y() - self._pos.y()) > 0.001)
        if not moving and abs(goal - self._visible) < 0.01:
            self._visible = goal
            self._timer.stop()
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(theme.c("border"), 1))
        p.setBrush(theme.c("stage"))
        p.drawRect(rect)
        p.setPen(QPen(theme.c("surface3"), 1, Qt.PenStyle.DashLine))
        for i in (1, 2):
            x = rect.left() + rect.width() * i / 3
            y = rect.top() + rect.height() * i / 3
            p.drawLine(QPointF(x, rect.top() + 8), QPointF(x, rect.bottom() - 8))
            p.drawLine(QPointF(rect.left() + 8, y), QPointF(rect.right() - 8, y))
        if self._visible < 0.01:
            return
        x = rect.left() + 10 + (rect.width() - 20) * self._pos.x()
        y = rect.top() + 10 + (rect.height() - 20) * self._pos.y()
        p.setPen(QPen(theme.c("accent", self._visible), 2))
        p.drawLine(QPointF(x - 12, y), QPointF(x - 4, y))
        p.drawLine(QPointF(x + 4, y), QPointF(x + 12, y))
        p.drawLine(QPointF(x, y - 12), QPointF(x, y - 4))
        p.drawLine(QPointF(x, y + 4), QPointF(x, y + 12))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.c("accent_text", self._visible))
        p.drawRect(QRectF(x - 2, y - 2, 4, 4))


# ------------------------------------------------------------ hand diagram ----
HAND_SOURCE_SIZE = 360
HAND_FINGER_ZONES = (       # source pixels, thumb … pinky
    ((30, 135), (112, 135), (112, 275), (30, 275)),
    ((88, 32), (160, 32), (160, 248), (88, 248)),
    ((136, 0), (216, 0), (216, 194), (136, 194)),
    ((192, 15), (273, 15), (273, 194), (192, 194)),
    ((249, 43), (330, 43), (330, 210), (249, 210)),
)
HAND_NUMBER_POINTS = ((70, 158), (124, 55), (178, 15), (232, 38), (286, 67))


def _load_hand_alpha():
    try:
        data = np.fromfile(paths.HAND_REFERENCE_PATH, dtype=np.uint8)
        gray = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
        if gray is None:
            raise ValueError("unreadable")
    except (OSError, ValueError):
        logger.exception("Could not load hand reference image")
        img = np.zeros((HAND_SOURCE_SIZE, HAND_SOURCE_SIZE), np.uint8)
        for box in ((42, 145, 320, 350), (91, 43, 151, 247), (145, 3, 211, 188),
                    (199, 23, 269, 190), (257, 52, 320, 204)):
            cv2.rectangle(img, box[:2], box[2:], 255, 18)
        return img
    gray = cv2.resize(gray, (HAND_SOURCE_SIZE, HAND_SOURCE_SIZE), interpolation=cv2.INTER_AREA)
    # Dark outline on a light checkerboard → alpha mask of the outline only.
    return np.clip((190 - gray.astype(np.int16)) * 4, 0, 255).astype(np.uint8)


class HandDiagram(QWidget):
    """Clickable palm outline; raised fingers turn red. Cross-fades on change."""

    fingerToggled = Signal(int)

    def __init__(self, size=300):
        super().__init__()
        self._size = size
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self._alpha = _load_hand_alpha()
        self._cache = {}
        self.pattern = (False,) * 5
        self._prev = None
        self._fade = 1.0
        self._pop = [0.0] * 5
        self._hover = -1
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(200)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(lambda v: (setattr(self, "_fade", float(v)), self.update()))
        self._pop_timer = QTimer(self)
        self._pop_timer.timeout.connect(self._pop_tick)

    def set_pattern(self, pattern, animate=True):
        pattern = tuple(bool(x) for x in pattern)
        if pattern == self.pattern:
            return
        if animate:
            self._prev = self._pixmap(self.pattern)
            for i, (a, b) in enumerate(zip(self.pattern, pattern)):
                if a != b:
                    self._pop[i] = 1.0
            self._pop_timer.start(16)
            self._anim.stop()
            self._anim.setStartValue(0.0)
            self._anim.setEndValue(1.0)
            self._anim.start()
        self.pattern = pattern
        self.update()

    def _pop_tick(self):
        self._pop = [max(0.0, v - 0.07) for v in self._pop]
        if not any(self._pop):
            self._pop_timer.stop()
        self.update()

    def _pixmap(self, pattern):
        ratio = self.devicePixelRatioF()
        key = (pattern, theme.is_dark(), ratio)
        pix = self._cache.get(key)
        if pix is not None:
            return pix
        size = HAND_SOURCE_SIZE
        zone = np.zeros((size, size), np.uint8)
        for enabled, polygon in zip(pattern, HAND_FINGER_ZONES):
            if enabled:
                cv2.fillPoly(zone, [np.array(polygon, np.int32)], 255)
        # Outline only: raised fingers in red, the rest in grey.
        selected = np.minimum(self._alpha, zone) > 0
        on, off = theme.c("accent"), theme.c("faint")
        out = np.zeros((size, size, 4), np.uint8)
        out[...] = (off.red(), off.green(), off.blue(), 0)
        out[selected, :3] = (on.red(), on.green(), on.blue())
        out[..., 3] = self._alpha
        px = int(self._size * 0.9 * ratio)
        out = cv2.resize(out, (px, px), interpolation=cv2.INTER_AREA)
        qimg = QImage(out.data, px, px, px * 4, QImage.Format.Format_RGBA8888).copy()
        pix = QPixmap.fromImage(qimg)
        pix.setDevicePixelRatio(ratio)
        self._cache[key] = pix
        return pix

    def _geometry(self):
        draw = self._size * 0.9
        return (self._size - draw) / 2, draw / HAND_SOURCE_SIZE

    def _finger_at(self, pos):
        offset, scale = self._geometry()
        sx, sy = (pos.x() - offset) / scale, (pos.y() - offset) / scale
        best = None
        for i, polygon in enumerate(HAND_FINGER_ZONES):
            xs = [pt[0] for pt in polygon]
            ys = [pt[1] for pt in polygon]
            if min(xs) <= sx <= max(xs) and min(ys) <= sy <= max(ys):
                tx, ty = HAND_NUMBER_POINTS[i]
                d = (sx - tx) ** 2 + (sy - ty) ** 2
                if best is None or d < best[0]:
                    best = (d, i)
        return None if best is None else best[1]

    def mouseMoveEvent(self, event):
        finger = self._finger_at(event.position())
        hover = -1 if finger is None else finger
        if hover != self._hover:
            self._hover = hover
            self.update()

    def leaveEvent(self, event):
        self._hover = -1
        self.update()

    def mouseReleaseEvent(self, event):
        finger = self._finger_at(event.position())
        if finger is not None:
            self.fingerToggled.emit(finger)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        offset, scale = self._geometry()
        current = self._pixmap(self.pattern)
        if self._prev is not None and self._fade < 1.0:
            p.setOpacity(1.0 - self._fade)
            p.drawPixmap(QPointF(offset, offset), self._prev)
            p.setOpacity(self._fade)
        p.drawPixmap(QPointF(offset, offset), current)
        p.setOpacity(1.0)
        p.setFont(theme.display_font(9, 0))
        for i, (sx, sy) in enumerate(HAND_NUMBER_POINTS):
            x, y = offset + sx * scale, offset + sy * scale
            r = 11 + 5 * math.sin(self._pop[i] * math.pi) + (1.5 if i == self._hover else 0)
            on = self.pattern[i]
            box = QRectF(x - r, y - r, 2 * r, 2 * r)
            p.setPen(QPen(theme.c("surface"), 2))
            p.setBrush(theme.c("accent") if on else theme.c("surface3"))
            p.drawPath(theme.chamfer_path(box, 5, "tl,tr,br,bl"))
            p.setPen(theme.c("accent_text") if on else theme.c("text"))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, str(i + 1))


class FingerChips(QWidget):
    fingerToggled = Signal(int)

    def __init__(self, names):
        super().__init__()
        self.names = list(names)
        self.pattern = (False,) * 5
        self.setFixedHeight(32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._font = theme.mono(7.5, True, 0.4)

    def set_pattern(self, pattern):
        self.pattern = tuple(pattern)
        self.update()

    def sizeHint(self):
        return QSize(300, 32)

    def _rects(self):
        gap = 5
        w = (self.width() - gap * 4) / 5
        return [QRectF(i * (w + gap), 0.5, w, self.height() - 1) for i in range(5)]

    def mouseReleaseEvent(self, event):
        for i, r in enumerate(self._rects()):
            if r.contains(event.position()):
                self.fingerToggled.emit(i)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(self._font)
        for i, r in enumerate(self._rects()):
            on = self.pattern[i]
            p.setPen(QPen(theme.c("accent") if on else theme.c("border"), 1))
            p.setBrush(theme.c("accent", 0.16) if on else theme.c("surface2"))
            p.drawPath(theme.chamfer_path(r, 6))
            p.setPen(theme.c("accent") if on else theme.c("muted"))
            text = p.fontMetrics().elidedText(self.names[i].upper(), Qt.TextElideMode.ElideRight,
                                              int(r.width() - 6))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)


def pattern_icon(pattern, size=34):
    """Tiny five-bar glyph of a finger pattern for list rows."""
    ratio = 2.0
    pix = QPixmap(int(size * ratio), int(size * ratio))
    pix.setDevicePixelRatio(ratio)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    heights = (0.55, 0.85, 0.95, 0.85, 0.7)
    bw = size / 7.5
    for i, (on, hgt) in enumerate(zip(pattern, heights)):
        full = size * 0.8 * hgt
        h = full if on else full * 0.36
        x = size * 0.1 + i * (bw + bw * 0.4)
        p.setBrush(theme.c("accent") if on else theme.c("faint"))
        p.drawRect(QRectF(x, size * 0.9 - h, bw, h))
    p.end()
    return pix
