"""MediaPipe model files: bundled with the installer, downloaded otherwise."""

import os
import urllib.error
import urllib.request

from handtrack import paths

HAND_MODEL = ("HandLandmarker", "hand_landmarker.task",
              "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
              "hand_landmarker/float16/latest/hand_landmarker.task")
FACE_MODEL = ("FaceLandmarker", "face_landmarker.task",
              "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
              "face_landmarker/float16/latest/face_landmarker.task")
MODELS = (HAND_MODEL, FACE_MODEL)


class ModelDownloadError(RuntimeError):
    def __init__(self, name, error):
        super().__init__(str(error))
        self.name = name
        self.error = error


def ensure_models(progress=None):
    """Download missing models. progress(name, percent) is called while loading."""
    paths.ensure_dirs()
    for name, filename, url in MODELS:
        target = paths.model_path(filename)
        if os.path.isfile(target) and os.path.getsize(target) > 0:
            continue
        target = os.path.join(paths.MODELS_DIR, filename)
        tmp = target + ".part"
        try:
            with urllib.request.urlopen(url, timeout=30) as resp, open(tmp, "wb") as out:
                total = int(resp.headers.get("Content-Length") or 0)
                done = 0
                while chunk := resp.read(256 * 1024):
                    out.write(chunk)
                    done += len(chunk)
                    if progress and total:
                        progress(name, int(done * 100 / total))
            os.replace(tmp, target)
        except (urllib.error.URLError, OSError) as exc:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise ModelDownloadError(name, exc) from exc
