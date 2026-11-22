"""Copy the shared code from this (Windows) repository into the Linux and macOS
repositories next to it, so all three ship identical program code.

    python packaging/sync_repos.py [../handlinux ../handmac]

Shared: src/, tests/, docs/, LICENSE, .gitattributes, .gitignore and the
platform-neutral files in packaging/. Each repository keeps its own README,
HOW-TO-INSTALL.txt, installer/uninstaller, packaging/<os>/ and CI workflow.
"""

import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHARED_DIRS = ("src", "tests", "docs")
SHARED_FILES = ("LICENSE", ".gitattributes", ".gitignore",
                "packaging/common.spec.py", "packaging/fetch_deps.py", "packaging/launcher.py",
                "packaging/make_icon.py", "packaging/make_screenshots.py", "packaging/benchmark.py",
                "packaging/requirements.txt", "packaging/overrides.txt",
                "packaging/requirements-dev.txt")
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache")


def sync(target):
    target = os.path.abspath(target)
    if not os.path.isdir(target):
        raise SystemExit(f"not a directory: {target}")
    for d in SHARED_DIRS:
        dst = os.path.join(target, d)
        shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(os.path.join(ROOT, d), dst, ignore=IGNORE)
    for f in SHARED_FILES:
        dst = os.path.join(target, f)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(ROOT, f), dst)
    print(f"synced -> {target}")


if __name__ == "__main__":
    targets = sys.argv[1:] or [os.path.join(ROOT, "..", "handlinux"), os.path.join(ROOT, "..", "handmac")]
    for t in targets:
        sync(t)
