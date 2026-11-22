"""Camera permission (macOS); everywhere else access is simply granted.

macOS asks the user once per app. OpenCV's own attempt to ask from the video
thread cannot work (it would have to spin the main run loop) and the camera
then hangs, so HandTrack asks itself through AVFoundation and tells OpenCV to
skip its request (OPENCV_AVFOUNDATION_SKIP_AUTH). The installer runs
``HandTrack --request-camera`` so the system prompt appears during setup, on
behalf of HandTrack.app.
"""

import logging
import os
import sys
import threading

logger = logging.getLogger("handtrack")

AUTHORIZED, DENIED, RESTRICTED, NOT_DETERMINED, UNKNOWN = (
    "authorized", "denied", "restricted", "not_determined", "unknown")
_STATUS = {0: NOT_DETERMINED, 1: RESTRICTED, 2: DENIED, 3: AUTHORIZED}

if sys.platform == "darwin":
    os.environ.setdefault("OPENCV_AVFOUNDATION_SKIP_AUTH", "1")


def _avfoundation():
    try:
        from AVFoundation import AVCaptureDevice, AVMediaTypeVideo
        return AVCaptureDevice, AVMediaTypeVideo
    except ImportError:
        return None


def status():
    if sys.platform != "darwin":
        return AUTHORIZED
    av = _avfoundation()
    if av is None:
        return UNKNOWN
    device, media = av
    return _STATUS.get(int(device.authorizationStatusForMediaType_(media)), UNKNOWN)


def request(timeout=180.0):
    """Ask for access if macOS has not asked yet. True when the camera may be used
    (also when the state cannot be determined: then OpenCV just tries)."""
    current = status()
    if current != NOT_DETERMINED:
        return current in (AUTHORIZED, UNKNOWN)
    device, media = _avfoundation()
    done, result = threading.Event(), {}

    def handler(granted):           # called on an arbitrary dispatch queue
        result["granted"] = bool(granted)
        done.set()

    logger.info("Asking macOS for camera access")
    device.requestAccessForMediaType_completionHandler_(media, handler)
    done.wait(timeout)
    granted = result.get("granted", False)
    logger.info("Camera access %s", "granted" if granted else "not granted")
    return granted
