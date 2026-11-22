# PyInstaller spec — Windows, one-folder, windowed. Run via packaging\windows\build.ps1.
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
DRIVER = True
EXTRA_DATAS = []
EXTRA_EXCLUDES = ["pyvirtualcam"]
HIDDEN_IMPORTS = ["pyautogui"]  # imported lazily, invisible to the analysis
exec(open(os.path.join(ROOT, "packaging", "common.spec.py"), encoding="utf-8").read())

exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="HandTrack",
    icon=os.path.join(ROOT, "src", "handtrack", "assets", "icon.ico"),
    console=False, version=os.path.join(ROOT, "build", "version_info.txt"), upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="HandTrack", upx=False)
