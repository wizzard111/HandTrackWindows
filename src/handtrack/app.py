"""Application entry point: splash → models → main window.

Command line:
    --self-test   load the models, process a few synthetic frames, exit 0/1
                  (used by the installers and CI; needs no camera or display)
    --request-camera  macOS: show the camera permission prompt, exit 0 if allowed
                  (the installer runs it; writes camera-permission.txt)
    --log-viewer LOG PID OFFSET  Windows: the log window (started by HandTrack itself)
    --version     print the version
"""

import os
import sys
import threading

from handtrack import APP_NAME, __version__, paths


def _enable_crash_log():
    """On a hard crash (e.g. an access violation in native code) write every
    thread's Python stack to logs/crash.log, so the cause can be found."""
    import faulthandler
    try:
        path = os.path.join(paths.LOGS_DIR, "crash.log")
        if os.path.isfile(path) and os.path.getsize(path) > 256 * 1024:
            os.replace(path, path + ".1")      # keep one old file, start a new one
        f = open(path, "a", encoding="utf-8")
        f.write(f"\n--- HandTrack {__version__} started ---\n")
        f.flush()
        faulthandler.enable(file=f, all_threads=True)
        _enable_crash_log.file = f      # keep it open for the process lifetime
    except OSError:
        pass


def _windows_app_id():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("HandTrack.App")
        except Exception:
            pass


def self_test():
    """Exercise the real pipeline headlessly. Returns a process exit code."""
    import time
    import numpy as np
    from handtrack.config import Settings
    from handtrack.engine import Engine
    from handtrack.vision.models import ensure_models
    try:
        ensure_models()
        settings = Settings(hide_face=True, gaze=True, draw_enabled=True, preview_visible=True)
        engine = Engine(settings)
        engine.create_landmarkers()
        frame = np.random.default_rng(0).integers(0, 255, (360, 640, 3), dtype=np.uint8)
        state = {"frame_id": 0, "hand_used": -1, "face_used": -1, "hand_submit": 0.0,
                 "face_submit": 0.0, "face_seen": time.monotonic(), "last_pattern": None,
                 "primary_key": None, "triggers": {}, "fps_t": time.monotonic(), "fps_n": 0,
                 "fps": 0.0, "stats_t": 0.0, "announced": True}
        for _ in range(10):
            engine._process(frame, state)
            engine.preview_consumed()
            time.sleep(0.02)
        engine.shutdown()
        from handtrack import vcam  # noqa: F401  (import check of the platform backend)
    except Exception as exc:
        print(f"SELF-TEST FAILED: {type(exc).__name__}: {exc}")
        return 1
    print(f"HandTrack {__version__} self-test OK")
    return 0


def request_camera():
    """Installer step (macOS): show the camera permission prompt for HandTrack.app,
    wait for the answer, record it in the data folder. Exit 0 when allowed."""
    from handtrack import camera_access
    granted = camera_access.request()
    state = camera_access.status()
    try:
        with open(os.path.join(paths.DATA_DIR, "camera-permission.txt"), "w", encoding="utf-8") as f:
            f.write(state + "\n")
    except OSError:
        pass
    return 0 if granted else 1


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--log-viewer"]:          # the log window process: nothing else loads
        from handtrack import logviewer
        return logviewer.main(argv[1:])
    if "--version" in argv:
        print(__version__)
        return 0
    logger = paths.setup_logging()
    _enable_crash_log()
    if "--self-test" in argv:
        return self_test()
    if "--request-camera" in argv:
        return request_camera()
    _windows_app_id()

    from PySide6.QtCore import QObject, QPropertyAnimation, QTimer, Signal
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox

    from handtrack.config import Settings
    from handtrack.i18n import Translator
    from handtrack.ui import theme
    from handtrack.ui.overlays import Splash

    # A GUI build of OpenCV points Qt at its own plugin folder when imported
    # (breaks PySide6 on Linux/Wayland). HandTrack uses Qt's own plugins.
    for var in ("QT_QPA_PLATFORM_PLUGIN_PATH", "QT_QPA_FONTDIR"):
        if "cv2" in os.environ.get(var, ""):
            del os.environ[var]
    app = QApplication(sys.argv[:1])
    # Before any worker thread starts: garbage is collected on this thread only.
    from handtrack.ui.gc_guard import GuiThreadGC
    app._gc_guard = GuiThreadGC(app)

    from handtrack import single_instance
    if single_instance.notify_running_instance():
        logger.info("HandTrack is already running: showed its window instead")
        return 0
    instance_server = single_instance.InstanceServer(app)
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName("handtrack")  # Wayland: match the .desktop entry for the icon
    app.setStyle("Fusion")
    if os.path.isfile(paths.ICON_PATH):
        app.setWindowIcon(QIcon(paths.ICON_PATH))

    settings = Settings.load()
    from handtrack import logwindow
    logwindow.mark_session_start(paths.LOG_FILE)
    logwindow.capture_native_output()   # MediaPipe/OpenCV messages into the log
    if settings.log_window:
        logwindow.open_log_window(logger, paths.LOG_FILE)
    import platform
    logger.info("HandTrack %s starting (Python %s, %s)", __version__, platform.python_version(),
                platform.platform())
    tr = Translator()
    theme.set_dark(settings.dark_mode)
    theme.load_fonts()
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
            import time
            t0 = time.monotonic()
            from handtrack.vision.models import ensure_models
            ensure_models(lambda name, pct: loader.progress.emit(
                tr("downloading_model", name=name, pct=pct), pct))
            loader.progress.emit(tr("splash_loading"), None)
            from handtrack.engine import Engine  # imports mediapipe (slow)
            engine = Engine(settings)
            engine.create_landmarkers()
            logger.info("Recognition models ready in %.1f s", time.monotonic() - t0)
            # The engine was created on this short-lived thread; hand it to the
            # GUI thread, or queued calls into it (preview_consumed) would be
            # posted to a dead thread and the preview would freeze on frame 1.
            engine.moveToThread(app.thread())
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
        instance_server.activate.connect(window.bring_to_front)
        window.setWindowOpacity(0.0)
        window.show()
        fade = QPropertyAnimation(window, b"windowOpacity", window)
        fade.setDuration(320)
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
