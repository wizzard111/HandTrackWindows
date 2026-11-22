"""One HandTrack per user.

Two copies would fight over the webcam and the virtual camera. The first one
listens on a local socket (a named pipe on Windows); a second launch connects,
asks it to show its window and exits before loading anything heavy.
HANDTRACK_ALLOW_MULTIPLE=1 turns this off (benchmarks, tests).
"""

import getpass
import logging
import os
import re

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

logger = logging.getLogger("handtrack")
_MESSAGE = b"show\n"


def server_name():
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    return "HandTrack-" + re.sub(r"[^A-Za-z0-9_.-]", "_", user)


def notify_running_instance(timeout_ms=500):
    """True if another HandTrack answered (and was asked to show itself)."""
    if os.environ.get("HANDTRACK_ALLOW_MULTIPLE"):
        return False
    sock = QLocalSocket()
    sock.connectToServer(server_name())
    if not sock.waitForConnected(timeout_ms):
        return False
    if os.name == "nt":
        # This launch is in the foreground; let the running copy take the
        # foreground too, or Windows only flashes its taskbar button.
        try:
            import ctypes
            ctypes.windll.user32.AllowSetForegroundWindow(-1)   # ASFW_ANY
        except Exception:
            pass
    sock.write(_MESSAGE)
    sock.waitForBytesWritten(timeout_ms)
    sock.disconnectFromServer()
    return True


class InstanceServer(QObject):
    """Listens for later launches; emits ``activate`` when one asks to be shown."""

    activate = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._server = QLocalServer(self)
        if os.environ.get("HANDTRACK_ALLOW_MULTIPLE"):
            return
        name = server_name()
        if not self._server.listen(name):
            # A socket file left by a crashed run (Linux/macOS): remove and retry.
            QLocalServer.removeServer(name)
            if not self._server.listen(name):
                logger.warning("Single-instance server unavailable: %s", self._server.errorString())
                return
        self._server.newConnection.connect(self._on_connection)

    def _on_connection(self):
        while self._server.hasPendingConnections():
            conn = self._server.nextPendingConnection()
            conn.readyRead.connect(lambda c=conn: self._on_ready(c))
            conn.disconnected.connect(conn.deleteLater)

    def _on_ready(self, conn):
        if bytes(conn.readAll()).startswith(b"show"):
            logger.info("Another launch asked this HandTrack to show its window")
            self.activate.emit()
