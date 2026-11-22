"""Measure HandTrack's CPU and memory use in typical situations.

    PYTHONPATH=src python packaging/benchmark.py --video CLIP [--seconds 20] [--out results.json]

CLIP is any video file; it replaces the webcam (HANDTRACK_VIDEO_SOURCE) and
loops at its frame rate, so every OS measures the same input. Use
--video camera to measure with the real webcam instead. Each scenario
runs the real app (handtrack.app.main) in a fresh process with a throwaway
data folder, waits for it to settle, then samples the process once a second:

    idle        window open, camera stopped
    tray        window hidden to the tray, camera stopped        (needs a tray)
    live        camera running, default settings, window open
    live_tray   camera running, window hidden to the tray         (needs a tray)
    privacy     camera running with "Hide face"
    call        "Hide face" + virtual camera, read by a DirectShow client
                the way a call app does                     (Windows; pygrabber)

CPU is the process's total over all its threads, in % of one core (so it can
exceed 100) and in % of the whole machine. Memory is the resident set (RSS /
Windows working set; includes shared libraries), the unique set size (USS:
memory only this process uses) and, on Windows, private bytes. Needs psutil.
"""

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCENARIOS = ("idle", "tray", "live", "live_tray", "privacy", "call")

BASE_SETTINGS = {  # the app's defaults, made explicit; the log window stays closed
    "hide_face": False, "visualize": True, "gaze": True, "fast_mode": True,
    "resolution": "1280x720", "vcam": False, "draw_enabled": True, "afk_enabled": True,
    "preview_visible": True, "show_counter": True, "log_window": False,
    "animation": os.environ.get("HANDTRACK_BENCH_ANIMATION", "1") == "1",
}


# ------------------------------------------------------------------ parent ----
def run_parent(args):
    use_camera = args.video == "camera"
    if not use_camera and not os.path.isfile(args.video):
        raise SystemExit(f"video not found: {args.video}")
    wanted = [s for s in args.scenarios.split(",") if s]
    results = {"machine": machine_info(), "seconds": args.seconds,
               "video": "webcam" if use_camera else os.path.basename(args.video),
               "scenarios": {}}
    for name in wanted:
        if name == "call" and sys.platform != "win32":
            print(f"{name:10} skipped (Windows only)")
            continue
        with tempfile.TemporaryDirectory(prefix="ht-bench-") as data, \
                tempfile.NamedTemporaryFile("r", suffix=".json", delete=False) as out:
            env = dict(os.environ, APPDATA=data, XDG_CONFIG_HOME=data, HOME=os.environ.get("HOME", data),
                       HANDTRACK_ALLOW_MULTIPLE="1",
                       PYTHONPATH=os.path.join(ROOT, "src"))
            if not use_camera:
                env["HANDTRACK_VIDEO_SOURCE"] = os.path.abspath(args.video)
            if sys.platform.startswith("linux") and not os.environ.get("DISPLAY") \
                    and not os.environ.get("WAYLAND_DISPLAY"):
                env["QT_QPA_PLATFORM"] = "offscreen"
            cmd = [sys.executable, os.path.abspath(__file__), "--child", name, "--seconds", str(args.seconds),
                   "--result", out.name]
            proc = subprocess.run(cmd, env=env, cwd=os.path.join(ROOT, "src"), timeout=args.seconds + 120)
            try:
                with open(out.name, encoding="utf-8") as f:
                    res = json.load(f)
            except (OSError, ValueError):
                res = {"error": f"no result (exit code {proc.returncode})"}
                crash = os.path.join(data, "HandTrack", "logs", "crash.log")
                if os.path.isfile(crash):
                    with open(crash, encoding="utf-8", errors="replace") as f:
                        res["crash_log"] = f.read()[-6000:]
                    print(res["crash_log"])
        os.unlink(out.name)
        results["scenarios"][name] = res
        print(format_row(name, res), flush=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
    return 0


def machine_info():
    import psutil
    return {"os": platform.platform(), "python": platform.python_version(), "cpu": platform.processor()
            or platform.machine(), "cores": psutil.cpu_count(), "ram_gb": round(psutil.virtual_memory().total / 2**30, 1)}


def format_row(name, r):
    if "error" in r:
        return f"{name:10} {r['error']}"
    if r.get("skipped"):
        return f"{name:10} skipped ({r['skipped']})"
    priv = f"  private {r['private_mb']:6.0f} MB" if r.get("private_mb") else ""
    if r.get("uss_mb"):
        priv += f"  USS {r['uss_mb']:5.0f} MB"
    fps = f"  {r['fps']:5.1f} FPS" if r.get("fps") else ""
    row = (f"{name:10} CPU {r['cpu_core']:6.1f}% of a core ({r['cpu_machine']:4.1f}% of all)"
           f"  RAM {r['rss_mb']:6.0f} MB (peak {r['rss_peak_mb']:4.0f}){priv}{fps}")
    if r.get("by_thread") and os.environ.get("HANDTRACK_BENCH_THREADS"):
        row += "\n" + " " * 11 + ", ".join(f"{k} {v}" for k, v in r["by_thread"].items())
    return row


# ------------------------------------------------------------------- child ----
def run_child(args):
    import psutil

    from handtrack import paths
    paths.ensure_dirs()
    settings = dict(BASE_SETTINGS)
    if args.child in ("privacy", "call"):
        settings["hide_face"] = True
    if args.child == "call":
        settings["vcam"] = True
    with open(paths.SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f)

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    import handtrack.ui.main_window as mw

    state = {"fps": 0.0, "result": None}
    proc = psutil.Process()
    live = args.child in ("live", "live_tray", "privacy", "call")
    hidden = args.child in ("tray", "live_tray")
    warmup = 8.0 if live else 4.0
    consumer = []

    class Bench(mw.MainWindow):
        def __init__(self, settings_obj, engine):
            super().__init__(settings_obj, engine)
            engine.stats.connect(lambda s: state.__setitem__("fps", s.get("fps") or state["fps"]))
            QTimer.singleShot(1500, self._setup)

        def _setup(self):
            if hidden:
                if self.tray is None:
                    state["result"] = {"skipped": "no system tray"}
                    self.quit_app()
                    return
                self.close()                    # X: hides to the tray
            if live:
                self.toggle_running()
            if args.child == "call":
                consumer.append(subprocess.Popen([sys.executable, os.path.abspath(__file__), "--consumer"]))
            QTimer.singleShot(int(warmup * 1000), self._measure)

        def _measure(self):
            proc.cpu_percent(None)
            state["threads0"] = thread_times(proc)
            state["t0"] = time.monotonic()
            samples = []

            def tick():
                cpu = proc.cpu_percent(None)
                mem = proc.memory_info()
                samples.append((cpu, mem.rss, getattr(mem, "private", 0)))
                if len(samples) < args.seconds:
                    QTimer.singleShot(1000, tick)
                else:
                    self._done(samples)
            QTimer.singleShot(1000, tick)

        def _done(self, samples):
            try:   # unique set size: memory only this process uses (Linux/macOS/Windows)
                uss = proc.memory_full_info().uss / 2**20
            except (psutil.Error, AttributeError):
                uss = None
            cpus = [s[0] for s in samples]
            cores = psutil.cpu_count() or 1
            state["result"] = {
                "cpu_core": sum(cpus) / len(cpus), "cpu_machine": sum(cpus) / len(cpus) / cores,
                "cpu_max": max(cpus),
                "rss_mb": sum(s[1] for s in samples) / len(samples) / 2**20,
                "rss_peak_mb": max(s[1] for s in samples) / 2**20,
                "private_mb": (sum(s[2] for s in samples) / len(samples) / 2**20) or None,
                "uss_mb": uss,
                "fps": state["fps"] if live else None, "threads": proc.num_threads(),
                "by_thread": thread_breakdown(state["threads0"], thread_times(proc),
                                              time.monotonic() - state["t0"]),
            }
            for c in consumer:
                c.kill()
            self.quit_app()

    mw.MainWindow = Bench
    from handtrack.app import main
    main([])
    QApplication.instance()
    with open(args.result, "w", encoding="utf-8") as f:
        json.dump(state["result"] or {"error": "no measurement"}, f)
    return 0


def thread_times(proc):
    return {t.id: t.user_time + t.system_time for t in proc.threads()}


def thread_breakdown(before, after, seconds):
    """% of a core per thread, grouped by Python thread name (native threads,
    i.e. MediaPipe/XNNPACK/Qt workers, are summed as "native")."""
    import threading
    names = {t.native_id: t.name for t in threading.enumerate()}
    out = {}
    for tid, total in after.items():
        name = names.get(tid, "native")
        out[name] = out.get(name, 0.0) + (total - before.get(tid, 0.0)) / seconds * 100
    return {k: round(v, 1) for k, v in sorted(out.items(), key=lambda kv: -kv[1]) if v >= 0.05}


def run_consumer():
    """A DirectShow client reading "HandTrack Camera" continuously (like a call)."""
    from pygrabber.dshow_graph import FilterGraph
    graph = FilterGraph()
    graph.add_video_input_device(graph.get_input_devices().index("HandTrack Camera"))
    graph.add_sample_grabber(lambda img: None)
    graph.add_null_render()
    graph.prepare_preview_graph()
    graph.run()
    while True:
        time.sleep(1)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--video")
    ap.add_argument("--seconds", type=int, default=20)
    ap.add_argument("--scenarios", default=",".join(SCENARIOS))
    ap.add_argument("--out")
    ap.add_argument("--child")
    ap.add_argument("--result")
    ap.add_argument("--consumer", action="store_true")
    args = ap.parse_args()
    if args.consumer:
        return run_consumer()
    if args.child:
        return run_child(args)
    if not args.video:
        ap.error("--video is required")
    return run_parent(args)


if __name__ == "__main__":
    raise SystemExit(main())
