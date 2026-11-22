import math
import random
from types import SimpleNamespace

import numpy as np
import pytest

from handtrack.vision import geometry as geo
from handtrack.vision import render


def make_hand(seed=0):
    rng = random.Random(seed)
    return [SimpleNamespace(x=rng.random(), y=rng.random(), z=rng.uniform(-0.1, 0.1))
            for _ in range(21)]


def reference_normalize(lm):
    """The v6 implementation; saved templates were produced by it."""
    arr = np.array([(p.x, p.y, p.z) for p in lm], dtype=np.float32)
    centered = arr - arr[0]
    angle = math.atan2(float(centered[9, 1]), float(centered[9, 0]))
    rotation = (-math.pi / 2.0) - angle
    cos_a, sin_a = math.cos(rotation), math.sin(rotation)
    x = centered[:, 0].copy()
    y = centered[:, 1].copy()
    centered[:, 0] = x * cos_a - y * sin_a
    centered[:, 1] = x * sin_a + y * cos_a
    scale = max(np.linalg.norm(centered[9]), 1e-6)
    return (centered / scale).ravel()


@pytest.mark.parametrize("seed", range(20))
def test_normalize_matches_v6(seed):
    lm = make_hand(seed)
    np.testing.assert_allclose(geo.normalize_hand_vector(lm), reference_normalize(lm), atol=1e-5)


def test_normalized_palm_points_up():
    vec = geo.normalize_hand_vector(make_hand(3)).reshape(21, 3)
    assert vec[9, 0] == pytest.approx(0.0, abs=1e-5)
    assert vec[9, 1] < 0


def test_classifier_picks_nearest():
    hands = {n: make_hand(n) for n in range(1, 6)}
    clf = geo.TemplateClassifier({n: geo.normalize_hand_vector(h) for n, h in hands.items()})
    for n, h in hands.items():
        label, dist = clf.classify(h)
        assert label == n
        assert dist == pytest.approx(0.0, abs=1e-5)
    assert not geo.TemplateClassifier()


def test_blend_matches_float_reference():
    rng = np.random.default_rng(1)
    frame = rng.integers(0, 256, (60, 80, 3), dtype=np.uint8)
    sticker = rng.integers(0, 256, (24, 24, 4), dtype=np.uint8)
    cache = render.StickerCache()
    item = cache.get(1, sticker, 24)
    for x, y in ((10, 10), (-8, -5), (70, 50), (100, 100)):
        expected = frame.copy()
        oh, ow = sticker.shape[:2]
        fx1, fy1 = max(0, x), max(0, y)
        fx2, fy2 = min(80, x + ow), min(60, y + oh)
        if fx2 > fx1 and fy2 > fy1:
            crop = sticker[fy1 - y:fy2 - y, fx1 - x:fx2 - x].astype(np.float64)
            a = crop[..., 3:4] / 255.0
            roi = expected[fy1:fy2, fx1:fx2].astype(np.float64)
            expected[fy1:fy2, fx1:fx2] = np.round(crop[..., :3] * a + roi * (1 - a))
        actual = frame.copy()
        render.blend_premultiplied(actual, item, x, y)
        assert np.abs(actual.astype(int) - expected.astype(int)).max() <= 1


def test_finger_states_open_hand():
    # Straight vertical hand: wrist at bottom, fingers pointing up.
    pts = [(0.5, 0.9)] * 21
    pts = list(pts)
    pts[17] = (0.62, 0.7)
    pts[2], pts[3], pts[4] = (0.40, 0.75), (0.34, 0.70), (0.28, 0.66)
    for base_x, (mcp, pip, dip, tip) in zip((0.44, 0.5, 0.56, 0.62),
                                            ((5, 6, 7, 8), (9, 10, 11, 12),
                                             (13, 14, 15, 16), (17, 18, 19, 20))):
        pts[mcp] = (base_x, 0.7)
        pts[pip] = (base_x, 0.6)
        pts[dip] = (base_x, 0.5)
        pts[tip] = (base_x, 0.4)
    lm = [SimpleNamespace(x=x, y=y, z=0.0) for x, y in pts]
    assert geo.get_finger_states(lm) == (True,) * 5


def test_drawing_fades_from_the_tail():
    d = render.Drawing()
    d.lifetime = 10.0
    d.add("Right", (0.1, 0.1), 200, 200, now=0.0)
    d.add("Right", (0.15, 0.15), 200, 200, now=1.0)
    d.add("Right", (0.2, 0.2), 200, 200, now=2.0)
    frame = np.zeros((200, 200, 3), np.uint8)
    d.render(frame, now=2.5)
    assert frame.any()
    d.render(np.zeros_like(frame), now=10.5)       # first point expired, rest still there
    assert d.strokes and len(d.strokes[0][3]) == 2
    d.render(np.zeros_like(frame), now=100.0)
    assert not d.strokes


def test_drawing_jump_starts_new_stroke():
    d = render.Drawing()
    d.add("Right", (0.1, 0.1), 400, 400, now=0.0)
    d.add("Right", (0.9, 0.9), 400, 400, now=0.03)
    assert len(d.strokes) == 2


def test_drawing_forever_and_clear():
    d = render.Drawing()
    d.lifetime = 0
    d.add("Right", (0.5, 0.5), 100, 100, now=0.0)
    d.render(np.zeros((100, 100, 3), np.uint8), now=1e6)
    assert d.strokes
    d.clear()
    assert not d.strokes


def test_pinch_hysteresis():
    def hand(gap):
        pts = [SimpleNamespace(x=0.5, y=0.5, z=0.0) for _ in range(21)]
        pts[0] = SimpleNamespace(x=0.5, y=0.9, z=0.0)
        pts[9] = SimpleNamespace(x=0.5, y=0.6, z=0.0)        # palm length 0.3
        pts[4] = SimpleNamespace(x=0.5, y=0.4, z=0.0)
        pts[8] = SimpleNamespace(x=0.5 + gap, y=0.4, z=0.0)
        return pts
    gap = 0.3 * 0.38                                         # between ON (0.30) and OFF (0.45)
    assert geo.is_pinching(hand(gap), was_pinching=False)[0] is False
    assert geo.is_pinching(hand(gap), was_pinching=True)[0] is True
    assert geo.is_pinching(hand(0.3 * 0.2))[0] is True
