"""HandTrack — hand gestures, gaze tracking, privacy mask and a virtual camera."""

import os

# numpy's OpenBLAS reserves a large buffer per CPU core for its thread pool
# (~350 MB of private memory on a 12-core machine). HandTrack only does small
# array maths, so one BLAS thread is plenty. Must be set before numpy loads.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

__version__ = "8.3.0"
APP_NAME = "HandTrack"
VCAM_DEVICE_NAME = "HandTrack Camera"
