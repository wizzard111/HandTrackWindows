"""Preview surface, covering badge, gaze map and the clickable hand diagram."""

import logging
import math

import cv2
import numpy as np
from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QRadialGradient
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
    """Pulsing red shield with 'COVERING…' text inside ``rect``."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    red = theme.c("accent")
    p.setPen(QPen(theme.c("accent", 0.55), 1))
    p.setBrush(QColor(8, 4, 8, 215))
    p.drawPath(theme.chamfer_path(rect, 10))

    cx, cy = rect.left() + 28, rect.center().y()
    beat = 0.5 + 0.5 * math.sin(phase * math.tau * 2)
    # Expanding ring.
    ring = (phase * 2) % 1.0
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(theme.c("accent", 0.6 * (1 - ring)), 2))
    p.drawPath(shield_path(cx, cy, 11 + 12 * ring))
    glow = QRadialGradient(QPointF(cx, cy), 26)
    glow.setColorAt(0, theme.c("accent", 0.35 + 0.35 * beat))
    glow.setColorAt(1, QColor(0, 0, 0, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(glow)
    p.drawEllipse(QPointF(cx, cy), 26, 26)
    p.setBrush(red)
    p.drawPath(shield_path(cx, cy, 10 + 1.5 * beat))
    p.setPen(QPen(QColor("white"), 1.6))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(QPointF(cx - 4, cy), QPointF(cx - 1, cy + 3))
    p.drawLine(QPointF(cx - 1, cy + 3), QPointF(cx + 4, cy - 3))

    dots = "." * (1 + int(phase * 6) % 3)
    p.setPen(red)
    p.setFont(theme.display_font(11, 2.5))
    p.drawText(QRectF(cx + 22, rect.top() + 6, rect.width() - 60, 22),
               Qt.AlignmentFlag.AlignVCenter, title + dots)
    p.setPen(QColor(255, 255, 255, 170))
    p.setFont(theme.font(8.5))
    p.drawText(QRectF(cx + 22, rect.top() + 26, rect.width() - 60, 18),
               Qt.AlignmentFlag.AlignVCenter, subtitle)
    # Scan line sweeping across the badge.
    x = rect.left() + rect.width() * ((phase * 1.5) % 1.0)
    p.setPen(QPen(theme.c("accent", 0.35), 1))
    p.drawLine(QPointF(x, rect.top() + 2), QPointF(x, rect.bottom() - 2))
    p.restore()


class CoveringBadge(QWidget):
    """Stand-alone animated badge (sidebar), visible while the face is hidden."""

    def __init__(self, title, subtitle):
        super().__init__()
        self._texts = (title, subtitle)
        self._phase = 0.0
        self.setFixedHeight(50)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def set_active(self, active):
        if active:
            self.show()
            self._timer.start(33)
        else:
            self._timer.stop()
            self.hide()

    def _tick(self):
        self._phase = (self._phase + 0.012) % 1.0
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        paint_covering(p, QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), self._phase, *self._texts)


# ----------------------------------------------------------------- preview ----
class PreviewWidget(QWidget):
    """Processed frames in a HUD frame; animated standby screen while stopped."""

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
        self._reveal = 1.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)
        self._reveal_anim = QVariantAnimation(self)
        self._reveal_anim.setDuration(420)
        self._reveal_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._reveal_anim.valueChanged.connect(lambda v: setattr(self, "_reveal", float(v)))

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
            self._reveal = 0.0
            self._reveal_anim.stop()
            self._reveal_anim.setStartValue(0.0)
            self._reveal_anim.setEndValue(1.0)
            self._reveal_anim.start()
        if state in (self.STANDBY, self.STARTING):
            self._image = self._array = None
        if state == self.HIDDEN:
            self._timer.stop()
        elif not self._timer.isActive():
            self._timer.start(33)
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
        self._phase = (self._phase + 0.012) % 1.0
        if self._state != self.LIVE:
            self.update()
        elif self._covering:
            self.update(0, self.height() - 80, 300, 80)
        else:
            self.update(0, 0, self.width(), 60)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        ratio = self.devicePixelRatioF()
        self.sizeChanged.emit(int(self.width() * ratio), int(self.height() * ratio))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        p.fillRect(rect, theme.c("bg"))
        frame_path = theme.chamfer_path(rect.adjusted(0.5, 0.5, -0.5, -0.5), 18)
        p.setClipPath(frame_path)
        p.fillRect(rect, theme.c("stage"))
        target = rect
        if self._state == self.LIVE and self._image is not None:
            img = self._image
            scale = min(rect.width() / img.width(), rect.height() / img.height())
            w, h = img.width() * scale, img.height() * scale
            target = QRectF((rect.width() - w) / 2, (rect.height() - h) / 2, w, h)
            if abs(scale - 1.0) > 0.01:
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.setOpacity(self._reveal)
            p.drawImage(target, img)
            p.setOpacity(1.0)
            self._paint_live_overlay(p, rect)
            self.framePainted.emit()
        elif self._state == self.HIDDEN:
            p.setPen(QColor(255, 255, 255, 150))
            theme.draw_icon(p, "eye", QRectF(rect.center().x() - 16, rect.center().y() - 52, 32, 32),
                            QColor(255, 255, 255, 150))
            p.setFont(theme.font(10.5))
            p.drawText(QRectF(40, rect.center().y(), rect.width() - 80, 60),
                       Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap, self._texts[2])
        else:
            self._paint_standby(p, rect)
        p.setClipping(False)
        p.setPen(QPen(theme.c("border"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(frame_path)
        self._paint_brackets(p, target if self._state == self.LIVE else rect.adjusted(14, 14, -14, -14))

    def _paint_brackets(self, p, r):
        p.setPen(QPen(theme.c("accent"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap))
        n = 18
        for (x, y, dx, dy) in ((r.left(), r.top(), 1, 1), (r.right(), r.top(), -1, 1),
                               (r.left(), r.bottom(), 1, -1), (r.right(), r.bottom(), -1, -1)):
            p.drawLine(QPointF(x, y), QPointF(x + dx * n, y))
            p.drawLine(QPointF(x, y), QPointF(x, y + dy * n))

    def _paint_live_overlay(self, p, rect):
        p.setFont(theme.display_font(9, 2))
        live = self._texts[3]
        fm = p.fontMetrics()
        badge = QRectF(18, 18, fm.horizontalAdvance(live.upper()) + 36, 26)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 170))
        p.drawPath(theme.chamfer_path(badge, 7))
        beat = 0.5 + 0.5 * math.sin(self._phase * math.tau * 3)
        p.setBrush(theme.c("accent", 0.45 + 0.55 * beat))
        p.drawRect(QRectF(badge.left() + 11, badge.center().y() - 4, 8, 8))
        p.setPen(QColor("white"))
        p.drawText(badge.adjusted(26, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, live.upper())
        if self._fps:
            text = f"{self._fps:.0f} FPS"
            w = fm.horizontalAdvance(text) + 24
            fbox = QRectF(rect.width() - 18 - w, 18, w, 26)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 170))
            p.drawPath(theme.chamfer_path(fbox, 7))
            p.setPen(QColor(255, 255, 255, 220))
            p.drawText(fbox, Qt.AlignmentFlag.AlignCenter, text)
        if self._covering:
            paint_covering(p, QRectF(18, rect.height() - 70, 250, 50), self._phase,
                           self._texts[4], self._texts[5])

    def _paint_standby(self, p, rect):
        cx, cy = rect.center().x(), rect.center().y() - 24
        t = self._phase
        # Slow purple/red haze.
        for i, color in enumerate((theme.c("accent2"), theme.c("accent"))):
            angle = (t + i * 0.5) * math.tau
            grad = QRadialGradient(QPointF(cx + math.cos(angle) * 60, cy + math.sin(angle) * 30), 230)
            grad.setColorAt(0, theme.c("accent2" if i == 0 else "accent", 0.20 if i == 0 else 0.10))
            grad.setColorAt(1, QColor(0, 0, 0, 0))
            p.fillRect(rect, grad)
        # Faint scan grid.
        p.setPen(QPen(QColor(255, 255, 255, 10), 1))
        step = 32
        for x in range(0, int(rect.width()), step):
            p.drawLine(x, 0, x, int(rect.height()))
        for y in range(0, int(rect.height()), step):
            p.drawLine(0, y, int(rect.width()), y)
        scan_y = rect.height() * ((t * 1.4) % 1.0)
        p.setPen(QPen(theme.c("accent", 0.25), 1))
        p.drawLine(QPointF(0, scan_y), QPointF(rect.width(), scan_y))

        beat = 0.5 + 0.5 * math.sin(t * math.tau * 2)
        hexr = 46 + 4 * beat
        p.setPen(QPen(theme.c("accent", 0.5 + 0.4 * beat), 2))
        p.setBrush(QColor(0, 0, 0, 160))
        p.drawPath(theme.chamfer_path(QRectF(cx - hexr, cy - hexr, 2 * hexr, 2 * hexr), 16, "tl,tr,br,bl"))
        if self._state == self.STARTING:
            pen = QPen(theme.c("accent"), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap)
            p.setPen(pen)
            p.drawArc(QRectF(cx - 58, cy - 58, 116, 116), int(-t * 360 * 4 * 16), 70 * 16)
        theme.draw_icon(p, "camera", QRectF(cx - 18, cy - 18, 36, 36), QColor("white"))
        p.setPen(QColor("white"))
        p.setFont(theme.display_font(17, 3))
        p.drawText(QRectF(0, cy + 66, rect.width(), 34), Qt.AlignmentFlag.AlignCenter, self._texts[0])
        p.setPen(QColor(255, 255, 255, 130))
        p.setFont(theme.font(10))
        p.drawText(QRectF(0, cy + 100, rect.width(), 24), Qt.AlignmentFlag.AlignCenter, self._texts[1])


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
        p.drawPath(theme.chamfer_path(rect, 10))
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
        glow = QRadialGradient(QPointF(x, y), 28)
        glow.setColorAt(0, theme.c("accent", 0.5 * self._visible))
        glow.setColorAt(1, QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QPointF(x, y), 28, 28)
        p.setPen(QPen(theme.c("accent", self._visible), 2))
        p.drawLine(QPointF(x - 12, y), QPointF(x - 4, y))
        p.drawLine(QPointF(x + 4, y), QPointF(x + 12, y))
        p.drawLine(QPointF(x, y - 12), QPointF(x, y - 4))
        p.drawLine(QPointF(x, y + 4), QPointF(x, y + 12))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, int(255 * self._visible)))
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
    """Clickable palm outline; raised fingers glow red. Cross-fades on change."""

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
        selected = np.minimum(self._alpha, zone)
        glow = cv2.GaussianBlur(selected, (0, 0), 9)
        on, off = theme.c("accent"), theme.c("faint")
        rgba = np.zeros((size, size, 4), np.float32)
        # Glow underneath, outline on top (premultiplied "over").
        ga = np.clip(glow.astype(np.float32) * 0.9, 0, 190)[..., None] / 255.0
        rgba[..., :3] = np.array((on.red(), on.green(), on.blue()), np.float32) * ga
        rgba[..., 3:4] = ga
        sel = (selected > 0)[..., None]
        line_rgb = np.where(sel, (on.red(), on.green(), on.blue()), (off.red(), off.green(), off.blue()))
        la = self._alpha.astype(np.float32)[..., None] / 255.0
        rgba[..., :3] = line_rgb * la + rgba[..., :3] * (1 - la)
        rgba[..., 3:4] = la + rgba[..., 3:4] * (1 - la)
        # Un-premultiply for QImage RGBA8888.
        alpha = np.maximum(rgba[..., 3:4], 1e-6)
        out = np.dstack([np.clip(rgba[..., :3] / alpha, 0, 255), rgba[..., 3:4] * 255]).astype(np.uint8)
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
            p.setPen(QColor("white") if on else theme.c("text"))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, str(i + 1))


class FingerChips(QWidget):
    fingerToggled = Signal(int)

    def __init__(self, names):
        super().__init__()
        self.names = list(names)
        self.pattern = (False,) * 5
        self.setFixedHeight(32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._font = theme.display_font(8, 0.8)

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
