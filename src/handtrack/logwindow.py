"""A separate window with the live log, opened at startup (setting: log_window).

The window is its own process that follows the log file and quits by itself
once HandTrack exits, so closing it never affects the program:

* Windows: a second, tiny HandTrack process with its own console
  (logviewer.py; ~10 MB, idle between lines); warnings are yellow, errors red.
* Linux / macOS: a terminal window running tail -f.

Native libraries (MediaPipe, OpenCV) print to the process's stdout/stderr,
which a windowed app has nowhere to show. capture_native_output() routes both
into the log, so their messages reach the file and the window too.

Started from a terminal already (a developer run), the log also goes there.
"""

import logging
import os
import shlex
import shutil
import subprocess
import sys
import threading

TITLE = "HandTrack - log"
_native = logging.getLogger("handtrack.native")
_session_offset = None   # log file size when this run started: windows show this run only


def mark_session_start(log_path):
    global _session_offset
    if _session_offset is None:
        _session_offset = os.path.getsize(log_path) if os.path.isfile(log_path) else 0


def capture_native_output():
    """Send everything written to fd 1/2 (also by C/C++ code) to the log."""
    if sys.stderr is not None and getattr(sys.stderr, "isatty", lambda: False)():
        return  # a terminal shows it already
    try:
        read_fd, write_fd = os.pipe()
        for fd in (1, 2):
            os.dup2(write_fd, fd)
        if sys.platform == "win32":
            # Native DLLs with their own C runtime take the Win32 std handles.
            import ctypes
            import msvcrt
            k32 = ctypes.WinDLL("kernel32")
            k32.SetStdHandle.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
            handle = msvcrt.get_osfhandle(write_fd)
            for std in (-11 & 0xFFFFFFFF, -12 & 0xFFFFFFFF):  # STD_OUTPUT_HANDLE, STD_ERROR_HANDLE
                k32.SetStdHandle(std, handle)
        stream = os.fdopen(write_fd, "w", encoding="utf-8", errors="replace", buffering=1)
        sys.stdout = sys.stderr = stream
    except OSError:
        return

    def pump():
        with os.fdopen(read_fd, "r", encoding="utf-8", errors="replace") as pipe:
            for line in pipe:
                line = line.rstrip()
                if line:
                    _native.info(line)

    threading.Thread(target=pump, name="NativeOutput", daemon=True).start()


def open_log_window(logger, log_path):
    """Opens the log window; returns True on success."""
    try:
        if sys.stderr is not None and getattr(sys.stderr, "isatty", lambda: False)():
            handler = logging.StreamHandler(sys.stderr)
            handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s", "%H:%M:%S"))
            logger.addHandler(handler)
            return True
        return show_log_window(log_path)
    except Exception:
        logger.exception("Could not open the log window")
        return False


def show_log_window(log_path):
    """Opens one more log window (tray menu "Show log")."""
    mark_session_start(log_path)
    if sys.platform == "win32":
        return _windows_window(log_path)
    return _terminal_tail(log_path)


def _windows_window(log_path):
    """A second, tiny HandTrack process with its own console (see logviewer.py)."""
    from handtrack import paths
    tail = ["--log-viewer", log_path, str(os.getpid()), str(_session_offset or 0)]
    if paths.FROZEN:
        cmd, cwd = [sys.executable, *tail], None
    else:
        exe = sys.executable
        windowless = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.basename(exe).lower() == "python.exe" and os.path.isfile(windowless):
            exe = windowless                      # the viewer opens its own console
        package_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cmd, cwd = [exe, "-m", "handtrack", *tail], package_parent
    env = dict(os.environ, HANDTRACK_ALLOW_MULTIPLE="1")
    subprocess.Popen(cmd, cwd=cwd, env=env, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


_TERMINALS = (
    ("x-terminal-emulator", ["-e"]), ("gnome-terminal", ["--"]), ("konsole", ["-e"]),
    ("kgx", ["--"]), ("ptyxis", ["--"]), ("xfce4-terminal", ["-x"]), ("mate-terminal", ["-x"]),
    ("kitty", []), ("alacritty", ["-e"]), ("foot", []), ("wezterm", ["start", "--"]), ("xterm", ["-e"]),
)


def _terminal_tail(log_path):
    pid = os.getpid()
    script = (f"printf '\\033]0;{TITLE}\\007'; tail -n 40 -F {shlex.quote(log_path)} & T=$!; "
              f"while kill -0 {pid} 2>/dev/null; do sleep 1; done; kill $T 2>/dev/null")
    if sys.platform == "darwin":
        apple = 'tell application "Terminal" to do script "{}"'.format(
            script.replace("\\", "\\\\").replace('"', '\\"'))
        subprocess.Popen(["osascript", "-e", apple], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    for name, args in _TERMINALS:
        exe = shutil.which(name)
        if exe:
            subprocess.Popen([exe, *args, "sh", "-c", script], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            return True
    return False
