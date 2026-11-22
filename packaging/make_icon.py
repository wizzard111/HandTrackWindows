"""Generate src/handtrack/assets/icon.png, icon.ico and icon.icns-ready PNG.

Black chamfered tile, red/purple edge glow, white hand outline.
Run after changing the design: python packaging/make_icon.py
"""

import os
import struct

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "src", "handtrack", "assets")
S = 1024


def chamfer_poly(x1, y1, x2, y2, cut):
    return np.array([(x1 + cut, y1), (x2, y1), (x2, y2 - cut), (x2 - cut, y2), (x1, y2), (x1, y1 + cut)],
                    np.int32)


def render():
    img = np.zeros((S, S, 4), np.float32)
    pad, cut = 40, 220
    tile = np.zeros((S, S), np.uint8)
    cv2.fillPoly(tile, [chamfer_poly(pad, pad, S - pad, S - pad, cut)], 255, cv2.LINE_AA)

    # Background: near-black with a purple bloom bottom-left and red top-right.
    yy, xx = np.mgrid[0:S, 0:S].astype(np.float32) / S
    purple = np.exp(-((xx - 0.15) ** 2 + (yy - 0.9) ** 2) / 0.18)[..., None] * np.array((184, 31, 91))
    red = np.exp(-((xx - 0.95) ** 2 + (yy - 0.1) ** 2) / 0.10)[..., None] * np.array((69, 31, 255))
    bg = np.clip(np.array((14, 6, 10)) + purple * 0.55 + red * 0.45, 0, 255)
    img[..., :3] = bg
    img[..., 3] = tile

    # Red edge line along the chamfer.
    edge = np.zeros((S, S), np.uint8)
    cv2.polylines(edge, [chamfer_poly(pad + 14, pad + 14, S - pad - 14, S - pad - 14, cut - 6)], True,
                  255, 10, cv2.LINE_AA)
    e = edge.astype(np.float32)[..., None] / 255
    img[..., :3] = img[..., :3] * (1 - e) + np.array((69, 31, 255)) * e

    # Hand outline from the reference image, thickened, white with a red glow.
    gray = cv2.imdecode(np.fromfile(os.path.join(ASSETS, "hand_reference.png"), np.uint8),
                        cv2.IMREAD_GRAYSCALE)
    hand = np.clip((190 - gray.astype(np.int16)) * 4, 0, 255).astype(np.uint8)
    inner = int(S * 0.62)
    hand = cv2.resize(hand, (inner, inner), interpolation=cv2.INTER_AREA)
    hand = cv2.dilate(hand, np.ones((9, 9), np.uint8))
    layer = np.zeros((S, S), np.uint8)
    o = (S - inner) // 2
    layer[o + 20:o + 20 + inner, o:o + inner] = hand
    glow = cv2.GaussianBlur(layer, (0, 0), 28).astype(np.float32)[..., None] / 255
    img[..., :3] = np.clip(img[..., :3] + glow * np.array((69, 31, 255)) * 1.6, 0, 255)
    a = layer.astype(np.float32)[..., None] / 255
    img[..., :3] = img[..., :3] * (1 - a) + 255 * a
    return np.clip(img, 0, 255).astype(np.uint8)


def png_bytes(bgra, size):
    small = cv2.resize(bgra, (size, size), interpolation=cv2.INTER_AREA)
    ok, data = cv2.imencode(".png", small)
    assert ok
    return data.tobytes()


def write_ico(path, bgra, sizes=(16, 24, 32, 48, 64, 128, 256)):
    """ICO with PNG-compressed entries (supported since Windows Vista)."""
    images = [png_bytes(bgra, s) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries = b""
    for s, data in zip(sizes, images):
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    with open(path, "wb") as f:
        f.write(header + entries + b"".join(images))


def main():
    icon = render()
    with open(os.path.join(ASSETS, "icon.png"), "wb") as f:
        f.write(png_bytes(icon, 256))
    with open(os.path.join(ASSETS, "icon-1024.png"), "wb") as f:   # source for macOS .icns
        f.write(png_bytes(icon, 1024))
    write_ico(os.path.join(ASSETS, "icon.ico"), icon)
    print("icon written")


if __name__ == "__main__":
    main()
