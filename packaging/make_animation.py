"""Turn packaging/media/animation.mp4 into src/handtrack/assets/animation.jpg.

The app plays the sidebar animation from one JPEG holding every frame in a
grid (no video decoding, no multimedia library at run time). Needs ffmpeg:

    python packaging/make_animation.py [path/to/video]

Frames are scaled to 240 px wide and laid out 8 per row; the frame count and
rate go into src/handtrack/assets/animation.json.
"""

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "packaging", "media", "animation.mp4")
OUT = os.path.join(ROOT, "src", "handtrack", "assets", "animation.jpg")
META = os.path.join(ROOT, "src", "handtrack", "assets", "animation.json")
WIDTH, COLS = 240, 8


def probe():
    out = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                          "-show_entries", "stream=nb_read_frames,avg_frame_rate", "-of", "json", SRC],
                         capture_output=True, text=True, check=True).stdout
    stream = json.loads(out)["streams"][0]
    num, den = (int(x) for x in stream["avg_frame_rate"].split("/"))
    return int(stream["nb_read_frames"]), num / den


def main():
    frames, fps = probe()
    rows = -(-frames // COLS)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", SRC, "-vf",
                    f"scale={WIDTH}:-2:flags=lanczos,tile={COLS}x{rows}", "-frames:v", "1", "-q:v", "4", OUT],
                   check=True)
    with open(META, "w", encoding="utf-8") as f:
        json.dump({"frames": frames, "columns": COLS, "fps": round(fps, 2)}, f)
    print(f"{frames} frames at {fps:.2f} FPS -> {OUT}")


if __name__ == "__main__":
    main()
