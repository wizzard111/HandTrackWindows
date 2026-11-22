"""Generate assets/icon.png and assets/icon.ico from the hand outline.

Run once after changing the design: python tools/make_icon.py
"""

import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
SIZE = 512


def gradient(size, c1, c2):
    t = np.linspace(0, 1, size, dtype=np.float32)
    tt = (t[None, :] + t[:, None]) / 2
    arr = np.zeros((size, size, 4), dtype=np.uint8)
    for i in range(3):
        arr[..., i] = (c1[i] + (c2[i] - c1[i]) * tt).astype(np.uint8)
    arr[..., 3] = 255
    return Image.fromarray(arr, "RGBA")


def main():
    bg = gradient(SIZE, (139, 108, 255), (34, 211, 238))
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, SIZE - 1, SIZE - 1), radius=120, fill=255)
    icon = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    icon.paste(bg, (0, 0), mask)

    with Image.open(os.path.join(ASSETS, "hand_reference.png")) as src:
        gray = np.asarray(src.convert("L"), dtype=np.int16)
    alpha = np.clip((190 - gray) * 4, 0, 255).astype(np.uint8)
    hand = Image.fromarray(alpha, "L")
    inner = int(SIZE * 0.66)
    hand = hand.resize((inner, inner), Image.Resampling.LANCZOS)
    # Thicken the outline so it survives at 16 px.
    hand = hand.filter(ImageFilter.MaxFilter(5))
    white = Image.new("RGBA", (inner, inner), (255, 255, 255, 255))
    shadow = Image.new("RGBA", (inner, inner), (20, 10, 60, 90))
    offset = ((SIZE - inner) // 2, (SIZE - inner) // 2 + 8)
    icon.paste(shadow, (offset[0], offset[1] + 10), hand.filter(ImageFilter.GaussianBlur(10)))
    icon.paste(white, offset, hand)

    icon.resize((256, 256), Image.Resampling.LANCZOS).save(os.path.join(ASSETS, "icon.png"))
    icon.save(os.path.join(ASSETS, "icon.ico"),
              sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("icon written")


if __name__ == "__main__":
    main()
