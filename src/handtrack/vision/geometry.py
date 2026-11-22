"""Landmark math: finger states, pinch, hand templates and eye ratios.

For a handful of scalar operations plain Python beats numpy (no array
allocation per call), so the per-frame hot paths below stay scalar and only
the 21-point template comparison is vectorised.
"""

import math

import numpy as np

FINGER_TIPS = (4, 8, 12, 16, 20)
FINGER_PIPS = (3, 6, 10, 14, 18)

HAND_CONNECTIONS = (
    (0, 1), (0, 5), (9, 13), (13, 17), (5, 9), (0, 17),
    (1, 2), (2, 3), (3, 4),
    (5, 6), (6, 7), (7, 8),
    (9, 10), (10, 11), (11, 12),
    (13, 14), (14, 15), (15, 16),
    (17, 18), (18, 19), (19, 20),
)

# Fraction of palm length (wrist -> middle MCP). Two thresholds (hysteresis):
# a pinch starts below PINCH_ON and only ends above PINCH_OFF, so jitter
# around a single threshold no longer breaks a stroke into pieces.
PINCH_ON = 0.30
PINCH_OFF = 0.45
_FINGER_THRESH2 = 1.05 ** 2

# Eye / iris indices of the 478-point FaceLandmarker mesh.
LEFT_EYE = (468, 33, 133, 159, 145)    # iris, corner L, corner R, lid top, lid bottom
RIGHT_EYE = (473, 362, 263, 386, 374)
EYE_VIZ_POINTS = LEFT_EYE + RIGHT_EYE

# Stable anchors for the privacy box: forehead, chin, cheeks, nose, mouth.
FACE_MASK_ANCHOR_IDX = (10, 152, 234, 454, 1, 4, 168, 61, 291, 13, 14, 50, 280)


def _dist2(ax, ay, bx, by):
    dx, dy = ax - bx, ay - by
    return dx * dx + dy * dy


def get_finger_states(lm):
    """Five booleans (thumb … pinky), True when the finger is extended.

    Each finger compares tip-to-anchor with joint-to-anchor distance, which
    is invariant to how the hand is rotated in the frame.
    """
    wx, wy = lm[0].x, lm[0].y
    pkx, pky = lm[17].x, lm[17].y
    # The thumb bends sideways, so measure against the pinky base.
    states = [_dist2(lm[4].x, lm[4].y, pkx, pky)
              > _dist2(lm[2].x, lm[2].y, pkx, pky) * _FINGER_THRESH2]
    for tip, pip in zip(FINGER_TIPS[1:], FINGER_PIPS[1:]):
        t, p = lm[tip], lm[pip]
        states.append(_dist2(t.x, t.y, wx, wy) > _dist2(p.x, p.y, wx, wy) * _FINGER_THRESH2)
    return tuple(states)


def is_pinching(lm, was_pinching=False):
    """Return (pinching, midpoint) for thumb tip + index tip."""
    thumb, index = lm[4], lm[8]
    scale2 = _dist2(lm[9].x, lm[9].y, lm[0].x, lm[0].y)
    if scale2 < 1e-12:
        return False, None
    mid = ((thumb.x + index.x) * 0.5, (thumb.y + index.y) * 0.5)
    limit = PINCH_OFF if was_pinching else PINCH_ON
    pinching = _dist2(thumb.x, thumb.y, index.x, index.y) < limit * limit * scale2
    return pinching, mid


def normalize_hand_vector(lm):
    """Normalise 21 points by position, scale and rotation (palm points up)."""
    arr = np.fromiter((c for p in lm for c in (p.x, p.y, p.z)),
                      dtype=np.float32, count=63).reshape(21, 3)
    arr -= arr[0]
    rotation = -math.pi / 2.0 - math.atan2(float(arr[9, 1]), float(arr[9, 0]))
    cos_a, sin_a = math.cos(rotation), math.sin(rotation)
    xy = arr[:, :2] @ np.array([[cos_a, sin_a], [-sin_a, cos_a]], dtype=np.float32)
    arr[:, :2] = xy
    scale = max(float(np.linalg.norm(arr[9])), 1e-6)
    return (arr / scale).ravel()


class TemplateClassifier:
    """Nearest-template matcher with the templates stacked into one matrix."""

    def __init__(self, templates=None):
        self.set_templates(templates or {})

    def set_templates(self, templates):
        self.templates = dict(templates)
        if self.templates:
            self._labels = np.array(sorted(self.templates), dtype=np.int32)
            self._matrix = np.stack([self.templates[n] for n in self._labels]).astype(np.float32)
        else:
            self._labels = self._matrix = None

    def __bool__(self):
        return self._matrix is not None

    def classify(self, lm):
        if self._matrix is None:
            return None, None
        distances = np.linalg.norm(self._matrix - normalize_hand_vector(lm), axis=1)
        best = int(np.argmin(distances))
        return int(self._labels[best]), float(distances[best])


def eye_ratio(landmarks, idx):
    iris_i, left_i, right_i, top_i, bottom_i = idx
    iris, left, right = landmarks[iris_i], landmarks[left_i], landmarks[right_i]
    top, bottom = landmarks[top_i], landmarks[bottom_i]
    h_span = right.x - left.x
    v_span = bottom.y - top.y
    h = (iris.x - left.x) / h_span if abs(h_span) > 1e-6 else 0.5
    v = (iris.y - top.y) / v_span if abs(v_span) > 1e-6 else 0.5
    return min(max(h, 0.0), 1.0), min(max(v, 0.0), 1.0)


def gaze_features(face_landmarks):
    left_h, left_v = eye_ratio(face_landmarks, LEFT_EYE)
    right_h, right_v = eye_ratio(face_landmarks, RIGHT_EYE)
    return (left_h, left_v, right_h, right_v)


def fit_gaze(features, targets):
    """Least-squares linear map from eye features to screen coordinates."""
    a = np.hstack([np.asarray(features, dtype=np.float64),
                   np.ones((len(features), 1))])
    t = np.asarray(targets, dtype=np.float64)
    coeffs_x, *_ = np.linalg.lstsq(a, t[:, 0], rcond=None)
    coeffs_y, *_ = np.linalg.lstsq(a, t[:, 1], rcond=None)
    return coeffs_x.tolist(), coeffs_y.tolist()


def predict_gaze(coeffs, features):
    coeffs_x, coeffs_y = coeffs
    vec = (*features, 1.0)
    return (sum(c * v for c, v in zip(coeffs_x, vec)),
            sum(c * v for c, v in zip(coeffs_y, vec)))
