"""Custom layout validation and a real FFmpeg render."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-custom-layout-")
sys.path.insert(0, ".")
from studio import custom_layout, media, render  # noqa: E402

fails = []


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)


valid = {
    "version": 1,
    "source": {"facecam": [.68, .02, .30, .30], "gameplay": [0, 0, 1, 1]},
    "frames": {"facecam": [0, 0, 1, .36], "gameplay": [0, .36, 1, .64]},
}
clean = custom_layout.clean(valid)
check("valid source areas accepted", clean["source"]["facecam"] == valid["source"]["facecam"])
check("valid output frames accepted", clean["frames"]["gameplay"] == valid["frames"]["gameplay"])

bad_values = [
    None,
    {},
    {"source": {"facecam": [0, 0, 1, 1]}, "frames": valid["frames"]},
    {"source": {**valid["source"], "facecam": [-.1, 0, .3, .3]}, "frames": valid["frames"]},
    {"source": {**valid["source"], "gameplay": [0, 0, .8, 1.1]}, "frames": valid["frames"]},
    {"source": valid["source"], "frames": {**valid["frames"], "facecam": [0, 0, float("nan"), .3]}},
]
for i, bad in enumerate(bad_values, 1):
    try:
        custom_layout.clean(bad)
        ok = False
    except ValueError:
        ok = True
    check("invalid layout case " + str(i) + " rejected", ok)

graph = custom_layout.filter_complex(valid, 1080, 1920, 30, 2.0)
check("filter graph has separate source crops", "crop=iw*" in graph and "[game_src]" in graph and "[face_src]" in graph)
check("filter graph creates a portrait canvas", "s=1080x1920" in graph and "[v0]" in graph)

work = Path(tempfile.mkdtemp(prefix="pc-custom-render-"))
src = work / "source.mp4"
try:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24:duration=2",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2", "-shortest",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)],
        check=True, capture_output=True, timeout=60,
    )
    info = media.probe(src)
    result = render.render_clip(
        src, work / "out", "custom-test",
        {"start": 0, "end": 2, "layout": "custom", "custom_layout": valid,
         "captions": False, "hook": "", "style": "clean"},
        [], info["width"], info["height"],
    )
    encoded = media.probe(work / "out" / result["file"])
    check("custom layout renders playable 1080x1920 MP4",
          encoded["width"] == 1080 and encoded["height"] == 1920)
except Exception as error:  # noqa: BLE001
    print("  " + str(error))
    fails.append("custom layout renders playable 1080x1920 MP4")

if fails:
    print("FAILED: " + ", ".join(fails))
    sys.exit(1)
print("All custom layout checks passed.")
