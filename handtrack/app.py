"""Application entry point: splash → models → main window."""

import os
import sys
import threading

from handtrack import APP_NAME, paths


def _windows_app_id():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("HandTrack.App")
        except Exception:
            pass


def main():
    logger = paths.setup_logging()
    _windows_app_id()

    from PySide6.QtCore import QObject, QPropertyAnimation, QTimer, Signal
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox

    from handtrack.config import Settings
    from handtrack.i18n import Translator
    from handtrack.ui import theme
    from handtrack.ui.overlays import Splash

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    if os.path.isfile(paths.ICON_PATH):
        app.setWindowIcon(QIcon(paths.ICON_PATH))

    settings = Settings.load()
    tr = Translator(settings.lang)
    theme.set_dark(settings.dark_mode)
    app.setStyleSheet(theme.stylesheet())

    splash = Splash("HandTrack", tr("app_subtitle"))
    splash.set_status(tr("splash_checking"))
    splash.show()

    class Loader(QObject):
        progress = Signal(str, object)
        done = Signal(object, object)

    loader = Loader()
    state = {}

    def load():
        try:
            from handtrack.vision.models import ensure_models
            ensure_models(lambda name, pct: loader.progress.emit(
                tr("downloading_model", name=name, pct=pct), pct))
            loader.progress.emit(tr("splash_loading"), None)
            from handtrack.engine import Engine  # imports mediapipe (slow)
            engine = Engine(settings)
            engine.create_landmarkers()
            loader.done.emit(engine, None)
        except Exception as exc:  # reported in the GUI thread
            logger.exception("Startup failed")
            loader.done.emit(None, exc)

    def on_done(engine, error):
        if error is not None:
            from handtrack.vision.models import ModelDownloadError
            splash.close()
            if isinstance(error, ModelDownloadError):
                title = tr("err_models_title")
                text = tr("err_model_download", name=error.name, dir=paths.MODELS_DIR, err=error.error)
            else:
                title = tr("err_startup_title")
                text = tr("err_startup", err=f"{type(error).__name__}: {error}", log=paths.LOGS_DIR)
            QMessageBox.critical(None, title, text)
            app.exit(1)
            return
        from handtrack.ui.main_window import MainWindow
        window = MainWindow(settings, engine)
        state["window"] = window
        window.setWindowOpacity(0.0)
        window.show()
        fade = QPropertyAnimation(window, b"windowOpacity", window)
        fade.setDuration(350)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.start()
        state["fade"] = fade
        QTimer.singleShot(120, splash.close)

    loader.progress.connect(lambda text, pct: splash.set_status(text, pct))
    loader.done.connect(on_done)
    threading.Thread(target=load, name="Startup", daemon=True).start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
