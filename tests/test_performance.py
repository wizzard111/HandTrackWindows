"""Guards for the resource-saving behaviour."""
import os

import numpy as np

import handtrack
from handtrack import engine as engine_mod
from handtrack import sound
from handtrack.config import Settings
from handtrack.engine import Engine
from handtrack.vision import render


def test_openblas_is_limited_to_one_thread():
    assert handtrack and os.environ.get("OPENBLAS_NUM_THREADS") == "1"


def test_afk_screen_is_built_once_and_copied():
    render._AFK_CACHE.clear()
    a = np.full((180, 320, 3), 77, np.uint8)
    b = np.full((180, 320, 3), 33, np.uint8)
    render.draw_afk(a, "AFK", "away")
    render.draw_afk(b, "AFK", "away")
    assert len(render._AFK_CACHE) == 1
    assert np.array_equal(a, b)            # same picture, whatever was there before
    assert a.max() > 200                   # white title drawn


def _intervals(engine, st, t):
    return engine._detection_intervals(st, t)


def test_detection_slows_down_on_an_empty_scene_and_recovers():
    e = Engine(Settings(hide_face=False, gaze=True))
    t0 = 1000.0
    st = {"face_seen": t0}
    # First second: full rate even though nothing has been seen yet.
    assert _intervals(e, st, t0) == (engine_mod.HAND_INTERVAL, engine_mod.FACE_GAZE_INTERVAL)
    assert _intervals(e, st, t0 + 0.5)[0] == engine_mod.HAND_INTERVAL
    # Nothing in view for more than SEARCH_AFTER: slower search for both.
    hand, face = _intervals(e, st, t0 + 2.0)
    assert hand == engine_mod.HAND_SEARCH_INTERVAL
    assert face == engine_mod.FACE_SEARCH_INTERVAL
    # A hand and a face appear: full rate again at once.
    st["hand_seen"] = st["face_seen"] = t0 + 2.1
    assert _intervals(e, st, t0 + 2.2) == (engine_mod.HAND_INTERVAL, engine_mod.FACE_GAZE_INTERVAL)


def test_no_slowdown_during_calibration():
    e = Engine(Settings())
    st = {"face_seen": 0.0, "hand_seen": 0.0}
    e.start_hand_calibration()
    e.start_gaze_calibration(9)
    hand, face = _intervals(e, st, 100.0)
    assert hand == engine_mod.HAND_INTERVAL and face == engine_mod.HAND_INTERVAL


def test_sound_without_file_is_silent(tmp_path, monkeypatch):
    monkeypatch.setattr(handtrack.paths, "SOUNDS_DIR", str(tmp_path))
    sound.play("does-not-exist")            # must not raise


def test_face_on_sound_is_shipped():
    path = os.path.join(handtrack.paths.SOUNDS_DIR, "face-on.wav")
    with open(path, "rb") as f:
        head = f.read(12)
    assert head[:4] == b"RIFF" and head[8:12] == b"WAVE"


def test_gui_thread_gc_collects_by_threshold():
    import gc

    from handtrack.ui.gc_guard import GuiThreadGC
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        gc.collect()
        for _ in range(gc.get_threshold()[0] + 50):
            a = []
            a.append(a)                     # cyclic garbage
        del a
        assert gc.get_count()[0] > gc.get_threshold()[0]
        GuiThreadGC.check()
        assert gc.get_count()[0] < gc.get_threshold()[0]
    finally:
        if was_enabled:
            gc.enable()
