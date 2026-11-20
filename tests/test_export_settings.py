"""Export setting validation and encoder fallback tests."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-export-settings-")
sys.path.insert(0, ".")

from studio import export_settings, media, render  # noqa: E402

fails = []


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)


expected = {
    "1080p": (1080, 1920),
    "2k": (1440, 2560),
    "4k": (2160, 3840),
}
for key, dimensions in expected.items():
    check(key + " output dimensions", export_settings.dimensions({"export_resolution": key}) == dimensions)

clean = export_settings.clean({
    "export_resolution": "4k",
    "export_encoder": "av1",
    "export_quality": "maximum",
})
check("valid manual settings are retained", clean == {
    "export_resolution": "4k", "export_encoder": "av1", "export_quality": "maximum"
})
check("missing settings use compatibility defaults", export_settings.clean({}) == export_settings.DEFAULTS)
check("invalid values are replaced safely", export_settings.clean({
    "export_resolution": "8k", "export_encoder": "vp9", "export_quality": "lossless"
}) == export_settings.DEFAULTS)

# Hardware is preferred when listed, but software stays available as a fallback.
h264 = export_settings.encoder_candidates("h264", "high", {
    "h264_nvenc", "h264_qsv", "libx264"
})
check("H.264 tries NVIDIA NVENC before QSV and software",
      [x[0] for x in h264] == ["h264_nvenc", "h264_qsv", "libx264"])
hevc = export_settings.encoder_candidates("hevc", "balanced", {"hevc_qsv", "libx265"})
check("HEVC falls back from QSV to software",
      [x[0] for x in hevc] == ["hevc_qsv", "libx265"])
av1 = export_settings.encoder_candidates("av1", "maximum", {"av1_nvenc", "libsvtav1"})
check("AV1 keeps AV1 while falling back from NVENC to SVT-AV1",
      [x[0] for x in av1] == ["av1_nvenc", "libsvtav1"])
check("unsupported codec has no silent H.264 fallback",
      export_settings.encoder_candidates("av1", "high", {"libx264"}) == [])

for quality, expected_crf in (("balanced", "21"), ("high", "18"), ("maximum", "16")):
    candidates = export_settings.encoder_candidates("h264", quality, {"libx264"})
    args = candidates[0][1]
    check(quality + " profile applies its software quality setting",
          "-crf" in args and args[args.index("-crf") + 1] == expected_crf)

ass_4k = render.build_ass([], 0, 1.2, "WAIT FOR IT", "bounce", [], 600, 2760, 2160, 3840)
check("4K ASS caption canvas uses native coordinates",
      "PlayResX: 2160" in ass_4k and "PlayResY: 3840" in ass_4k and r"\\fs192" in ass_4k)
filter_4k = render._filter("blur", 1620, width=2160, height=3840)
check("4K layout filter composes at 2160x3840", "scale=2160:3840" in filter_4k)

# Make short real MP4s at every requested size. This checks that the composition and
# captions use the selected dimensions, not a 1080p render enlarged afterward.
work = Path(tempfile.mkdtemp(prefix="pc-export-render-"))
source = work / "source.mp4"
try:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24:duration=1.2",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1.2", "-shortest",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)],
        check=True, capture_output=True, timeout=60,
    )
    source_info = media.probe(source)
    expected_encoders = {"1080p": (1080, 1920), "2k": (1440, 2560), "4k": (2160, 3840)}
    for resolution, (width, height) in expected_encoders.items():
        clip = {
            "start": 0, "end": 1.2, "layout": "blur", "captions": False, "hook": "",
            "export_resolution": resolution, "export_encoder": "h264", "export_quality": "balanced",
        }
        made = render.render_clip(source, work / resolution, resolution, clip, [], source_info["width"], source_info["height"])
        encoded = media.probe(work / resolution / made["file"])
        check(resolution + " render uses native selected dimensions",
              encoded["width"] == width and encoded["height"] == height)
        check(resolution + " render records the actual encoder",
              bool(made.get("encoder")) and made.get("resolution") == f"{width}x{height}")
except Exception as error:  # noqa: BLE001
    print("  Real export test: " + str(error))
    fails.append("real 1080p/2K/4K exports")

if fails:
    print("FAILED: " + ", ".join(fails))
    sys.exit(1)
print("All export setting checks passed.")
