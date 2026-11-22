import time

import numpy as np

from handtrack.config import Settings
from handtrack.engine import Engine


def _run_one_frame(engine):
    frame = np.zeros((360, 640, 3), np.uint8)
    state = {"frame_id": 0, "hand_used": -1, "face_used": -1, "hand_submit": 0.0,
             "face_submit": 0.0, "face_seen": time.monotonic(), "last_pattern": None,
             "primary_key": None, "triggers": {}, "fps_t": time.monotonic(), "fps_n": 0,
             "fps": 0.0, "stats_t": 0.0, "announced": True}
    sent, shown = [], []
    engine._update_vcam = lambda f, w, h: sent.append(f.copy())
    engine.frame_ready.connect(lambda f: shown.append(f.copy()))
    engine.preview_size = (640, 360)          # no resize: preview starts as the same array
    engine._process(frame, state)
    return sent[0], shown[0]


def test_finger_counter_is_drawn_on_the_preview_only():
    settings = Settings(show_counter=True, preview_visible=True, hide_face=False, gaze=False,
                        afk_enabled=False, draw_enabled=False, vcam=True)
    sent, shown = _run_one_frame(Engine(settings))
    corner = (slice(300, 360), slice(0, 80))   # bottom-left, where the counter goes
    assert sent[corner].max() == 0, "the counter leaked into the virtual camera"
    assert shown[corner].max() > 0, "the preview should show the counter"
