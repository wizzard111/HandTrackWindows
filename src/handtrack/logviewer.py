"""The Windows log window: ``HandTrack --log-viewer LOG PID OFFSET``.

A second, tiny HandTrack process (standard library only: no Qt, no MediaPipe,
~10 MB) that opens its own console, prints the log from OFFSET on and follows
it until process PID exits. It sleeps in WaitForSingleObject on that process,
so it costs nothing between lines and closes itself with HandTrack. Closing
the window only ends the viewer. Replaces a PowerShell loop that took ~3 % of
a core and ~100 MB.
"""

import os
import re
import sys

_LINE = re.compile(r"^\S+ (\d\d:\d\d:\d\d),\d+ \| (\w+) \| ([^|]+) \| (.*)$")
_RESET, _DIM, _WHITE, _YELLOW, _RED = "\x1b[0m", "\x1b[90m", "\x1b[97m", "\x1b[93m", "\x1b[91m"


def _format(line):
    m = _LINE.match(line)
    if not m:
        return line
    clock, level, thread, msg = m.groups()
    if "WARN" in level:
        color = _YELLOW
    elif level in ("ERROR", "CRITICAL"):
        color = _RED
    elif thread.strip() == "NativeOutput":
        color = _DIM
    else:
        color = _WHITE
    return f"{color}{clock}  {level:<7}  {msg}{_RESET}"


def _open_shared(path):
    """Open for reading while allowing HandTrack to keep writing and to rotate
    (rename) the file: Python's open() would block the rename on Windows."""
    import ctypes
    import msvcrt
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    handle = k32.CreateFileW(path, 0x80000000, 0x1 | 0x2 | 0x4, None, 4, 0x80, None)  # GENERIC_READ, share all, OPEN_ALWAYS
    if handle in (None, wintypes.HANDLE(-1).value):
        raise OSError(ctypes.get_last_error(), "cannot open the log")
    return os.fdopen(msvcrt.open_osfhandle(handle, os.O_RDONLY), "rb")


def run(log_path, pid, offset):
    import ctypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    if not k32.GetConsoleWindow():
        k32.AllocConsole()
    k32.SetConsoleTitleW("HandTrack - log")
    k32.SetConsoleOutputCP(65001)
    out = open("CONOUT$", "w", encoding="utf-8", errors="replace")
    import msvcrt
    from ctypes import wintypes
    handle = wintypes.HANDLE(msvcrt.get_osfhandle(out.fileno()))   # the console we write to
    mode = wintypes.DWORD()
    if k32.GetConsoleMode(handle, ctypes.byref(mode)):
        k32.SetConsoleMode(handle, mode.value | 0x0004)    # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    # Wide enough that log lines do not wrap (160 columns, 36 rows, 3000 lines kept).
    k32.SetConsoleScreenBufferSize(handle, wintypes._COORD(160, 3000))
    k32.SetConsoleWindowInfo(handle, True, ctypes.byref(wintypes.SMALL_RECT(0, 0, 159, 35)))
    out.write(f"{_DIM}HandTrack log  ({log_path})\nThis window closes by itself when HandTrack exits.{_RESET}\n\n")
    out.flush()

    process = k32.OpenProcess(0x00100000, False, pid)       # SYNCHRONIZE
    f = _open_shared(log_path)
    if 0 <= offset <= os.path.getsize(log_path):
        f.seek(offset)
    pending = b""
    while True:
        chunk = f.read()
        if chunk:
            pending += chunk
            *lines, pending = pending.split(b"\n")
            for raw in lines:
                line = raw.decode("utf-8", "replace").rstrip("\r")
                if line:
                    out.write(_format(line) + "\n")
            out.flush()
            continue
        # Rotated (the file got shorter than what was read): start the new one.
        try:
            if os.path.getsize(log_path) < f.tell():
                f.close()
                f = _open_shared(log_path)
        except OSError:
            pass
        # Sleep until there may be news; wake at once if HandTrack exits.
        if not process or k32.WaitForSingleObject(process, 250) == 0:
            break
    return 0


def main(argv):
    """argv after --log-viewer: LOG PID OFFSET."""
    if sys.platform != "win32" or len(argv) < 3:
        return 2
    try:
        return run(argv[0], int(argv[1]), int(argv[2]))
    except (OSError, ValueError):
        return 1
