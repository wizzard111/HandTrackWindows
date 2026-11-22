"""System-wide hotkey (works while another app is focused or HandTrack is in the tray).

Bindings are strings like "ctrl+alt+h": modifiers (ctrl, alt, shift, win) and
one key (a-z, 0-9, f1-f24, space, enter, tab, esc, backspace, delete, insert,
home, end, pageup, pagedown, up, down, left, right, printscreen, pause, or a
punctuation character). At least one modifier is required, so a plain key is
never taken away from other programs.

Windows   RegisterHotKey on a small thread with its own message loop.
Linux     XGrabKey on the X11 root window (python-xlib). Wayland does not let
          applications grab keys globally, so there it is unavailable.
macOS     not available yet (needs the Accessibility permission and pyobjc).
"""

import logging
import os
import sys
import threading

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger("handtrack")

DEFAULT_HIDE_FACE = "ctrl+alt+h"
MODIFIER_NAMES = {"ctrl": "ctrl", "control": "ctrl", "alt": "alt", "option": "alt",
                  "shift": "shift", "win": "win", "meta": "win", "super": "win", "command": "win"}
_NAMED_KEYS = ("space", "enter", "tab", "esc", "backspace", "delete", "insert", "home", "end",
               "pageup", "pagedown", "up", "down", "left", "right", "printscreen", "pause")


def parse(binding):
    """"ctrl+alt+h" -> (frozenset({"ctrl", "alt"}), "h"); raises ValueError."""
    parts = [p.strip().lower() for p in (binding or "").split("+") if p.strip()]
    mods, keys = set(), []
    for part in parts:
        if part in MODIFIER_NAMES:
            mods.add(MODIFIER_NAMES[part])
        else:
            keys.append(part)
    if len(keys) != 1:
        raise ValueError("needs exactly one key besides the modifiers")
    key = keys[0]
    valid = (len(key) == 1 or key in _NAMED_KEYS
             or (key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24))
    if not valid:
        raise ValueError(f"unknown key: {key}")
    if not mods:
        raise ValueError("needs at least one modifier (Ctrl, Alt, Shift or Win)")
    return frozenset(mods), key


def display_text(binding):
    """"ctrl+alt+h" -> "Ctrl + Alt + H" (modifiers in a fixed order)."""
    try:
        mods, key = parse(binding)
    except ValueError:
        return binding or ""
    order = [m for m in ("ctrl", "alt", "shift", "win") if m in mods]
    names = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win"}
    return " + ".join([names[m] for m in order] + [key.upper() if len(key) == 1 else key.capitalize()])


def unavailable_reason():
    """None when global hotkeys work here, else a short explanation."""
    if sys.platform == "win32":
        return None
    if sys.platform == "darwin":
        return "Global hotkeys are not available on macOS yet."
    if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or (
            os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY")):
        return "Wayland does not let apps use global hotkeys; they work in an X11 session."
    try:
        import Xlib  # noqa: F401
    except ImportError:
        return "python-xlib is missing."
    if not os.environ.get("DISPLAY"):
        return "No X11 display."
    return None


class GlobalHotkey(QObject):
    """One global hotkey; emits ``triggered`` on the GUI thread when pressed."""

    triggered = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._backend = None
        self.binding = ""
        self.error = None

    def set_binding(self, binding):
        """Register ``binding`` (or nothing for ""). Returns None or an error text."""
        self.stop()
        self.binding, self.error = binding, None
        if not binding:
            return None
        reason = unavailable_reason()
        if reason:
            self.error = reason
            return reason
        try:
            mods, key = parse(binding)
        except ValueError as exc:
            self.error = str(exc)
            return self.error
        backend = _WindowsBackend(self) if sys.platform == "win32" else _X11Backend(self)
        self.error = backend.start(mods, key)
        if self.error is None:
            self._backend = backend
            logger.info("Global hotkey %s registered", display_text(binding))
        else:
            logger.warning("Global hotkey %s not registered: %s", binding, self.error)
        return self.error

    def stop(self):
        if self._backend is not None:
            self._backend.stop()
            self._backend = None


# ------------------------------------------------------------------ Windows ----
class _WindowsBackend:
    _VK = {"space": 0x20, "enter": 0x0D, "tab": 0x09, "esc": 0x1B, "backspace": 0x08,
           "delete": 0x2E, "insert": 0x2D, "home": 0x24, "end": 0x23, "pageup": 0x21,
           "pagedown": 0x22, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
           "printscreen": 0x2C, "pause": 0x13}
    _MODS = {"alt": 0x1, "ctrl": 0x2, "shift": 0x4, "win": 0x8}

    def __init__(self, owner):
        self._owner = owner
        self._thread = None
        self._thread_id = None

    def _vk(self, key):
        import ctypes
        if key in self._VK:
            return self._VK[key]
        if key.startswith("f") and key[1:].isdigit():
            return 0x70 + int(key[1:]) - 1
        if key.isalnum():
            return ord(key.upper())
        code = ctypes.windll.user32.VkKeyScanW(ord(key))
        return None if code == -1 else code & 0xFF

    def start(self, mods, key):
        vk = self._vk(key)
        if vk is None:
            return f"unknown key: {key}"
        flags = 0x4000                                  # MOD_NOREPEAT
        for m in mods:
            flags |= self._MODS[m]
        ready, result = threading.Event(), {}
        self._thread = threading.Thread(target=self._loop, args=(flags, vk, ready, result),
                                        name="Hotkey", daemon=True)
        self._thread.start()
        ready.wait(2.0)
        return result.get("error", "the hotkey thread did not start")

    def _loop(self, flags, vk, ready, result):
        import ctypes
        from ctypes import wintypes
        user32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
        self._thread_id = k32.GetCurrentThreadId()
        if not user32.RegisterHotKey(None, 1, flags, vk):
            result["error"] = "this combination is already used by another program"
            ready.set()
            return
        result["error"] = None
        ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == 0x0312:                   # WM_HOTKEY
                self._owner.triggered.emit()
        user32.UnregisterHotKey(None, 1)

    def stop(self):
        import ctypes
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)   # WM_QUIT
        if self._thread is not None:
            self._thread.join(1.0)


# --------------------------------------------------------------------- X11 ----
class _X11Backend:
    _KEYSYMS = {"space": "space", "enter": "Return", "tab": "Tab", "esc": "Escape",
                "backspace": "BackSpace", "delete": "Delete", "insert": "Insert", "home": "Home",
                "end": "End", "pageup": "Prior", "pagedown": "Next", "left": "Left", "up": "Up",
                "right": "Right", "down": "Down", "printscreen": "Print", "pause": "Pause"}

    def __init__(self, owner):
        self._owner = owner
        self._stop = threading.Event()
        self._thread = None
        self._display = None

    def start(self, mods, key):
        from Xlib import X, XK, display, error
        try:
            d = display.Display()
        except Exception as exc:
            return f"cannot open the X11 display: {exc}"
        name = self._KEYSYMS.get(key) or (key.upper() if key.startswith("f") and len(key) > 1 else key)
        keysym = XK.string_to_keysym(name)
        if not keysym and len(key) == 1:
            keysym = ord(key)
        keycode = d.keysym_to_keycode(keysym)
        if not keycode:
            d.close()
            return f"unknown key: {key}"
        mask = 0
        for m, bit in (("ctrl", X.ControlMask), ("shift", X.ShiftMask), ("alt", X.Mod1Mask),
                       ("win", X.Mod4Mask)):
            if m in mods:
                mask |= bit
        root = d.screen().root
        catcher = error.CatchError(error.BadAccess)
        # Also grab with Caps Lock / Num Lock on, or the hotkey dies with them.
        for extra in (0, X.LockMask, X.Mod2Mask, X.LockMask | X.Mod2Mask):
            root.grab_key(keycode, mask | extra, True, X.GrabModeAsync, X.GrabModeAsync, onerror=catcher)
        d.sync()
        if catcher.get_error():
            d.close()
            return "this combination is already used by another program"
        self._display = d
        self._thread = threading.Thread(target=self._loop, name="Hotkey", daemon=True)
        self._thread.start()
        return None

    def _loop(self):
        import select
        from Xlib import X
        d = self._display
        while not self._stop.is_set():
            readable, _, _ = select.select([d.fileno()], [], [], 0.5)
            if not readable:
                continue
            while d.pending_events():
                if d.next_event().type == X.KeyPress:
                    self._owner.triggered.emit()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(1.0)
        if self._display is not None:
            try:
                self._display.close()
            except Exception:
                pass
