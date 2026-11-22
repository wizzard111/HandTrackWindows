import sys
import threading
import types

from handtrack import camera_access


def _fake_avfoundation(monkeypatch, status, grant):
    calls = []

    class Device:
        @staticmethod
        def authorizationStatusForMediaType_(media):
            return status["value"]

        @staticmethod
        def requestAccessForMediaType_completionHandler_(media, handler):
            calls.append(media)

            def answer():                     # like macOS: later, on another thread
                status["value"] = 3 if grant else 2
                handler(grant)
            threading.Timer(0.05, answer).start()

    module = types.SimpleNamespace(AVCaptureDevice=Device, AVMediaTypeVideo="vide")
    monkeypatch.setitem(sys.modules, "AVFoundation", module)
    monkeypatch.setattr(sys, "platform", "darwin")
    return calls


def test_other_platforms_are_always_allowed(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert camera_access.status() == camera_access.AUTHORIZED
    assert camera_access.request() is True


def test_mac_asks_once_and_waits_for_the_answer(monkeypatch):
    status = {"value": 0}                     # not determined
    calls = _fake_avfoundation(monkeypatch, status, grant=True)
    assert camera_access.status() == camera_access.NOT_DETERMINED
    assert camera_access.request(timeout=5) is True
    assert calls == ["vide"]
    assert camera_access.request(timeout=5) is True   # already decided: no second prompt
    assert calls == ["vide"]


def test_mac_denied_is_reported_not_hung(monkeypatch):
    status = {"value": 0}
    _fake_avfoundation(monkeypatch, status, grant=False)
    assert camera_access.request(timeout=5) is False
    assert camera_access.status() == camera_access.DENIED
    assert camera_access.request(timeout=5) is False      # denied earlier: no prompt, no wait


def test_mac_without_pyobjc_lets_opencv_try(monkeypatch):
    monkeypatch.setitem(sys.modules, "AVFoundation", None)  # import fails
    monkeypatch.setattr(sys, "platform", "darwin")
    assert camera_access.status() == camera_access.UNKNOWN
    assert camera_access.request() is True
