"""Preview surface, gaze map and the clickable hand diagram."""

import logging
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import (
    QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from handtrack import paths
from handtrack.ui import theme

logger = logging.getLogger("handtrack")


# ----------------------------------------------------------------- preview ----
class PreviewWidget(QWidget):
    """Shows processed frames; animated standby screen while stopped."""

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
        self._texts = ("", "", "", "LIVE")
        self._phase = 0.0
        self._reveal = 1.0
        self._afk = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)
        self._reveal_anim = QVariantAnimation(self)
        self._reveal_anim.setDuration(450)
        self._reveal_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._reveal_anim.valueChanged.connect(lambda v: setattr(self, "_reveal", float(v)))

    def set_texts(self, standby_title, standby_hint, hidden, live):
        self._texts = (standby_title, standby_hint, hidden, live)
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
        # The animation timer only runs for animated states: no idle CPU use.
        if state == self.LIVE and not self._timer.isActive():
            self._timer.start(33)
        elif state == self.HIDDEN:
            self._timer.stop()
        elif not self._timer.isActive():
            self._timer.start(33)
        self.update()

    def set_frame(self, array):
        h, w = array.shape[:2]
        self._array = array  # keep the buffer alive for the QImage
        self._image = QImage(array.data, w, h, array.strides[0], QImage.Format.Format_BGR888)
        if self._state != self.LIVE:
            self.set_state(self.LIVE)
        self.update()

    def set_fps(self, fps, afk=False):
        self._fps = fps
        self._afk = afk

    def _tick(self):
        self._phase = (self._phase + 0.02) % 1.0
        if self._state != self.LIVE:
            self.update()
        else:
            self.update(QRectF(0, 0, self.width(), 60).toRect())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        ratio = self.devicePixelRatioF()
        self.sizeChanged.emit(int(self.width() * ratio), int(self.height() * ratio))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        p.fillRect(rect, theme.c("bg"))
        clip = QPainterPath()
        clip.addRoundedRect(rect, 18, 18)
        p.setClipPath(clip)
        p.fillRect(rect, QColor("#07080b"))

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
            self._paint_center_text(p, rect, "eye", self._texts[2], "")
        else:
            self._paint_standby(p, rect)

        p.setClipping(False)
        p.setPen(QPen(theme.c("border"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 18, 18)

    def _paint_live_overlay(self, p, rect):
        font = theme.font(9, QFont.Weight.Bold)
        p.setFont(font)
        live = self._texts[3]
        badge = QRectF(14, 14, p.fontMetrics().horizontalAdvance(live) + 34, 26)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 140))
        p.drawRoundedRect(badge, 13, 13)
        pulse = 0.5 + 0.5 * math.sin(self._phase * math.tau * 2)
        red = theme.c("danger")
        glow = QColor(red)
        glow.setAlphaF(0.35 * pulse)
        p.setBrush(glow)
        p.drawEllipse(QPointF(badge.left() + 14, badge.center().y()), 7, 7)
        p.setBrush(red)
        p.drawEllipse(QPointF(badge.left() + 14, badge.center().y()), 4, 4)
        p.setPen(QColor("white"))
        p.drawText(badge.adjusted(25, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, live)
        if self._fps:
            text = f"{self._fps:.0f} FPS"
            fbox = QRectF(rect.width() - 14 - p.fontMetrics().horizontalAdvance(text) - 22, 14,
                          p.fontMetrics().horizontalAdvance(text) + 22, 26)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 140))
            p.drawRoundedRect(fbox, 13, 13)
            p.setPen(QColor(255, 255, 255, 220))
            p.drawText(fbox, Qt.AlignmentFlag.AlignCenter, text)

    def _paint_standby(self, p, rect):
        cx, cy = rect.center().x(), rect.center().y() - 24
        t = self._phase
        # Soft rotating aurora behind the icon.
        for i, color in enumerate((theme.c("accent"), theme.c("accent2"))):
            angle = (t + i * 0.5) * math.tau
            ox, oy = math.cos(angle) * 40, math.sin(angle) * 22
            grad = QRadialGradient(QPointF(cx + ox, cy + oy), 190)
            c1 = QColor(color)
            c1.setAlphaF(0.22)
            grad.setColorAt(0, c1)
            grad.setColorAt(1, QColor(0, 0, 0, 0))
            p.fillRect(rect, grad)
        pulse = 0.5 + 0.5 * math.sin(t * math.tau * 2)
        p.setPen(Qt.PenStyle.NoPen)
        ring = theme.c("accent")
        ring.setAlphaF(0.10 + 0.10 * pulse)
        p.setBrush(ring)
        r = 46 + 6 * pulse
        p.drawEllipse(QPointF(cx, cy), r, r)
        p.setBrush(QColor(255, 255, 255, 18))
        p.drawEllipse(QPointF(cx, cy), 40, 40)
        if self._state == self.STARTING:
            pen = QPen(theme.c("accent2"), 3)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawArc(QRectF(cx - 40, cy - 40, 80, 80), int(-t * 360 * 3 * 16), 90 * 16)
        p.setPen(QColor(255, 255, 255, 230))
        p.setFont(theme.icon_font(24))
        p.drawText(QRectF(cx - 40, cy - 40, 80, 80), Qt.AlignmentFlag.AlignCenter,
                   theme.ICONS["camera"])
        p.setFont(theme.font(14, QFont.Weight.DemiBold))
        p.drawText(QRectF(0, cy + 62, rect.width(), 30), Qt.AlignmentFlag.AlignCenter, self._texts[0])
        p.setPen(QColor(255, 255, 255, 130))
        p.setFont(theme.font(10))
        p.drawText(QRectF(0, cy + 92, rect.width(), 24), Qt.AlignmentFlag.AlignCenter, self._texts[1])

    def _paint_center_text(self, p, rect, icon, title, hint):
        p.setPen(QColor(255, 255, 255, 160))
        p.setFont(theme.icon_font(26))
        p.drawText(QRectF(0, rect.center().y() - 60, rect.width(), 50),
                   Qt.AlignmentFlag.AlignCenter, theme.ICONS[icon])
        p.setFont(theme.font(10.5))
        p.drawText(QRectF(40, rect.center().y(), rect.width() - 80, 60),
                   Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap, title)


# ---------------------------------------------------------------- gaze map ----
class GazeMap(QWidget):
    """Screen-shaped map with a smoothly gliding gaze dot."""

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
        p.setBrush(theme.c("surface2"))
        p.drawRoundedRect(rect, 12, 12)
        p.setPen(QPen(theme.c("border"), 1, Qt.PenStyle.DashLine))
        for i in (1, 2):
            x = rect.left() + rect.width() * i / 3
            y = rect.top() + rect.height() * i / 3
            p.drawLine(QPointF(x, rect.top() + 8), QPointF(x, rect.bottom() - 8))
            p.drawLine(QPointF(rect.left() + 8, y), QPointF(rect.right() - 8, y))
        if self._visible < 0.01:
            return
        x = rect.left() + 10 + (rect.width() - 20) * self._pos.x()
        y = rect.top() + 10 + (rect.height() - 20) * self._pos.y()
        glow = QRadialGradient(QPointF(x, y), 26)
        g = theme.c("accent2")
        g.setAlphaF(0.45 * self._visible)
        glow.setColorAt(0, g)
        glow.setColorAt(1, QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QPointF(x, y), 26, 26)
        dot = theme.c("accent2")
        dot.setAlphaF(self._visible)
        p.setBrush(dot)
        p.drawEllipse(QPointF(x, y), 6, 6)
        p.setBrush(QColor(255, 255, 255, int(255 * self._visible)))
        p.drawEllipse(QPointF(x, y), 2.5, 2.5)


# ------------------------------------------------------------ hand diagram ----
HAND_SOURCE_SIZE = 360
# Finger zones in source pixels, order thumb … pinky.
HAND_FINGER_ZONES = (
    ((30, 135), (112, 135), (112, 275), (30, 275)),
    ((88, 32), (160, 32), (160, 248), (88, 248)),
    ((136, 0), (216, 0), (216, 194), (136, 194)),
    ((192, 15), (273, 15), (273, 194), (192, 194)),
    ((249, 43), (330, 43), (330, 210), (249, 210)),
)
HAND_NUMBER_POINTS = ((70, 158), (124, 55), (178, 15), (232, 38), (286, 67))


def _load_hand_alpha():
    try:
        with Image.open(paths.HAND_REFERENCE_PATH) as src:
            gray = np.asarray(src.convert("L"), dtype=np.int16)
    except (OSError, ValueError):
        logger.exception("Could not load hand reference image")
        img = Image.new("L", (HAND_SOURCE_SIZE, HAND_SOURCE_SIZE), 0)
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle((42, 145, 320, 350), radius=80, outline=255, width=18)
        for box in ((91, 43, 151, 247), (145, 3, 211, 188), (199, 23, 269, 190), (257, 52, 320, 204)):
            draw.rounded_rectangle(box, radius=28, outline=255, width=18)
        return np.asarray(img)
    # Dark outline on a light checkerboard → alpha mask of the outline only.
    return np.clip((190 - gray) * 4, 0, 255).astype(np.uint8)


class HandDiagram(QWidget):
    """Clickable palm outline; raised fingers glow green. Cross-fades on change."""

    fingerToggled = Signal(int)

    def __init__(self, size=300):
        super().__init__()
        self._size = size
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._alpha = _load_hand_alpha()
        self._cache = {}
        self.pattern = (False,) * 5
        self._prev = None
        self._fade = 1.0
        self._pop = [0.0] * 5
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(lambda v: (setattr(self, "_fade", float(v)), self.update()))
        self._pop_timer = QTimer(self)
        self._pop_timer.timeout.connect(self._pop_tick)
        self._hover = -1
        self.setMouseTracking(True)

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

    def clear_cache(self):
        self._cache.clear()
        self.update()

    def _pop_tick(self):
        self._pop = [max(0.0, v - 0.06) for v in self._pop]
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
        zone = Image.new("L", (size, size), 0)
        draw = ImageDraw.Draw(zone)
        for enabled, polygon in zip(pattern, HAND_FINGER_ZONES):
            if enabled:
                draw.polygon(polygon, fill=255)
        selected = np.minimum(self._alpha, np.asarray(zone))
        glow = np.asarray(Image.fromarray(selected).filter(ImageFilter.GaussianBlur(9)), dtype=np.float32)

        green = theme.c("success")
        base = theme.c("faint") if theme.is_dark() else theme.c("muted")
        rgba = np.zeros((size, size, 4), dtype=np.uint8)
        # Glow layer underneath, then the outline on top.
        glow_a = np.clip(glow * 0.8, 0, 170).astype(np.uint8)
        rgba[..., 0], rgba[..., 1], rgba[..., 2] = green.red(), green.green(), green.blue()
        rgba[..., 3] = glow_a
        outline = np.zeros_like(rgba)
        outline[..., 0], outline[..., 1], outline[..., 2] = base.red(), base.green(), base.blue()
        sel = selected > 0
        outline[sel, 0], outline[sel, 1], outline[sel, 2] = green.red(), green.green(), green.blue()
        outline[..., 3] = self._alpha
        img = Image.alpha_composite(Image.fromarray(rgba, "RGBA"), Image.fromarray(outline, "RGBA"))
        px = int(self._size * 0.9 * ratio)
        img = img.resize((px, px), Image.Resampling.LANCZOS)
        data = img.tobytes("raw", "RGBA")
        qimg = QImage(data, px, px, px * 4, QImage.Format.Format_RGBA8888).copy()
        pix = QPixmap.fromImage(qimg)
        pix.setDevicePixelRatio(ratio)
        self._cache[key] = pix
        return pix

    def _geometry(self):
        draw = self._size * 0.9
        offset = (self._size - draw) / 2
        return offset, draw / HAND_SOURCE_SIZE

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

        p.setFont(theme.font(9, QFont.Weight.Bold))
        for i, (sx, sy) in enumerate(HAND_NUMBER_POINTS):
            x, y = offset + sx * scale, offset + sy * scale
            r = 12 + 5 * math.sin(self._pop[i] * math.pi) + (1.5 if i == self._hover else 0)
            on = self.pattern[i]
            p.setPen(QPen(theme.c("surface"), 2))
            p.setBrush(theme.c("success") if on else theme.c("surface3"))
            p.drawEllipse(QPointF(x, y), r, r)
            p.setPen(QColor("#062814") if on else theme.c("text"))
            p.drawText(QRectF(x - r, y - r, 2 * r, 2 * r), Qt.AlignmentFlag.AlignCenter, str(i + 1))


class FingerChips(QWidget):
    """Five compact chips mirroring the diagram (also keyboard/mouse friendly)."""

    fingerToggled = Signal(int)

    def __init__(self, names):
        super().__init__()
        self.names = list(names)
        self.pattern = (False,) * 5
        self.setFixedHeight(34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(theme.font(9, QFont.Weight.DemiBold))

    def set_pattern(self, pattern):
        self.pattern = tuple(pattern)
        self.update()

    def sizeHint(self):
        return QSize(300, 34)

    def _rects(self):
        gap = 6
        w = (self.width() - gap * 4) / 5
        return [QRectF(i * (w + gap), 0, w, self.height()) for i in range(5)]

    def mouseReleaseEvent(self, event):
        for i, r in enumerate(self._rects()):
            if r.contains(event.position()):
                self.fingerToggled.emit(i)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(self.font())
        for i, r in enumerate(self._rects()):
            on = self.pattern[i]
            p.setPen(Qt.PenStyle.NoPen)
            if on:
                bg = theme.c("success")
                bg.setAlphaF(0.18)
                p.setBrush(bg)
            else:
                p.setBrush(theme.c("surface2"))
            p.drawRoundedRect(r, 9, 9)
            p.setPen(theme.c("success") if on else theme.c("muted"))
            text = p.fontMetrics().elidedText(self.names[i], Qt.TextElideMode.ElideRight, int(r.width() - 8))
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
        h = full if on else full * 0.38
        x = size * 0.1 + i * (bw + bw * 0.4)
        p.setBrush(theme.c("success") if on else theme.c("faint"))
        p.drawRoundedRect(QRectF(x, size * 0.9 - h, bw, h), bw / 2, bw / 2)
    p.end()
    return pix

