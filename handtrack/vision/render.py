"""Everything drawn onto the outgoing video frame."""

import logging
import math
import os
from collections import OrderedDict

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from handtrack import paths
from handtrack.vision.geometry import EYE_VIZ_POINTS, FACE_MASK_ANCHOR_IDX, HAND_CONNECTIONS

logger = logging.getLogger("handtrack")

STICKER_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
PLACEHOLDER_COLORS_RGB = {
    1: (255, 99, 132), 2: (255, 159, 64), 3: (255, 205, 86),
    4: (75, 192, 120), 5: (90, 120, 255),
}

SKELETON_COLOR = (120, 255, 170)   # BGR, soft mint
JOINT_COLOR = (255, 255, 255)
DRAW_COLOR_BGR = (80, 60, 255)
DRAW_FADE_SECONDS = 10.0
DRAW_MIN_POINT_DISTANCE2 = 3 ** 2

STICKER_SIZE_BUCKET = 8
STICKER_ANGLE_BUCKET = 5
STICKER_CACHE_SIZE = 192


# ---------------------------------------------------------------- stickers ----
def _load_font(size):
    for name in ("segoeuib.ttf", "arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make_placeholder_sticker(n, size=400):
    color = PLACEHOLDER_COLORS_RGB.get(n, (200, 200, 200))
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = 12
    draw.ellipse([pad, pad, size - pad, size - pad], fill=color + (235,),
                 outline=(255, 255, 255, 255), width=10)
    font = _load_font(size // 2)
    text = str(n)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1]),
              text, fill=(255, 255, 255, 255), font=font)
    return cv2.cvtColor(np.asarray(img), cv2.COLOR_RGBA2BGRA)


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


def load_sticker_images():
    """Return ({n: BGRA array}, {n: is_custom}) for n = 1..5."""
    stickers, custom = {}, {}
    for n in range(1, 6):
        path = find_sticker_file(n)
        image = None
        if path:
            try:
                with Image.open(path) as src:
                    image = cv2.cvtColor(np.asarray(src.convert("RGBA")), cv2.COLOR_RGBA2BGRA)
            except (OSError, ValueError):
                logger.warning("Could not load sticker %s", path, exc_info=True)
        custom[n] = image is not None
        stickers[n] = image if image is not None else make_placeholder_sticker(n)
    return stickers, custom


class StickerCache:
    """LRU cache of resized/rotated stickers, stored ready for blending.

    Each entry keeps the colour premultiplied by alpha and the inverse alpha,
    both as uint16, so the per-frame blend is one multiply-add per pixel
    instead of four float conversions.
    """

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
    blend_premultiplied(frame, item, int((ox + rx) / 2) - size // 2,
                        int((oy + ry) / 2) - size // 2)


# ---------------------------------------------------------------- overlays ----
def draw_hand_skeleton(frame, lm, w, h):
    pts = np.array([(p.x * w, p.y * h) for p in lm], dtype=np.int32)
    lines = [pts[[a, b]] for a, b in HAND_CONNECTIONS]
    cv2.polylines(frame, lines, False, SKELETON_COLOR, 2, cv2.LINE_AA)
    for x, y in pts:
        cv2.circle(frame, (int(x), int(y)), 3, JOINT_COLOR, -1, cv2.LINE_AA)


def draw_eye_points(frame, face_landmarks, w, h):
    for index in EYE_VIZ_POINTS:
        p = face_landmarks[index]
        cv2.circle(frame, (int(p.x * w), int(p.y * h)), 2, SKELETON_COLOR, -1, cv2.LINE_AA)


def draw_corner_counter(frame, text):
    h = frame.shape[0]
    x, y = 16, h - 18
    cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (0, 0, 0), 6, cv2.LINE_AA)
    cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (255, 255, 255), 2, cv2.LINE_AA)


def face_box(face_landmarks, w, h):
    xs = [face_landmarks[i].x for i in FACE_MASK_ANCHOR_IDX]
    ys = [face_landmarks[i].y for i in FACE_MASK_ANCHOR_IDX]
    left, right = min(xs) * w, max(xs) * w
    top, bottom = min(ys) * h, max(ys) * h
    pad_x = int((right - left) * 0.2) + 15
    pad_y = int((bottom - top) * 0.2) + 15
    return (max(0, int(left - pad_x)), max(0, int(top - pad_y)),
            min(w, int(right + pad_x)), min(h, int(bottom + pad_y)))


def draw_afk(frame, title, subtitle):
    h, w = frame.shape[:2]
    frame[:] = (24, 18, 20)
    (tw, th), _ = cv2.getTextSize(title, cv2.FONT_HERSHEY_DUPLEX, 2.4, 4)
    cv2.putText(frame, title, ((w - tw) // 2, (h + th) // 2), cv2.FONT_HERSHEY_DUPLEX,
                2.4, (255, 255, 255), 4, cv2.LINE_AA)
    (sw, sh), _ = cv2.getTextSize(subtitle, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
    cv2.putText(frame, subtitle, ((w - sw) // 2, (h + th) // 2 + sh + 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (170, 170, 180), 2, cv2.LINE_AA)


class Drawing:
    """Pinch-drawn strokes, one deque of points per hand, fading over time."""

    def __init__(self):
        self.strokes = {}     # hand key -> list of [points, last_time]
        self._pinching = {}

    def clear(self):
        self.strokes.clear()
        self._pinching.clear()

    def release(self, hand_key=None):
        if hand_key is None:
            self._pinching.clear()
        else:
            self._pinching.pop(hand_key, None)

    def add(self, hand_key, midpoint, w, h, now):
        x, y = int(midpoint[0] * w), int(midpoint[1] * h)
        strokes = self.strokes.setdefault(hand_key, [])
        if not self._pinching.get(hand_key) or not strokes:
            strokes.append([[(x, y)], [now]])
        else:
            points, times = strokes[-1]
            lx, ly = points[-1]
            if (x - lx) ** 2 + (y - ly) ** 2 >= DRAW_MIN_POINT_DISTANCE2:
                points.append((x, y))
                times.append(now)
        self._pinching[hand_key] = True

    def render(self, frame, now):
        cutoff = now - DRAW_FADE_SECONDS
        for hand_key in list(self.strokes):
            strokes = self.strokes[hand_key]
            kept = []
            for points, times in strokes:
                drop = 0
                while drop < len(times) and times[drop] < cutoff:
                    drop += 1
                if drop:
                    del points[:drop], times[:drop]
                if points:
                    kept.append([points, times])
            if not kept:
                del self.strokes[hand_key]
                continue
            self.strokes[hand_key] = kept
            for points, _times in kept:
                if len(points) == 1:
                    cv2.circle(frame, points[0], 4, DRAW_COLOR_BGR, -1, cv2.LINE_AA)
                else:
                    cv2.polylines(frame, [np.array(points, dtype=np.int32)], False,
                                  DRAW_COLOR_BGR, 6, cv2.LINE_AA)
