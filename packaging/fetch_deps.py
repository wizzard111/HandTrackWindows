"""Download build-time binaries: MediaPipe models and the Unity Capture driver.

The driver DLLs are pinned to a commit and verified by SHA-256, so a
compromised or changed upstream file can never end up in the installer.
"""

import hashlib
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from handtrack.vision.models import MODELS  # noqa: E402

UNITY_CAPTURE_COMMIT = "3ed54c325e0ad71afcf4f246c07e5e17b3d7f2d2"
UNITY_CAPTURE_BASE = f"https://github.com/schellingb/UnityCapture/raw/{UNITY_CAPTURE_COMMIT}/"
DRIVER_FILES = {
    "UnityCaptureFilter64.dll": "72812f5363d8ecb45632253f8c8c888844b1b62e27616f3c8cc21064ccde25e5",
    "UnityCaptureFilter32.dll": "aa3ebdf03dea7f3aab3dd7b724751f49ed71672256b57c6a19aa6809cabf30ba",
}


def download(url, target):
    print(f"  {url}")
    tmp = target + ".part"
    with urllib.request.urlopen(url, timeout=60) as resp, open(tmp, "wb") as out:
        while chunk := resp.read(1 << 20):
            out.write(chunk)
    os.replace(tmp, target)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    """fetch_deps.py [DEST]   DEST defaults to build/deps; gets models/ and, on Windows, driver/."""
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dest = os.path.abspath(args[0]) if args else os.path.join(ROOT, "build", "deps")
    models_dir = os.path.join(dest, "models")
    os.makedirs(models_dir, exist_ok=True)

    print("MediaPipe models:")
    for _name, filename, url in MODELS:
        target = os.path.join(models_dir, filename)
        if not os.path.isfile(target):
            download(url, target)

    if sys.platform == "win32" or "--driver" in sys.argv:
        driver_dir = os.path.join(dest, "driver")
        os.makedirs(driver_dir, exist_ok=True)
        print("Unity Capture driver:")
        for filename, digest in DRIVER_FILES.items():
            target = os.path.join(driver_dir, filename)
            if not os.path.isfile(target) or sha256(target) != digest:
                download(UNITY_CAPTURE_BASE + "Install/" + filename, target)
            actual = sha256(target)
            if actual != digest:
                os.remove(target)
                raise SystemExit(f"SHA-256 mismatch for {filename}: {actual}")
    print("done")


if __name__ == "__main__":
    main()
