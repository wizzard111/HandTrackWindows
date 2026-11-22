"""Short interface sounds, played by the operating system.

No audio library in the app (Qt Multimedia alone would add tens of MB and an
audio thread): Windows plays WAV files natively through winsound, Linux uses
whichever of pw-play / paplay / aplay is installed, macOS uses afplay. Every
call returns at once; a missing player or file is silently skipped.
"""

import logging
import os
import shutil
import subprocess
import sys

from handtrack import paths

logger = logging.getLogger("handtrack")
_player = None


def _unix_player():
    global _player
    if _player is None:
        if sys.platform == "darwin":
            _player = ["afplay"] if shutil.which("afplay") else []
        else:
            for cmd in (["pw-play"], ["paplay"], ["aplay", "-q"]):
                if shutil.which(cmd[0]):
                    _player = cmd
                    break
            else:
                _player = []
    return _player


def play(name):
    """Play assets/sounds/<name>.wav without blocking."""
    path = os.path.join(paths.SOUNDS_DIR, f"{name}.wav")
    if not os.path.isfile(path):
        return
    try:
        if sys.platform == "win32":
            import threading
            import winsound
            # PlaySound reads the file before it returns (~20 ms): keep that off the UI thread.
            flags = winsound.SND_FILENAME | winsound.SND_NODEFAULT
            threading.Thread(target=winsound.PlaySound, args=(path, flags), name="Sound", daemon=True).start()
            return
        player = _unix_player()
        if player:
            subprocess.Popen([*player, path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
    except Exception:
        logger.exception("Could not play sound %s", name)
