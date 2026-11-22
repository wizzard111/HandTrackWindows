"""Unity Capture protocol test: this process plays the filter's (receiver's)
role, so no driver has to be registered."""

import ctypes
import struct
import sys
import uuid

import numpy as np
import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows shared memory")

HEADER = struct.Struct("<Iiiiiiii")
MAX_IMAGE = 3840 * 2160 * 4 * 2


@pytest.fixture
def receiver(monkeypatch):
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexA.restype = wintypes.HANDLE
    k32.CreateEventA.restype = wintypes.HANDLE
    k32.CreateFileMappingA.restype = wintypes.HANDLE
    k32.CreateFileMappingA.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                       wintypes.DWORD, wintypes.DWORD, ctypes.c_char_p]
    k32.MapViewOfFile.restype = ctypes.c_void_p
    k32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.DWORD, ctypes.c_size_t]
    k32.OpenEventA.restype = wintypes.HANDLE
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.SetEvent.argtypes = [wintypes.HANDLE]
    k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]

    # Unique names so a real Unity Capture filter on this machine is untouched.
    tag = uuid.uuid4().hex[:8]
    from handtrack import vcam

    def names(self, *_a, **_k):
        return {k: f"HTTest_{tag}_{k}".encode() for k in ("Mutx", "Want", "Sent", "Data")}

    original_init = vcam.UnityCaptureOutput.__init__

    def init(self, width, height, cap_num=0):
        original_init(self, width, height, cap_num)
        self._names = names(self)

    monkeypatch.setattr(vcam.UnityCaptureOutput, "__init__", init)
    n = names(None)
    handles = [k32.CreateMutexA(None, False, n["Mutx"]),
               k32.CreateEventA(None, False, False, n["Sent"]),
               k32.CreateFileMappingA(wintypes.HANDLE(-1), None, 0x04, 0,
                                      HEADER.size + MAX_IMAGE, n["Data"])]
    view = k32.MapViewOfFile(handles[2], 0x0002, 0, 0, 0)
    ctypes.memmove(view, struct.pack("<I", MAX_IMAGE), 4)
    yield k32, view, handles[1], n
    k32.UnmapViewOfFile(ctypes.c_void_p(view))
    for h in handles:
        k32.CloseHandle(h)


def test_frame_layout(receiver):
    from handtrack.vcam import UnityCaptureOutput
    k32, view, sent_event, names = receiver
    w, h = 64, 32
    frame = np.zeros((h, w, 3), np.uint8)
    frame[: h // 2] = (255, 255, 255)       # top half white (BGR)
    frame[:, :8] = (255, 0, 0)              # left strip blue (BGR)

    out = UnityCaptureOutput(w, h)
    assert out.send(frame)
    assert k32.WaitForSingleObject(sent_event, 0) == 0  # receiver got "sent"

    max_size, width, height, stride, fmt, resize, mirror, timeout = HEADER.unpack(
        ctypes.string_at(view, HEADER.size))
    assert (max_size, width, height, stride, fmt, resize) == (MAX_IMAGE, w, h, w, 0, 1)
    image = np.frombuffer(ctypes.string_at(view + HEADER.size, w * h * 4), np.uint8).reshape(h, w, 4)
    # Stored bottom-up, RGBA: first row is the bottom (black) row.
    assert tuple(image[0, 20]) == (0, 0, 0, 255)
    assert tuple(image[-1, 20]) == (255, 255, 255, 255)
    assert tuple(image[-1, 0]) == (0, 0, 255, 255)

    # The filter signals "want" when it reads; the output reports it once.
    want = k32.OpenEventA(0x0002, False, names["Want"])
    k32.SetEvent(want)
    assert out.consumer_wants_frame()
    assert not out.consumer_wants_frame()
    k32.CloseHandle(want)
    out.close()


def test_send_without_receiver_is_noop():
    from handtrack.vcam import UnityCaptureOutput
    out = UnityCaptureOutput(32, 16)
    out._names = {k: f"HTMissing_{uuid.uuid4().hex}_{k}".encode() for k in ("Mutx", "Want", "Sent", "Data")}
    assert out.send(np.zeros((16, 32, 3), np.uint8)) is False
    out.close()
