"""Virtual camera output.

The installer registers the Unity Capture DirectShow filter (MIT licensed)
under the name "HandTrack Camera", so no OBS install is needed. Any app that
lists regular webcams (Discord, Telegram Desktop, Zoom, Teams, Skype,
browsers, OBS) can then select it.

Frames reach the filter through the small shared-memory protocol defined in
Unity Capture's shared.inl: a named mutex, two auto-reset events and a file
mapping holding a 32-byte header followed by an RGBA image stored bottom-up.
The filter letterboxes the image itself when an app asks for a different
resolution, so the picture is never stretched.

If Unity Capture is missing but pyvirtualcam is installed (source checkouts),
it is used as a fallback, which also covers OBS Virtual Camera.
"""

import ctypes
import logging
import os
import queue
import struct
import sys
import threading
import time

import cv2
import numpy as np

from handtrack import VCAM_DEVICE_NAME, paths

logger = logging.getLogger("handtrack")

_DSHOW_VIDEO_CATEGORY = r"CLSID\{860BB310-5D01-11d0-BD3B-00A0C911CE86}\Instance"
_UC_CLSID = r"CLSID\{{5C2CD55C-92AD-4999-8666-912BD3E700{:02X}}}"
_UC_MAX_IMAGE = 3840 * 2160 * 4 * 2
_UC_HEADER = struct.Struct("<Iiiiiiii")  # maxSize, w, h, stride, format, resize, mirror, timeout
_UC_RESIZE_LINEAR = 1
_UC_TIMEOUT_MS = 1500
DRIVER_DIR = os.path.join(paths.RESOURCE_DIR, "driver")
if not paths.FROZEN and not os.path.isdir(DRIVER_DIR):
    # Source checkout: packaging/fetch_deps.py downloads the driver here.
    DRIVER_DIR = os.path.join(paths.RESOURCE_DIR, "build", "deps", "driver")

try:  # optional fallback, not shipped in the installer
    import pyvirtualcam
except ImportError:
    pyvirtualcam = None

VCAM_AVAILABLE = sys.platform == "win32" or pyvirtualcam is not None


# ---------------------------------------------------------------- registry ----
def _reg_default(path):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, path) as key:
            return str(winreg.QueryValueEx(key, "")[0]).strip()
    except OSError:
        return None


def unity_capture_devices():
    """[(cap_num, name)] of registered 64-bit Unity Capture devices."""
    if sys.platform != "win32":
        return []
    devices = []
    for num in range(10):
        name = _reg_default(_UC_CLSID.format(0x10 + num + (1 if num else 0)))
        if name:
            devices.append((num, name))
    return devices


def list_dshow_cameras():
    """Friendly names of registered DirectShow software video sources."""
    if sys.platform != "win32":
        return []
    import winreg
    names = []
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, _DSHOW_VIDEO_CATEGORY) as root:
            index = 0
            while True:
                try:
                    sub = winreg.EnumKey(root, index)
                except OSError:
                    break
                index += 1
                try:
                    with winreg.OpenKey(root, sub) as key:
                        names.append(str(winreg.QueryValueEx(key, "FriendlyName")[0]))
                except OSError:
                    continue
    except OSError:
        pass
    return names


def driver_installed():
    if unity_capture_devices():
        return True
    return pyvirtualcam is not None and "OBS Virtual Camera" in list_dshow_cameras()


def driver_files_available():
    return os.path.isfile(os.path.join(DRIVER_DIR, "UnityCaptureFilter64.dll"))


def install_driver():
    """Register the bundled filter with one UAC prompt. Returns (ok, error)."""
    if sys.platform != "win32":
        return False, "Windows only"
    if not driver_files_available():
        return False, f"Driver files not found in {DRIVER_DIR}"
    from ctypes import wintypes

    windir = os.environ.get("SystemRoot", r"C:\Windows")
    name_arg = f'"/i:UnityCaptureName={VCAM_DEVICE_NAME}"'
    dll64 = os.path.join(DRIVER_DIR, "UnityCaptureFilter64.dll")
    dll32 = os.path.join(DRIVER_DIR, "UnityCaptureFilter32.dll")
    commands = [f'"{os.path.join(windir, "System32", "regsvr32.exe")}" /s {name_arg} "{dll64}"']
    if os.path.isfile(dll32):
        commands.append(
            f'"{os.path.join(windir, "SysWOW64", "regsvr32.exe")}" /s {name_arg} "{dll32}"')

    class SHELLEXECUTEINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong),
            ("hwnd", wintypes.HWND), ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
            ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    info = SHELLEXECUTEINFO()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x00000040  # SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = os.path.join(windir, "System32", "cmd.exe")
    info.lpParameters = '/c "' + " && ".join(commands) + '"'
    info.nShow = 0
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        return False, ctypes.FormatError()
    kernel32 = ctypes.windll.kernel32
    kernel32.WaitForSingleObject(info.hProcess, 60_000)
    code = wintypes.DWORD()
    kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
    kernel32.CloseHandle(info.hProcess)
    if code.value != 0:
        return False, f"regsvr32 exit code {code.value}"
    return True, None


# -------------------------------------------------- Unity Capture protocol ----
class UnityCaptureOutput:
    """Writes frames into the Unity Capture filter's shared memory."""

    def __init__(self, width, height, cap_num=0):
        from ctypes import wintypes
        if width * height * 4 > _UC_MAX_IMAGE:
            raise ValueError("Frame too large for Unity Capture")
        self.width, self.height = width, height
        suffix = "" if cap_num == 0 else chr(ord("0") + cap_num)
        self._names = {k: f"UnityCapture_{k}{suffix}".encode() for k in ("Mutx", "Want", "Sent", "Data")}
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        for fn, res, args in (
            ("OpenMutexA", wintypes.HANDLE, [wintypes.DWORD, wintypes.BOOL, ctypes.c_char_p]),
            ("CreateEventA", wintypes.HANDLE, [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, ctypes.c_char_p]),
            ("OpenEventA", wintypes.HANDLE, [wintypes.DWORD, wintypes.BOOL, ctypes.c_char_p]),
            ("OpenFileMappingA", wintypes.HANDLE, [wintypes.DWORD, wintypes.BOOL, ctypes.c_char_p]),
            ("MapViewOfFile", ctypes.c_void_p, [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                                wintypes.DWORD, ctypes.c_size_t]),
            ("UnmapViewOfFile", wintypes.BOOL, [ctypes.c_void_p]),
            ("WaitForSingleObject", wintypes.DWORD, [wintypes.HANDLE, wintypes.DWORD]),
            ("ReleaseMutex", wintypes.BOOL, [wintypes.HANDLE]),
            ("SetEvent", wintypes.BOOL, [wintypes.HANDLE]),
            ("CloseHandle", wintypes.BOOL, [wintypes.HANDLE]),
        ):
            getattr(k32, fn).restype = res
            getattr(k32, fn).argtypes = args
        self._k32 = k32
        self._mutex = self._want = self._sent = self._mapping = None
        self._view = None
        self._image = None
        self._flipped = np.empty((height, width, 3), np.uint8)

    def _open(self):
        """Succeeds only once an app has opened the camera (the filter
        creates the shared objects on its side)."""
        k32, n = self._k32, self._names
        if self._view:
            return True
        if not self._mutex:
            self._mutex = k32.OpenMutexA(0x00100000 | 0x0001, False, n["Mutx"])  # SYNCHRONIZE|MODIFY
            if not self._mutex:
                return False
        if not self._want:
            self._want = k32.CreateEventA(None, False, False, n["Want"])
        if not self._sent:
            self._sent = k32.OpenEventA(0x0002, False, n["Sent"])  # EVENT_MODIFY_STATE
            if not self._sent:
                return False
        if not self._mapping:
            self._mapping = k32.OpenFileMappingA(0x0002, False, n["Data"])  # FILE_MAP_WRITE
            if not self._mapping:
                return False
        view = k32.MapViewOfFile(self._mapping, 0x0002, 0, 0, 0)
        if not view:
            return False
        self._view = view
        buf = (ctypes.c_uint8 * (self.width * self.height * 4)).from_address(view + _UC_HEADER.size)
        self._image = np.ctypeslib.as_array(buf).reshape(self.height, self.width, 4)
        return True

    def consumer_wants_frame(self):
        """True if the filter asked for a frame since the last check."""
        return bool(self._want) and self._k32.WaitForSingleObject(self._want, 0) == 0

    def send(self, bgr):
        if not self._open():
            return False
        # The filter writes rows bottom-up into a DIB: flip outside the lock,
        # then convert straight into shared memory (no intermediate copy).
        cv2.flip(bgr, 0, dst=self._flipped)
        k32 = self._k32
        k32.WaitForSingleObject(self._mutex, 0xFFFFFFFF)
        try:
            header = _UC_HEADER.pack(_UC_MAX_IMAGE, self.width, self.height, self.width, 0,
                                     _UC_RESIZE_LINEAR, 0, _UC_TIMEOUT_MS)
            ctypes.memmove(self._view + 4, header[4:], _UC_HEADER.size - 4)
            cv2.cvtColor(self._flipped, cv2.COLOR_BGR2RGBA, dst=self._image)
        finally:
            k32.ReleaseMutex(self._mutex)
        k32.SetEvent(self._sent)
        return True

    def close(self):
        k32 = self._k32
        self._image = None
        if self._view:
            k32.UnmapViewOfFile(self._view)
            self._view = None
        for name in ("_mapping", "_sent", "_want", "_mutex"):
            handle = getattr(self, name)
            if handle:
                k32.CloseHandle(handle)
                setattr(self, name, None)


def _standby_frame(width, height):
    frame = np.full((height, width, 3), (24, 18, 20), np.uint8)
    text = "HandTrack"
    scale = max(0.8, width / 900)
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_DUPLEX, scale, 2)
    cv2.putText(frame, text, ((width - tw) // 2, (height + th) // 2), cv2.FONT_HERSHEY_DUPLEX,
                scale, (200, 190, 200), 2, cv2.LINE_AA)
    return frame


# ------------------------------------------------------------------ sender ----
class VirtualCameraSender:
    """Owns the virtual camera on its own thread; only the newest frame is kept.

    ``active`` is True while some app is actually reading the camera. When
    nobody watches, frames are written at ~2 FPS so the CPU stays idle.
    """

    IDLE_INTERVAL = 0.5
    ACTIVE_GRACE = 1.0

    def __init__(self, width, height, fps=30):
        self.width = width
        self.height = height
        self.fps = fps
        self.device = None
        self.error = None
        self.announced = None
        self.active = False
        self._frames = queue.Queue(maxsize=1)
        self._started = threading.Event()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, name="VirtualCamera", daemon=True)

    @property
    def alive(self):
        return self._thread.is_alive()

    @property
    def started(self):
        return self._started.is_set()

    def start(self):
        self._thread.start()

    def submit(self, bgr_frame):
        if self._stop_event.is_set():
            return
        try:
            self._frames.put_nowait(bgr_frame)
        except queue.Full:
            try:
                self._frames.get_nowait()
            except queue.Empty:
                pass
            try:
                self._frames.put_nowait(bgr_frame)
            except queue.Full:
                pass

    def _run(self):
        try:
            devices = unity_capture_devices()
            if devices:
                cap_num, name = next(((n, d) for n, d in devices if d == VCAM_DEVICE_NAME), devices[0])
                self.device = name
                self._run_unity(UnityCaptureOutput(self.width, self.height, cap_num))
            elif pyvirtualcam is not None:
                self._run_pyvirtualcam()
            else:
                raise RuntimeError("Virtual camera driver is not installed.")
        except Exception as exc:
            logger.exception("Virtual camera worker failed")
            self.error = str(exc) or type(exc).__name__

    def _run_unity(self, out):
        self._started.set()
        last_want = 0.0
        last_sent = 0.0
        try:
            while not self._stop_event.is_set():
                try:
                    frame = self._frames.get(timeout=0.2)
                except queue.Empty:
                    continue
                now = time.monotonic()
                if out.consumer_wants_frame():
                    last_want = now
                self.active = now - last_want < self.ACTIVE_GRACE
                if self.active or now - last_sent >= self.IDLE_INTERVAL:
                    if out.send(frame):
                        last_sent = now
            # Leave a neutral picture instead of a frozen last frame.
            try:
                out.send(_standby_frame(self.width, self.height))
            except Exception:
                pass
        finally:
            out.close()

    def _run_pyvirtualcam(self):
        with pyvirtualcam.Camera(width=self.width, height=self.height, fps=self.fps,
                                 fmt=pyvirtualcam.PixelFormat.BGR) as camera:
            self.device = camera.device
            self.active = True
            self._started.set()
            while not self._stop_event.is_set():
                try:
                    frame = self._frames.get(timeout=0.2)
                except queue.Empty:
                    continue
                camera.send(frame)

    def stop(self):
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1.5)
