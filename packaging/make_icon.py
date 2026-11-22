"""Generate src/handtrack/assets/icon.png, icon.ico and icon.icns-ready PNG.

Black square tile, grey frame, white hand outline, red corner block.
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
    """Black square tile, 1 px-style frame, white hand outline, red corner block."""
    img = np.zeros((S, S, 4), np.uint8)
    pad = 40
    cv2.rectangle(img, (pad, pad), (S - pad, S - pad), (12, 10, 10, 255), -1)
    cv2.rectangle(img, (pad + 18, pad + 18), (S - pad - 18, S - pad - 18), (70, 64, 62, 255), 8)
    cv2.rectangle(img, (S - pad - 150, pad + 18), (S - pad - 18, pad + 150), (63, 35, 208, 255), -1)

    gray = cv2.imdecode(np.fromfile(os.path.join(ASSETS, "hand_reference.png"), np.uint8),
                        cv2.IMREAD_GRAYSCALE)
    hand = np.clip((190 - gray.astype(np.int16)) * 4, 0, 255).astype(np.uint8)
    inner = int(S * 0.58)
    hand = cv2.resize(hand, (inner, inner), interpolation=cv2.INTER_AREA)
    hand = cv2.dilate(hand, np.ones((9, 9), np.uint8))
    o = (S - inner) // 2
    a = hand.astype(np.float32)[..., None] / 255
    roi = img[o + 30:o + 30 + inner, o:o + inner, :3].astype(np.float32)
    img[o + 30:o + 30 + inner, o:o + inner, :3] = (roi * (1 - a) + 238 * a).astype(np.uint8)
    return img


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
