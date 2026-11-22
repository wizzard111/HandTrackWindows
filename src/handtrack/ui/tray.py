"""System tray icon: quick controls, and closing the window keeps HandTrack running.

Left click shows or hides the window. The menu starts/stops the camera,
toggles streaming and face hiding, opens the log and quits. While the camera
runs the icon carries a red dot. Where the desktop has no tray (e.g. GNOME
without an extension) the window simply closes the app, as before.
"""

from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from handtrack import paths


def tray_available():
    return QSystemTrayIcon.isSystemTrayAvailable()


def _live_icon(base):
    """The app icon with a red dot in the corner."""
    pix = base.pixmap(64, 64)
    if pix.isNull():
        pix = QPixmap(64, 64)
        pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QColor("#000000"))
    p.setBrush(QColor("#d4142f"))
    p.drawEllipse(QPointF(50, 50), 12, 12)
    p.end()
    return QIcon(pix)


class Tray(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        tr = window.tr
        self._icon = QIcon(paths.ICON_PATH)
        self._icon_live = _live_icon(self._icon)
        self._told_hidden = False

        self.icon = QSystemTrayIcon(self._icon, window)
        menu = QMenu(window)
        self.open_action = QAction(tr("tray_open"), menu)
        self.open_action.triggered.connect(self.show_window)
        self.run_action = QAction(tr("tray_start"), menu)
        self.run_action.triggered.connect(window.toggle_running)
        self.vcam_action = QAction(tr("vcam_cb"), menu, checkable=True)
        self.vcam_action.triggered.connect(lambda on: window.set_setting("vcam", on))
        self.hide_action = QAction(tr("hide_face_cb"), menu, checkable=True)
        self.hide_action.triggered.connect(lambda on: window.set_setting("hide_face", on))
        log_action = QAction(tr("tray_log"), menu)
        log_action.triggered.connect(window.show_log)
        quit_action = QAction(tr("tray_quit"), menu)
        quit_action.triggered.connect(window.quit_app)

        menu.addAction(self.open_action)
        menu.addSeparator()
        menu.addAction(self.run_action)
        menu.addAction(self.vcam_action)
        menu.addAction(self.hide_action)
        menu.addSeparator()
        menu.addAction(log_action)
        menu.addAction(quit_action)
        self.menu = menu
        self.icon.setContextMenu(menu)
        self.icon.activated.connect(self._on_activated)
        self.refresh()
        self.icon.show()

    def _on_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            if self.window.isVisible() and not self.window.isMinimized():
                self.window.hide()
            else:
                self.show_window()

    def show_window(self):
        w = self.window
        w.showNormal()
        w.raise_()
        w.activateWindow()

    def refresh(self):
        tr, w = self.window.tr, self.window
        running = w.camera_state != "stopped"
        live = w.camera_state == "live"
        self.run_action.setText(tr("tray_stop") if running else tr("tray_start"))
        self.vcam_action.setChecked(w.settings.vcam)
        self.hide_action.setChecked(w.settings.hide_face)
        self.icon.setIcon(self._icon_live if live else self._icon)
        self.icon.setToolTip(tr("tray_tip_live") if live else tr("tray_tip_stopped"))

    def notify_hidden(self):
        """Once per run: tell the user the app went to the tray."""
        if self._told_hidden:
            return
        self._told_hidden = True
        tr = self.window.tr
        self.icon.showMessage(tr("tray_hidden_title"), tr("tray_hidden_msg"), self._icon, 4000)

    def remove(self):
        self.icon.hide()
