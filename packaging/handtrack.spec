# PyInstaller spec — one-folder, windowed build.
# Run through packaging/build.ps1, which fetches models and the driver first.
import os

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
DEPS = os.path.join(ROOT, "build", "deps")

datas = [
    (os.path.join(ROOT, "assets"), "assets"),
    (os.path.join(DEPS, "models"), "models"),
    (os.path.join(DEPS, "driver"), "driver"),
]
datas += collect_data_files("mediapipe", includes=["**/*.binarypb", "**/*.tflite", "**/*.txt"])
binaries = collect_dynamic_libs("mediapipe")

a = Analysis(
    [os.path.join(ROOT, "packaging", "launcher.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=[],
    # matplotlib stays: mediapipe's vision package imports it at import time.
    excludes=[
        "pyvirtualcam", "tkinter", "scipy", "pandas", "IPython", "jax", "jaxlib", "torch",
        "tensorflow", "sounddevice", "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick",
        "PySide6.QtWebEngineCore", "PySide6.QtMultimedia", "PySide6.QtPdf", "PySide6.QtSql",
        "PySide6.QtOpenGL", "PySide6.QtDBus", "PySide6.QtSvg",
    ],
    noarchive=False,
)

# Files that are never used: FFmpeg (only needed to decode video files; the
# webcam goes through DirectShow), Qt's software OpenGL and Qt translations.
_DROP = ("opencv_videoio_ffmpeg", "opengl32sw.dll")
a.binaries = [b for b in a.binaries if not any(x in os.path.basename(b[0]) for x in _DROP)]
a.datas = [d for d in a.datas if "PySide6/translations" not in d[0].replace("\\", "/")
           and "PySide6\\translations" not in d[0]]
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HandTrack",
    icon=os.path.join(ROOT, "assets", "icon.ico"),
    console=False,
    version=os.path.join(ROOT, "build", "version_info.txt"),
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="HandTrack", upx=False)
