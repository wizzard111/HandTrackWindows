"""Everything drawn onto the outgoing video frame (OpenCV only, no Pillow)."""

import logging
import math
import os
from collections import OrderedDict

import cv2
import numpy as np

from handtrack import paths
from handtrack.vision.geometry import EYE_VIZ_POINTS, FACE_MASK_ANCHOR_IDX, HAND_CONNECTIONS

logger = logging.getLogger("handtrack")

STICKER_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
SKELETON_COLOR = (34, 30, 150)     # BGR dark red
JOINT_COLOR = (196, 202, 208)      # worn off-white
STICKER_SIZE_BUCKET = 8
STICKER_ANGLE_BUCKET = 5
STICKER_CACHE_SIZE = 192

# Drawing colours (BGR): dried red, worn white, muddy purple, slate, rust.
DRAW_COLORS = ((34, 30, 150), (196, 202, 208), (95, 55, 110), (120, 110, 100), (40, 85, 150))


# ---------------------------------------------------------------- stickers ----
def make_placeholder_sticker(n, size=400):
    """Black disc, red ring, white digit."""
    img = np.zeros((size, size, 4), np.uint8)
    c = size // 2
    cv2.circle(img, (c, c), c - 10, (16, 10, 14, 235), -1, cv2.LINE_AA)
    cv2.circle(img, (c, c), c - 14, (34, 30, 150, 255), 14, cv2.LINE_AA)
    text = str(n)
    scale = size / 90
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_DUPLEX, scale, 12)
    cv2.putText(img, text, (c - tw // 2, c + th // 2), cv2.FONT_HERSHEY_DUPLEX, scale,
                (255, 255, 255, 255), 12, cv2.LINE_AA)
    return img


def find_sticker_file(n):
    try:
        names = os.listdir(paths.IMAGES_DIR)
    except OSError:
        return None
    target = f"gesture_{n}"
    for name in names:
        stem, ext = os.path.splitext(name)
        if stem.lower() == target and ext.lower() in STICKER_EXTENSIONS:
            return os.path.join(paths.IMAGES_DIR, name)
    return None


def read_bgra(path):
    """Read any supported image as BGRA; works with non-ASCII paths."""
    data = np.fromfile(path, dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError(f"unreadable image: {path}")
    if img.dtype != np.uint8:
        img = (img / 256).astype(np.uint8)
    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    if img.shape[2] == 3:
        return cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    return img


def load_sticker_images():
    """Return ({n: BGRA array}, {n: is_custom}) for n = 1..5."""
    stickers, custom = {}, {}
    for n in range(1, 6):
        path = find_sticker_file(n)
        image = None
        if path:
            try:
                image = read_bgra(path)
            except (OSError, ValueError):
                logger.warning("Could not load sticker %s", path, exc_info=True)
        custom[n] = image is not None
        stickers[n] = image if image is not None else make_placeholder_sticker(n)
    return stickers, custom


class StickerCache:
    """LRU cache of resized/rotated stickers, stored ready for blending
    (colour premultiplied by alpha and the inverse alpha, both uint16)."""

    def __init__(self, max_items=STICKER_CACHE_SIZE):
        self.max_items = max_items
        self._items = OrderedDict()

    def clear(self):
        self._items.clear()

    def get(self, sticker_id, source_bgra, size, angle_deg=None):
        size = max(20, int(round(size / STICKER_SIZE_BUCKET) * STICKER_SIZE_BUCKET))
        angle = None if angle_deg is None else int(round(angle_deg / STICKER_ANGLE_BUCKET)
                                                   * STICKER_ANGLE_BUCKET) % 360
        key = (sticker_id, size, angle)
        item = self._items.get(key)
        if item is not None:
            self._items.move_to_end(key)
            return item
        img = cv2.resize(source_bgra, (size, size), interpolation=cv2.INTER_AREA)
        if angle:
            matrix = cv2.getRotationMatrix2D((size / 2, size / 2), angle, 1.0)
            img = cv2.warpAffine(img, matrix, (size, size), flags=cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
        alpha = img[:, :, 3:4].astype(np.uint16)
        item = (img[:, :, :3].astype(np.uint16) * alpha, 255 - alpha)
        self._items[key] = item
        if len(self._items) > self.max_items:
            self._items.popitem(last=False)
        return item


def blend_premultiplied(frame, item, x1, y1):
    premul, inv_alpha = item
    h_f, w_f = frame.shape[:2]
    oh, ow = inv_alpha.shape[:2]
    ox1, oy1 = max(0, -x1), max(0, -y1)
    fx1, fy1 = max(0, x1), max(0, y1)
    fx2, fy2 = min(w_f, x1 + ow), min(h_f, y1 + oh)
    w, h = fx2 - fx1, fy2 - fy1
    if w <= 0 or h <= 0:
        return
    roi = frame[fy1:fy2, fx1:fx2]
    blended = roi * inv_alpha[oy1:oy1 + h, ox1:ox1 + w] + premul[oy1:oy1 + h, ox1:ox1 + w]
    # x / 255 ≈ (x + 128 + (x >> 8)) >> 8, exact for 0..65025.
    blended += 128
    blended += blended >> 8
    roi[:] = blended >> 8


def overlay_sticker_on_hand(frame, lm, cache, sticker_id, sticker_bgra,
                            scale_factor=1.3, rotate=True):
    h, w = frame.shape[:2]
    ox, oy = lm[0].x * w, lm[0].y * h
    rx, ry = lm[9].x * w, lm[9].y * h
    vx, vy = rx - ox, ry - oy
    dist = math.hypot(vx, vy)
    if dist < 2:
        return
    angle = -(math.degrees(math.atan2(vy, vx)) + 90) if rotate else None
    item = cache.get(sticker_id, sticker_bgra, max(20, int(dist * scale_factor)), angle)
    size = item[1].shape[0]
    blend_premultiplied(frame, item, int((ox + rx) / 2) - size // 2, int((oy + ry) / 2) - size // 2)


# ---------------------------------------------------------------- overlays ----
def draw_hand_skeleton(frame, lm, w, h):
    pts = np.array([(p.x * w, p.y * h) for p in lm], dtype=np.int32)
    cv2.polylines(frame, [pts[[a, b]] for a, b in HAND_CONNECTIONS], False, SKELETON_COLOR, 2, cv2.LINE_AA)
    for x, y in pts:
        cv2.rectangle(frame, (int(x) - 2, int(y) - 2), (int(x) + 2, int(y) + 2), JOINT_COLOR, -1)


def draw_eye_points(frame, face_landmarks, w, h):
    for index in EYE_VIZ_POINTS:
        p = face_landmarks[index]
        cv2.circle(frame, (int(p.x * w), int(p.y * h)), 2, SKELETON_COLOR, -1, cv2.LINE_AA)


def draw_corner_counter(frame, text):
    h = frame.shape[0]
    x, y = 16, h - 18
    cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_DUPLEX, 1.3, (0, 0, 0), 6, cv2.LINE_AA)
    cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_DUPLEX, 1.3, (255, 255, 255), 2, cv2.LINE_AA)


def face_box(face_landmarks, w, h):
    xs = [face_landmarks[i].x for i in FACE_MASK_ANCHOR_IDX]
    ys = [face_landmarks[i].y for i in FACE_MASK_ANCHOR_IDX]
    left, right = min(xs) * w, max(xs) * w
    top, bottom = min(ys) * h, max(ys) * h
    pad_x = int((right - left) * 0.2) + 15
    pad_y = int((bottom - top) * 0.2) + 15
    return (max(0, int(left - pad_x)), max(0, int(top - pad_y)),
            min(w, int(right + pad_x)), min(h, int(bottom + pad_y)))


_SHIELD = np.array([(0.0, -1.0), (0.82, -0.68), (0.72, 0.25), (0.0, 1.0), (-0.72, 0.25), (-0.82, -0.68)])


def draw_privacy_mask(frame, box):
    """Black box with a red shield, so the other side sees it is intentional."""
    x1, y1, x2, y2 = box
    frame[y1:y2, x1:x2] = 0
    w, h = x2 - x1, y2 - y1
    if w < 40 or h < 40:
        return
    r = min(w, h) * 0.22
    cx, cy = x1 + w / 2, y1 + h / 2
    pts = (_SHIELD * r + (cx, cy)).astype(np.int32)
    cv2.polylines(frame, [pts], True, (34, 30, 150), max(2, int(r / 9)), cv2.LINE_AA)


def draw_afk(frame, title, subtitle):
    h, w = frame.shape[:2]
    frame[:] = (12, 6, 10)
    # Diagonal hazard stripes in deep purple.
    step = max(24, w // 24)
    for x in range(-h, w, step * 2):
        cv2.line(frame, (x, h), (x + h, 0), (24, 18, 22), step // 2)
    (tw, th), _ = cv2.getTextSize(title, cv2.FONT_HERSHEY_DUPLEX, 3.0, 6)
    org = ((w - tw) // 2, (h + th) // 2)
    cv2.putText(frame, title, org, cv2.FONT_HERSHEY_DUPLEX, 3.0, (34, 30, 150), 6, cv2.LINE_AA)
    (sw, sh), _ = cv2.getTextSize(subtitle, cv2.FONT_HERSHEY_SIMPLEX, 0.85, 2)
    cv2.putText(frame, subtitle, ((w - sw) // 2, org[1] + sh + 26), cv2.FONT_HERSHEY_SIMPLEX,
                0.85, (180, 186, 192), 2, cv2.LINE_AA)


# ----------------------------------------------------------------- drawing ----
class Drawing:
    """Pinch-drawn neon strokes.

    * the pinch point is smoothed with an adaptive low-pass filter (steady
      when slow, responsive when fast), so lines do not wobble;
    * a big jump starts a new stroke instead of drawing a line across the frame;
    * points age out from the tail; the last FADE_TAIL seconds fade smoothly;
    * glow is a blurred, additive copy of the strokes.
    """

    FADE_TAIL = 1.2
    JUMP_FRACTION = 0.18
    MIN_STEP2 = 2.5 ** 2

    def __init__(self):
        self.strokes = []          # [hand_key, color, thickness, points[], times[]]
        self._active = {}          # hand_key -> stroke being drawn
        self._smooth = {}          # hand_key -> (x, y, t)
        self.color = DRAW_COLORS[0]
        self.thickness = 6
        self.lifetime = 10.0       # seconds; 0 = keep until cleared
        self.glow = False

    def clear(self):
        self.strokes.clear()
        self._active.clear()
        self._smooth.clear()

    def release(self, hand_key=None):
        if hand_key is None:
            self._active.clear()
            self._smooth.clear()
        else:
            self._active.pop(hand_key, None)
            self._smooth.pop(hand_key, None)

    def active_keys(self):
        return list(self._active)

    def _filter(self, hand_key, x, y, now):
        prev = self._smooth.get(hand_key)
        if prev is None:
            self._smooth[hand_key] = (x, y, now)
            return x, y
        px, py, pt = prev
        dt = max(1e-3, now - pt)
        speed = math.hypot(x - px, y - py) / dt          # px / s
        alpha = min(1.0, 0.25 + speed / 2500.0)          # slow → smooth, fast → follow
        sx, sy = px + (x - px) * alpha, py + (y - py) * alpha
        self._smooth[hand_key] = (sx, sy, now)
        return sx, sy

    def add(self, hand_key, midpoint, w, h, now):
        x, y = midpoint[0] * w, midpoint[1] * h
        stroke = self._active.get(hand_key)
        if stroke is not None:
            lx, ly = stroke[3][-1]
            if math.hypot(x - lx, y - ly) > self.JUMP_FRACTION * math.hypot(w, h):
                stroke = None
                self._smooth.pop(hand_key, None)
        sx, sy = self._filter(hand_key, x, y, now)
        point = (int(round(sx)), int(round(sy)))
        if stroke is None:
            stroke = [hand_key, self.color, self.thickness, [point], [now]]
            self.strokes.append(stroke)
            self._active[hand_key] = stroke
            return
        lx, ly = stroke[3][-1]
        if (point[0] - lx) ** 2 + (point[1] - ly) ** 2 >= self.MIN_STEP2:
            stroke[3].append(point)
            stroke[4].append(now)

    def _expire(self, now):
        if self.lifetime <= 0:
            return
        cutoff = now - self.lifetime
        kept = []
        for stroke in self.strokes:
            times = stroke[4]
            drop = 0
            while drop < len(times) and times[drop] < cutoff:
                drop += 1
            if drop:
                del stroke[3][:drop], times[:drop]
            if stroke[3]:
                kept.append(stroke)
            elif self._active.get(stroke[0]) is stroke:
                del self._active[stroke[0]]
        self.strokes = kept

    def _alpha(self, t, now):
        if self.lifetime <= 0:
            return 1.0
        return max(0.0, min(1.0, (self.lifetime - (now - t)) / self.FADE_TAIL))

    GLOW_SCALE = 4   # glow is blurred at 1/4 resolution: ~16x cheaper, looks the same

    def _runs(self, now):
        """Yield (points int32 array, colour, thickness, alpha) per drawable run.

        Fully opaque stretches come out as one polyline; only the fading tail
        is split into single segments."""
        for _key, color, thick, points, times in self.strokes:
            pts = np.asarray(points, np.int32)
            if len(pts) == 1:
                yield pts, color, thick, self._alpha(times[0], now)
                continue
            start = 0
            while start < len(pts) - 1:
                a = self._alpha(times[start], now)
                end = start + 1
                if a >= 1.0:
                    while end < len(pts) - 1 and self._alpha(times[end], now) >= 1.0:
                        end += 1
                yield pts[start:end + 1], color, thick, a
                start = end

    def render(self, frame, now):
        self._expire(now)
        if not self.strokes:
            return
        runs = [r for r in self._runs(now) if r[3] > 0.02]
        if self.glow:
            self._render_glow(frame, runs)
        # The fading tail tapers away (narrower line) instead of being alpha
        # blended: no per-pixel work, and it reads as a dissolving trail.
        for pts, color, thick, a in runs:
            width = max(1, int(round(thick * (a if a < 1 else 1.0))))
            if len(pts) == 1:
                cv2.circle(frame, tuple(int(v) for v in pts[0]), max(1, width // 2 + 1), color, -1, cv2.LINE_AA)
            else:
                cv2.polylines(frame, [pts], False, color, width, cv2.LINE_AA)
            if self.glow and width >= 3:   # white-hot centre: reads as neon
                hot = tuple(min(255, c + (255 - c) * 0.7) for c in color)
                cv2.polylines(frame, [pts], False, hot, max(1, width // 3), cv2.LINE_AA)

    def _render_glow(self, frame, runs):
        fh, fw = frame.shape[:2]
        s = self.GLOW_SCALE
        pad = self.thickness * 6
        allpts = np.concatenate([r[0] for r in runs])
        x1, y1 = (np.maximum(allpts.min(axis=0) - pad, 0) // s) * s
        x2, y2 = np.minimum(allpts.max(axis=0) + pad, (fw - 1, fh - 1))
        w, h = (x2 - x1) // s + 1, (y2 - y1) // s + 1
        if w < 2 or h < 2:
            return
        small = np.zeros((h, w, 3), np.uint8)
        offset = np.array((x1, y1), np.int32)
        for pts, color, thick, a in runs:
            sp = (pts - offset) // s
            c = tuple(int(v * min(1.0, a)) for v in color)
            width = max(1, int(thick * 1.8 / s))
            if len(sp) == 1:
                cv2.circle(small, tuple(int(v) for v in sp[0]), width, c, -1)
            else:
                cv2.polylines(small, [sp], False, c, width)
        cv2.GaussianBlur(small, (0, 0), max(1.0, self.thickness * 1.4 / s), dst=small)
        glow = cv2.resize(small, (w * s, h * s), interpolation=cv2.INTER_LINEAR)
        rh, rw = min(glow.shape[0], fh - y1), min(glow.shape[1], fw - x1)
        roi = frame[y1:y1 + rh, x1:x1 + rw]
        cv2.add(roi, glow[:rh, :rw], dst=roi)
        cv2.add(roi, glow[:rh, :rw], dst=roi)
