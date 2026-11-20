"""Export setting validation and encoder fallback tests."""
import os
import sys
import tempfile

os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-export-settings-")
sys.path.insert(0, ".")

from studio import export_settings  # noqa: E402

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

for quality, expected_crf in (("balanced", "23"), ("high", "20"), ("maximum", "17")):
    candidates = export_settings.encoder_candidates("h264", quality, {"libx264"})
    args = candidates[0][1]
    check(quality + " profile applies its software quality setting",
          "-crf" in args and args[args.index("-crf") + 1] == expected_crf)

if fails:
    print("FAILED: " + ", ".join(fails))
    sys.exit(1)
print("All export setting checks passed.")
