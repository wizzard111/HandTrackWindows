"""Video pipeline: capture → MediaPipe → overlays → preview + virtual camera.

Three threads cooperate and none of them is the GUI thread:

* CameraCapture reads the webcam and keeps only the newest frame;
* the Engine worker processes frames and draws overlays;
* VirtualCamera paces frames out to the virtual device.

MediaPipe runs in LIVE_STREAM mode on its own threads and hands results back
through callbacks. The GUI only receives Qt signals and never blocks.
"""

import logging
import sys
import threading
import time
import types

import cv2
import numpy as np
from PySide6.QtCore import QObject, Signal

from handtrack import paths
from handtrack.config import Settings
from handtrack.vcam import VCAM_AVAILABLE, VirtualCameraSender
from handtrack.vision import geometry as geo
from handtrack.vision import render
from handtrack.vision.models import FACE_MODEL, HAND_MODEL


def _stub_matplotlib():
    """mediapipe's drawing_utils imports matplotlib.pyplot at import time but
    only uses it in a debug plotting helper we never call. Importing the real
    one costs ~0.4 s at every start (and ~40 MB in the bundle), so always give
    it an inert stand-in unless something already imported matplotlib."""
    if "matplotlib" in sys.modules:
        return
    pkg = types.ModuleType("matplotlib")
    pkg.__path__ = []
    pyplot = types.ModuleType("matplotlib.pyplot")

    def _missing(*_a, **_k):
        raise RuntimeError("matplotlib is not installed")
    pyplot.__getattr__ = lambda name: _missing
    pkg.pyplot = pyplot
    sys.modules["matplotlib"] = pkg
    sys.modules["matplotlib.pyplot"] = pyplot


_stub_matplotlib()

import mediapipe as mp  # noqa: E402
from mediapipe.tasks.python import BaseOptions  # noqa: E402
from mediapipe.tasks.python.vision import (  # noqa: E402
    FaceLandmarker, FaceLandmarkerOptions, HandLandmarker, HandLandmarkerOptions,
    RunningMode,
)

logger = logging.getLogger("handtrack")

HAND_INTERVAL = 1.0 / 30.0
FACE_GAZE_INTERVAL = 1.0 / 20.0
FACE_AFK_INTERVAL = 1.0 / 10.0
RESULT_STALE_SECONDS = 0.35
PRIVACY_STALE_SECONDS = 0.15
STATS_INTERVAL = 0.1
CUSTOM_GESTURE_COOLDOWN = 1.5

GAZE_SAMPLES_PER_POINT = 15
GAZE_WAIT_BEFORE_COLLECT = 0.8
GAZE_POINT_TIMEOUT = 8.0
HAND_SAMPLES_TARGET = 20
HAND_WIZARD_COUNTDOWN = 2.5
HAND_CALIB_TIMEOUT = 10.0

GAZE_ZONE_KEYS = (
    ("gaze_zone_top_left", "gaze_zone_top_center", "gaze_zone_top_right"),
    ("gaze_zone_mid_left", "gaze_zone_mid_center", "gaze_zone_mid_right"),
    ("gaze_zone_bottom_left", "gaze_zone_bottom_center", "gaze_zone_bottom_right"),
)


class LatestFrameCapture:
    """Reads the camera on its own thread and keeps only the newest frame."""

    def __init__(self, capture):
        self.capture = capture
        self._cond = threading.Condition()
        self._stop = threading.Event()
        self._frame = None
        self._frame_id = 0
        self.failed = False
        self._thread = threading.Thread(target=self._run, name="CameraCapture", daemon=True)

    def start(self):
        self._thread.start()

    def _run(self):
        misses = 0
        while not self._stop.is_set():
            ok, frame = self.capture.read()
            if not ok:
                misses += 1
                if misses > 150:  # ~3 s of nothing: the camera is gone
                    self.failed = True
                    with self._cond:
                        self._cond.notify_all()
                    return
                self._stop.wait(0.02)
                continue
            misses = 0
            with self._cond:
                self._frame = frame
                self._frame_id += 1
                self._cond.notify_all()

    def wait_latest(self, after_id, timeout=0.1):
        with self._cond:
            if self._frame_id == after_id and not self.failed:
                self._cond.wait(timeout)
            if self._frame is None or self._frame_id == after_id:
                return after_id, None
            return self._frame_id, self._frame

    def stop(self):
        self._stop.set()
        try:
            self.capture.release()
        except Exception:
            logger.exception("Could not release camera")
        self._thread.join(timeout=1.0)


def _hand_entries(hand_result):
    """Hands with stable Left/Right keys, right hand first."""
    if not hand_result or not hand_result.hand_landmarks:
        return []
    entries, used = [], set()
    handedness = getattr(hand_result, "handedness", None) or []
    for index, landmarks in enumerate(hand_result.hand_landmarks[:2]):
        label = ""
        if index < len(handedness) and handedness[index]:
            category = handedness[index][0]
            label = category.category_name or category.display_name or ""
        if label not in ("Left", "Right") or label in used:
            label = f"Hand{index}"
        used.add(label)
        entries.append((label, landmarks))
    entries.sort(key=lambda item: ({"Right": 0, "Left": 1}.get(item[0], 2), item[0]))
    return entries


class Engine(QObject):
    started = Signal(int, int, int, int)          # actual w, h, requested w, h
    stopped = Signal(int)                         # worker thread ident
    failed = Signal(str, dict)                    # i18n key, kwargs
    frame_ready = Signal(object)                  # BGR numpy array sized for the preview
    stats = Signal(dict)
    vcam_state = Signal(str, dict)                # "on" / "off" / "error"
    gesture_triggered = Signal(dict)
    hand_calib_progress = Signal(str, dict)       # i18n key, kwargs
    hand_calib_finished = Signal(bool, dict)      # ok, {templates} or {step}
    gaze_calib_progress = Signal(int, float)      # point index, 0..1 fill
    gaze_calib_finished = Signal(bool, object)    # ok, list of mean features

    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.classifier = geo.TemplateClassifier()
        self.custom_gestures = []
        self.gaze_coeffs = None
        self.screen_size = (1920, 1080)
        self.preview_size = (960, 540)

        self.stickers, self.stickers_custom = render.load_sticker_images()
        self.sticker_cache = render.StickerCache()
        self.drawing = render.Drawing()

        self._thread = None
        self._stop = threading.Event()
        self._reload_stickers = False
        self._clear_drawing = False
        self._preview_busy = False
        self._vcam = None

        self._lock = threading.Lock()
        self._hand = (None, -1, 0.0)
        self._face = (None, -1, 0.0)
        self._start_time = time.monotonic()
        self._last_ts = -1
        self._landmarkers = None

        self._hand_calib = None
        self._gaze_calib = None

    # ------------------------------------------------------------ lifecycle ----
    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    @property
    def worker_ident(self):
        return None if self._thread is None else self._thread.ident

    def create_landmarkers(self):
        """Load both models. Slow (~1 s), so the splash screen calls it."""
        hand = HandLandmarker.create_from_options(HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=paths.model_path(HAND_MODEL[1])),
            running_mode=RunningMode.LIVE_STREAM, num_hands=2,
            min_hand_detection_confidence=0.6, min_hand_presence_confidence=0.6,
            min_tracking_confidence=0.6, result_callback=self._on_hand,
        ))
        face = FaceLandmarker.create_from_options(FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=paths.model_path(FACE_MODEL[1])),
            running_mode=RunningMode.LIVE_STREAM, num_faces=1,
            min_face_detection_confidence=0.6, min_face_presence_confidence=0.6,
            min_tracking_confidence=0.6, output_face_blendshapes=False,
            output_facial_transformation_matrixes=False, result_callback=self._on_face,
        ))
        self._landmarkers = (hand, face)

    def start(self):
        if self.running:
            return
        self._stop.clear()
        self._preview_busy = False
        self._thread = threading.Thread(target=self._run, name="Engine", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
        self._thread = None

    def shutdown(self):
        self.stop()
        if self._landmarkers:
            for detector in self._landmarkers:
                try:
                    detector.close()
                except Exception:
                    logger.exception("Could not close landmarker")
            self._landmarkers = None

    def reload_stickers(self):
        if self.running:
            self._reload_stickers = True
        else:
            self._do_reload_stickers()
        return self.stickers_custom

    def _do_reload_stickers(self):
        self.stickers, self.stickers_custom = render.load_sticker_images()
        self.sticker_cache.clear()

    def clear_drawing(self):
        self._clear_drawing = True
        if not self.running:
            self.drawing.clear()

    def preview_consumed(self):
        self._preview_busy = False

    # -------------------------------------------------------- calibrations ----
    def start_hand_calibration(self):
        self._hand_calib = {"step": 1, "phase": "countdown", "t0": time.monotonic(),
                            "samples": [], "templates": {}}

    def cancel_hand_calibration(self):
        self._hand_calib = None

    def start_gaze_calibration(self, n_points):
        self._gaze_calib = {"index": 0, "n": n_points, "phase": "wait",
                            "t0": time.monotonic(), "samples": [], "results": []}

    def cancel_gaze_calibration(self):
        self._gaze_calib = None

    @property
    def hand_calibrating(self):
        return self._hand_calib is not None

    # ------------------------------------------------- MediaPipe callbacks ----
    def _on_hand(self, result, _image, timestamp_ms):
        with self._lock:
            self._hand = (result, timestamp_ms, time.monotonic())

    def _on_face(self, result, _image, timestamp_ms):
        with self._lock:
            self._face = (result, timestamp_ms, time.monotonic())

    def _next_ts(self):
        ts = int((time.monotonic() - self._start_time) * 1000)
        if ts <= self._last_ts:
            ts = self._last_ts + 1
        self._last_ts = ts
        return ts

    # -------------------------------------------------------------- worker ----
    def _open_camera(self):
        s = self.settings
        if sys.platform == "win32":
            backend = cv2.CAP_DSHOW
        elif sys.platform == "darwin":
            backend = cv2.CAP_AVFOUNDATION
        else:
            backend = cv2.CAP_V4L2
        cap = cv2.VideoCapture(s.camera_index, backend)
        if not cap.isOpened():
            cap.release()
            return None, None
        req_w, req_h = s.resolution_tuple()
        # MJPG lets most USB webcams deliver 720p/1080p at 30 FPS; raw YUY2
        # is often limited to 5–10 FPS at those sizes.
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, req_w)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, req_h)
        cap.set(cv2.CAP_PROP_FPS, 30)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap, (req_w, req_h)

    def _run(self):
        cap, requested = self._open_camera()
        if cap is None:
            self.failed.emit("err_camera", {"n": self.settings.camera_index + 1})
            self.stopped.emit(threading.get_ident())
            return
        reader = LatestFrameCapture(cap)
        reader.start()
        with self._lock:
            self._hand = (None, -1, 0.0)
            self._face = (None, -1, 0.0)
        state = {
            "frame_id": 0, "hand_used": -1, "face_used": -1,
            "hand_submit": 0.0, "face_submit": 0.0, "face_seen": time.monotonic(),
            "last_pattern": None, "primary_key": None, "triggers": {},
            "fps_t": time.monotonic(), "fps_n": 0, "fps": 0.0, "stats_t": 0.0,
            "announced": False, "last_raw": None,
        }
        self.drawing.clear()
        try:
            while not self._stop.is_set():
                frame_id, raw = reader.wait_latest(state["frame_id"])
                if reader.failed:
                    self.failed.emit("err_camera", {"n": self.settings.camera_index + 1})
                    break
                if raw is None:
                    continue
                state["frame_id"] = frame_id
                if not state["announced"]:
                    h, w = raw.shape[:2]
                    self.started.emit(w, h, *requested)
                    state["announced"] = True
                if self._reload_stickers:
                    self._reload_stickers = False
                    self._do_reload_stickers()
                try:
                    self._process(raw, state)
                except Exception:
                    logger.exception("Unhandled error in video loop")
        finally:
            reader.stop()
            self._close_vcam()
            self.drawing.clear()
            self._hand_calib = None
            if self._gaze_calib is not None:
                self._gaze_calib = None
                self.gaze_calib_finished.emit(False, None)
            self.stopped.emit(threading.get_ident())

    def _process(self, raw, st):
        s = self.settings
        frame = cv2.flip(raw, 1)
        height, width = frame.shape[:2]
        now = time.monotonic()
        show_viz = s.visualize
        gaze_calibrating = self._gaze_calib is not None

        need_face = s.hide_face or s.gaze or gaze_calibrating or s.afk_enabled
        if s.hide_face or gaze_calibrating:
            face_interval = HAND_INTERVAL
        elif s.gaze:
            face_interval = FACE_GAZE_INTERVAL
        else:
            face_interval = FACE_AFK_INTERVAL
        self._submit(frame, now, st, need_face, face_interval)

        with self._lock:
            hand_result, hand_ts, hand_at = self._hand
            face_result, face_ts, face_at = self._face

        hand_new = hand_ts != st["hand_used"]
        st["hand_used"] = hand_ts
        if now - hand_at > RESULT_STALE_SECONDS:
            hand_result, hand_new = None, False

        face_new = face_ts != st["face_used"]
        st["face_used"] = face_ts
        face_limit = PRIVACY_STALE_SECONDS if s.hide_face else RESULT_STALE_SECONDS
        if not need_face or now - face_at > face_limit:
            face_result, face_new = None, False

        stats = {}
        counter = self._process_hands(frame, width, height, hand_result, hand_new,
                                      show_viz, now, st, stats)
        if self._clear_drawing:
            self._clear_drawing = False
            self.drawing.clear()
        if s.draw_enabled:
            d = self.drawing
            d.color = render.DRAW_COLORS[s.draw_color % len(render.DRAW_COLORS)]
            d.thickness, d.lifetime = s.draw_thickness, s.draw_lifetime
            d.render(frame, now)
        elif self.drawing.strokes:
            self.drawing.clear()
        if s.show_counter:
            render.draw_corner_counter(frame, counter)

        self._process_face(frame, width, height, face_result, face_new, show_viz,
                           now, st, stats)

        # ---- outputs: no colour conversion, Qt and pyvirtualcam take BGR ----
        self._update_vcam(frame, width, height)

        if s.preview_visible and not self._preview_busy:
            pw, ph = self.preview_size
            scale = min(pw / width, ph / height, 1.0)
            if scale < 0.999:
                preview = cv2.resize(frame, (max(1, int(width * scale)), max(1, int(height * scale))),
                                     interpolation=cv2.INTER_LINEAR)
            else:
                preview = frame
            self._preview_busy = True
            self.frame_ready.emit(preview)

        st["fps_n"] += 1
        if now - st["fps_t"] >= 1.0:
            st["fps"] = st["fps_n"] / (now - st["fps_t"])
            st["fps_n"], st["fps_t"] = 0, now
        if now - st["stats_t"] >= STATS_INTERVAL:
            st["stats_t"] = now
            stats["fps"] = st["fps"]
            self.stats.emit(stats)

    def _submit(self, frame, now, st, need_face, face_interval):
        hand_due = now - st["hand_submit"] >= HAND_INTERVAL
        face_due = need_face and now - st["face_submit"] >= face_interval
        if not (hand_due or face_due) or not self._landmarkers:
            return
        h, w = frame.shape[:2]
        if self.settings.fast_mode:
            small = cv2.resize(frame, (max(160, w // 2), max(90, h // 2)),
                               interpolation=cv2.INTER_AREA)
            rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        else:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        ts = self._next_ts()
        hand_lm, face_lm = self._landmarkers
        if hand_due:
            st["hand_submit"] = now
            try:
                hand_lm.detect_async(image, ts)
            except (RuntimeError, ValueError):
                logger.exception("HandLandmarker submission failed")
        if face_due:
            st["face_submit"] = now
            try:
                face_lm.detect_async(image, ts)
            except (RuntimeError, ValueError):
                logger.exception("FaceLandmarker submission failed")

    # --------------------------------------------------------------- hands ----
    def _process_hands(self, frame, width, height, hand_result, is_new, show_viz,
                       now, st, stats):
        s = self.settings
        entries = _hand_entries(hand_result)

        if self._hand_calib is not None:
            landmarks = entries[0][1] if entries else None
            self._hand_calibration_step(landmarks if is_new else None, now)
            self.drawing.release()
            st["last_pattern"] = st["primary_key"] = None
            if landmarks is None:
                stats["gesture"] = ("gesture_no_hand", {})
                return "-"
            raw = sum(geo.get_finger_states(landmarks))
            stats["gesture"] = ("gesture_calibrating", {"n": raw})
            if show_viz:
                render.draw_hand_skeleton(frame, landmarks, width, height)
            return str(raw)

        if not entries:
            stats["gesture"] = ("gesture_no_hand", {})
            stats["fingers"] = None
            st["last_pattern"] = st["primary_key"] = None
            self.drawing.release()
            return "-"

        counter = "-"
        active = set()
        classifier = self.classifier
        for position, (hand_key, landmarks) in enumerate(entries):
            active.add(hand_key)
            states = geo.get_finger_states(landmarks)
            count = sum(states)
            if show_viz:
                render.draw_hand_skeleton(frame, landmarks, width, height)

            if position == 0:
                if classifier:
                    tmpl_n, dist = classifier.classify(landmarks)
                    if dist < s.threshold:
                        count = tmpl_n
                        stats["gesture"] = ("gesture_templ", {"n": count, "d": dist})
                    else:
                        stats["gesture"] = ("gesture_templ_unsure", {"n": count, "d": dist})
                else:
                    stats["gesture"] = ("gesture_basic", {"n": count})
                stats["fingers"] = states
                counter = str(count)
                if is_new:
                    if hand_key != st["primary_key"]:
                        st["last_pattern"] = None
                    st["primary_key"] = hand_key
                    self._trigger_custom(states, now, st)

            if s.attach_photo and 1 <= count <= 5:
                render.overlay_sticker_on_hand(
                    frame, landmarks, self.sticker_cache, count, self.stickers[count],
                    scale_factor=s.sticker_scale, rotate=s.rotate_sticker)

            if is_new:
                was = hand_key in self.drawing._active
                pinching, mid = geo.is_pinching(landmarks, was) if s.draw_enabled else (False, None)
                if pinching:
                    self.drawing.add(hand_key, mid, width, height, now)
                else:
                    self.drawing.release(hand_key)

        if is_new:
            for key in self.drawing.active_keys():
                if key not in active:
                    self.drawing.release(key)
        return counter

    def _trigger_custom(self, states, now, st):
        if states == st["last_pattern"]:
            return
        st["last_pattern"] = states
        if not self.settings.custom_gestures_enabled:
            return
        for index, gesture in enumerate(self.custom_gestures):
            if gesture["pattern"] != states:
                continue
            if now - st["triggers"].get(index, 0.0) > CUSTOM_GESTURE_COOLDOWN:
                st["triggers"][index] = now
                self.gesture_triggered.emit(gesture)
            break

    def _hand_calibration_step(self, landmarks, now):
        c = self._hand_calib
        n = c["step"]
        if c["phase"] == "countdown":
            remaining = HAND_WIZARD_COUNTDOWN - (now - c["t0"])
            if remaining > 0:
                self.hand_calib_progress.emit("hand_calib_step_countdown", {"n": n, "r": remaining})
                return
            c.update(phase="collect", t0=now, samples=[])

        if landmarks is not None:
            c["samples"].append(geo.normalize_hand_vector(landmarks))
            self.hand_calib_progress.emit("hand_calib_step_collect",
                                          {"n": n, "c": len(c["samples"]), "t": HAND_SAMPLES_TARGET})
        timed_out = now - c["t0"] >= HAND_CALIB_TIMEOUT
        if len(c["samples"]) >= HAND_SAMPLES_TARGET or (timed_out and len(c["samples"]) >= 5):
            c["templates"][n] = np.mean(np.array(c["samples"]), axis=0)
            if n >= 5:
                self._hand_calib = None
                self.hand_calib_finished.emit(True, c["templates"])
            else:
                c.update(step=n + 1, phase="countdown", t0=now, samples=[])
                self.hand_calib_progress.emit("hand_calib_step_prep", {"n": n + 1})
        elif timed_out:
            self._hand_calib = None
            self.hand_calib_finished.emit(False, {"n": n})

    # ---------------------------------------------------------- face, gaze ----
    def _process_face(self, frame, width, height, face_result, face_new, show_viz,
                      now, st, stats):
        s = self.settings
        face = face_result.face_landmarks[0] if face_result and face_result.face_landmarks else None
        if face is not None and face_new:
            st["face_seen"] = now

        calib = self._gaze_calib
        features = None
        if face is not None and (s.gaze or calib is not None):
            features = geo.gaze_features(face)
            if show_viz:
                render.draw_eye_points(frame, face, width, height)

        if calib is not None:
            self._gaze_calibration_step(features if face_new else None, now)

        if s.gaze:
            if features is None:
                stats["gaze"] = ("gaze_status_no_face", {})
            elif self.gaze_coeffs is not None:
                sw, sh = self.screen_size
                gx, gy = geo.predict_gaze(self.gaze_coeffs, features)
                gx, gy = min(max(gx, 0.0), sw), min(max(gy, 0.0), sh)
                stats["gaze_point"] = (gx / sw, gy / sh)
                col, row = min(2, int(gx / sw * 3)), min(2, int(gy / sh * 3))
                stats["gaze"] = ("gaze_status_zone", {"zone_key": GAZE_ZONE_KEYS[row][col]})
            else:
                avg = (features[0] + features[2]) / 2
                key = "gaze_dir_left" if avg < 0.4 else "gaze_dir_right" if avg > 0.6 else "gaze_dir_center"
                stats["gaze"] = ("gaze_status_rough", {"direction_key": key, "val": avg})
                stats["gaze_point"] = (1.0 - avg, 0.5)
        else:
            stats["gaze"] = ("gaze_status_off", {})

        # The privacy mask is drawn after the eye features are read, so gaze
        # calibration also works with the mask on.
        if s.hide_face:
            if face is not None:
                render.draw_privacy_mask(frame, render.face_box(face, width, height))
            else:
                frame[:] = 0  # fail closed: a lost track must never reveal the face

        if s.afk_enabled and not s.hide_face and now - st["face_seen"] > s.afk_timeout:
            stats["afk"] = True
            render.draw_afk(frame, self._afk_text[0], self._afk_text[1])

    _afk_text = ("AFK", "")

    def set_afk_text(self, title, subtitle):
        self._afk_text = (title, subtitle)

    def _gaze_calibration_step(self, features, now):
        c = self._gaze_calib
        if c["phase"] == "wait":
            if now - c["t0"] >= GAZE_WAIT_BEFORE_COLLECT:
                c.update(phase="collect", t0=now, samples=[])
            return
        if features is not None:
            c["samples"].append(features)
            self.gaze_calib_progress.emit(c["index"], len(c["samples"]) / GAZE_SAMPLES_PER_POINT)
        timed_out = now - c["t0"] >= GAZE_POINT_TIMEOUT
        if len(c["samples"]) >= GAZE_SAMPLES_PER_POINT or (timed_out and len(c["samples"]) >= 3):
            c["results"].append(np.mean(np.array(c["samples"]), axis=0).tolist())
            c["index"] += 1
            if c["index"] >= c["n"]:
                self._gaze_calib = None
                self.gaze_calib_finished.emit(True, c["results"])
            else:
                c.update(phase="wait", t0=now, samples=[])
                self.gaze_calib_progress.emit(c["index"], 0.0)
        elif timed_out:
            self._gaze_calib = None
            self.gaze_calib_finished.emit(False, None)

    # ------------------------------------------------------ virtual camera ----
    def _update_vcam(self, frame, width, height):
        want = self.settings.vcam and VCAM_AVAILABLE
        sender = self._vcam
        if sender is not None and (not want or (sender.width, sender.height) != (width, height)):
            self._close_vcam()
            sender = None
        if not want:
            return
        if sender is None:
            sender = self._vcam = VirtualCameraSender(width, height)
            sender.start()
        if sender.error is not None:
            error = sender.error
            self._close_vcam(announce=False)
            self.settings.vcam = False
            self.vcam_state.emit("error", {"err": error})
            return
        if sender.started and sender.announced is not sender.active:
            sender.announced = sender.active
            self.vcam_state.emit("on", {"dev": sender.device, "w": width, "h": height,
                                        "active": sender.active})
        sender.submit(frame)

    def _close_vcam(self, announce=True):
        if self._vcam is not None:
            self._vcam.stop()
            self._vcam = None
            if announce:
                self.vcam_state.emit("off", {})
