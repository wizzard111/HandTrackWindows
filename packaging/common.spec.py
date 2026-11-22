# Shared PyInstaller analysis for all platforms (exec'd by the per-OS .spec files).
# Expects ROOT and DRIVER (bool) to be defined by the caller.
import os

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

SRC = os.path.join(ROOT, "src")
DEPS = os.path.join(ROOT, "build", "deps")

datas = [
    (os.path.join(SRC, "handtrack", "assets"), os.path.join("handtrack", "assets")),
    (os.path.join(DEPS, "models"), "models"),
]
if DRIVER:
    datas.append((os.path.join(DEPS, "driver"), "driver"))
if EXTRA_DATAS:
    datas += EXTRA_DATAS
datas += collect_data_files("mediapipe", includes=["**/*.binarypb", "**/*.tflite", "**/*.txt"])

# Not used at runtime (tests/test_packaging.py checks the app imports none of
# them). matplotlib is replaced by an inert stub in engine.py
# (mediapipe imports it only for a debug plot helper); Pillow is not needed.
EXCLUDES = [
    "matplotlib", "PIL", "tkinter", "scipy", "pandas", "IPython", "jax", "jaxlib", "torch",
    "tensorflow", "sounddevice", "unittest", "pydoc", "doctest", "pdb", "lib2to3", "xmlrpc",
    "sqlite3", "curses", "PySide6.QtQml", "PySide6.QtQuick",
    "PySide6.QtWebEngineCore", "PySide6.QtMultimedia", "PySide6.QtPdf", "PySide6.QtSql",
    "PySide6.QtOpenGL", "PySide6.QtDBus",
] + EXTRA_EXCLUDES

a = Analysis(
    [os.path.join(ROOT, "packaging", "launcher.py")],
    pathex=[SRC],
    binaries=collect_dynamic_libs("mediapipe"),
    datas=datas,
    hiddenimports=HIDDEN_IMPORTS,
    excludes=EXCLUDES,
    noarchive=False,
    optimize=1,
)

# Never used: FFmpeg (only decodes video files; webcams use DirectShow /
# AVFoundation / V4L2), Qt's software OpenGL, Qt translations.
# (On Linux cv2 links libavcodec directly, so only the Windows FFmpeg plugin may go.)
_DROP = ("opencv_videoio_ffmpeg", "opengl32sw", "libQt6Pdf", "Qt6Pdf")
a.binaries = [b for b in a.binaries if not any(x in os.path.basename(b[0]) for x in _DROP)]
a.datas = [d for d in a.datas if not d[0].replace("\\", "/").startswith("PySide6/translations")]
pyz = PYZ(a.pure)
