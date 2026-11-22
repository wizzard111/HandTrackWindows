"""A separate window with the live log, opened at startup (setting: log_window).

The window is its own process that follows the log file and quits by itself
once HandTrack exits, so closing it never affects the program:

* Windows: a classic console (conhost.exe) running a small PowerShell loop;
  warnings are yellow, errors red.
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
        if sys.platform == "win32":
            return _windows_window(log_path)
        return _terminal_tail(log_path)
    except Exception:
        logger.exception("Could not open the log window")
        return False


# Follows the log like tail -f, reopens it after rotation, quits with HandTrack.
_PS_VIEWER = r"""
$ErrorActionPreference = 'SilentlyContinue'
$Host.UI.RawUI.WindowTitle = '__TITLE__'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$log = '__LOG__'; $appPid = __PID__; $start = __OFFSET__
try { $Host.UI.RawUI.BufferSize = New-Object Management.Automation.Host.Size(160, 3000)
      $Host.UI.RawUI.WindowSize = New-Object Management.Automation.Host.Size(160, 36) } catch { }
# "2026-01-01 12:00:00,123 | LEVEL | Thread | message" -> "12:00:00  LEVEL  message"
function Show($line) {
    if (-not $line) { return }
    $c = 'Gray'
    if ($line -match '^\S+ (\d\d:\d\d:\d\d),\d+ \| (\w+) \| ([^|]+) \| (.*)$') {
        $level = $Matches[2]; $thread = $Matches[3].Trim(); $msg = $Matches[4]
        if ($level -match 'WARN') { $c = 'Yellow' }
        elseif ($level -match 'ERROR|CRITICAL') { $c = 'Red' }
        elseif ($thread -eq 'NativeOutput') { $c = 'DarkGray' }
        else { $c = 'White' }
        $line = '{0}  {1,-7}  {2}' -f $Matches[1], $level, $msg
    }
    Write-Host $line -ForegroundColor $c
}
function Open-Log { $fs = [IO.File]::Open($log, 'OpenOrCreate', 'Read', 'ReadWrite,Delete'); New-Object IO.StreamReader($fs, [Text.Encoding]::UTF8) }
Write-Host "HandTrack log  ($log)" -ForegroundColor DarkGray
Write-Host "This window closes by itself when HandTrack exits." -ForegroundColor DarkGray
Write-Host ""
$r = Open-Log
if ($start -le $r.BaseStream.Length) { $r.BaseStream.Position = $start; $r.DiscardBufferedData() }   # this run only
while (Get-Process -Id $appPid) {
    $line = $r.ReadLine()
    if ($null -ne $line) { Show $line; continue }
    Start-Sleep -Milliseconds 200
    $len = (Get-Item -LiteralPath $log).Length
    if ($len -lt $r.BaseStream.Position) { $r.Close(); $r = Open-Log }   # rotated
}
"""


def _windows_window(log_path):
    script = (_PS_VIEWER.replace("__TITLE__", TITLE)
              .replace("__LOG__", log_path.replace("'", "''"))
              .replace("__PID__", str(os.getpid()))
              .replace("__OFFSET__", str(os.path.getsize(log_path) if os.path.isfile(log_path) else 0)))
    import base64
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    windir = os.environ.get("SystemRoot", r"C:\Windows")
    powershell = os.path.join(windir, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    conhost = os.path.join(windir, "System32", "conhost.exe")
    # conhost.exe forces a classic console window even where Windows Terminal is
    # the default; fall back to a plain new console otherwise.
    args = [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded]
    if os.path.isfile(conhost):
        subprocess.Popen([conhost, *args], close_fds=True)
    else:
        subprocess.Popen(args, creationflags=subprocess.CREATE_NEW_CONSOLE, close_fds=True)
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
