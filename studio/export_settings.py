"""Validated, resolution-independent export settings and FFmpeg encoder selection."""
from __future__ import annotations

import functools
import re
import subprocess
from typing import Iterable

from .media import NO_WINDOW


RESOLUTIONS = {
    "1080p": {"label": "1080p · 1080 × 1920", "width": 1080, "height": 1920},
    "2k": {"label": "2K-class · 1440 × 2560", "width": 1440, "height": 2560},
    "4k": {"label": "4K · 2160 × 3840", "width": 2160, "height": 3840},
}
CODECS = {
    "h264": {"label": "H.264 · most compatible"},
    "hevc": {"label": "HEVC / H.265 · smaller files"},
    "av1": {"label": "AV1 · efficient compression"},
}
QUALITIES = {
    "balanced": {"label": "Balanced", "description": "Good quality with faster exports"},
    "high": {"label": "High quality", "description": "Sharper output and larger files"},
    "maximum": {"label": "Maximum quality", "description": "Highest quality setting; slower and larger"},
}
DEFAULTS = {
    "export_resolution": "1080p",
    "export_encoder": "h264",
    "export_quality": "balanced",
}

# These values are intentionally separate for each encoder family. Lower CRF/CQ means higher quality.
_PROFILES = {
    # Balanced keeps the previous H.264 quality (QSV 23 / x264 CRF 21) as its starting point.
    "balanced": {"nvenc": 23, "qsv": 23, "crf": 21, "av1_crf": 33},
    "high": {"nvenc": 20, "qsv": 20, "crf": 18, "av1_crf": 29},
    "maximum": {"nvenc": 17, "qsv": 17, "crf": 16, "av1_crf": 25},
}

_ENCODERS = {
    "h264": (
        ("h264_nvenc", "nvenc"),
        ("h264_qsv", "qsv"),
        ("libx264", "x264"),
    ),
    "hevc": (
        ("hevc_nvenc", "nvenc"),
        ("hevc_qsv", "qsv"),
        ("libx265", "x265"),
    ),
    "av1": (
        ("av1_nvenc", "nvenc"),
        ("av1_qsv", "qsv"),
        ("libsvtav1", "svtav1"),
        ("libaom-av1", "aom"),
    ),
}


def clean(values: dict | None) -> dict:
    """Return only the three supported export choices, replacing unknown values safely."""
    values = values if isinstance(values, dict) else {}
    result = {}
    for key, choices in (
        ("export_resolution", RESOLUTIONS),
        ("export_encoder", CODECS),
        ("export_quality", QUALITIES),
    ):
        value = values.get(key, DEFAULTS[key])
        result[key] = value if isinstance(value, str) and value in choices else DEFAULTS[key]
    return result


def dimensions(values: dict | None) -> tuple[int, int]:
    selected = clean(values)["export_resolution"]
    row = RESOLUTIONS[selected]
    return row["width"], row["height"]


@functools.lru_cache(maxsize=1)
def installed_encoders() -> frozenset[str]:
    """Read FFmpeg's encoder list once. Runtime encoding still tries candidates and falls back on errors."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=NO_WINDOW,
            timeout=15,
            check=False,
        )
        if result.returncode not in (0, 1):
            return frozenset()
        return frozenset(re.findall(
            r"(?m)^\s*[A-Z.]{6}\s+([A-Za-z0-9_.-]+)\s",
            result.stdout + "\n" + result.stderr,
        ))
    except (OSError, subprocess.TimeoutExpired):
        return frozenset()


def _arguments(kind: str, quality: str) -> list[str]:
    profile = _PROFILES[quality]
    if kind == "nvenc":
        return ["-preset", "p5", "-rc", "vbr", "-cq", str(profile["nvenc"]), "-b:v", "0", "-pix_fmt", "yuv420p"]
    if kind == "qsv":
        return ["-global_quality", str(profile["qsv"]), "-preset", "fast", "-pix_fmt", "nv12"]
    if kind == "x264":
        return ["-crf", str(profile["crf"]), "-preset", "veryfast", "-pix_fmt", "yuv420p"]
    if kind == "x265":
        return ["-crf", str(profile["crf"]), "-preset", "fast", "-pix_fmt", "yuv420p"]
    if kind == "svtav1":
        return ["-crf", str(profile["av1_crf"]), "-preset", "8", "-pix_fmt", "yuv420p"]
    if kind == "aom":
        return ["-crf", str(profile["av1_crf"]), "-b:v", "0", "-cpu-used", "6", "-pix_fmt", "yuv420p"]
    raise ValueError("That video encoder is not supported.")


def encoder_candidates(codec: str, quality: str, available: Iterable[str] | None = None) -> list[tuple[str, list[str]]]:
    """Best available encoder first; all fallbacks keep the requested codec."""
    if codec not in CODECS:
        codec = DEFAULTS["export_encoder"]
    if quality not in QUALITIES:
        quality = DEFAULTS["export_quality"]
    available_names = set(installed_encoders() if available is None else available)
    candidates = []
    for name, kind in _ENCODERS[codec]:
        if name in available_names:
            candidates.append((name, ["-c:v", name, *_arguments(kind, quality)]))
    return candidates


def capability_summary(available: Iterable[str] | None = None) -> dict:
    """A simple status for UI/help text; runtime may still fall back if a listed GPU encoder fails."""
    names = set(installed_encoders() if available is None else available)
    return {
        "nvenc": any(name in names for name in ("h264_nvenc", "hevc_nvenc", "av1_nvenc")),
        "qsv": any(name in names for name in ("h264_qsv", "hevc_qsv", "av1_qsv")),
        "software": any(name in names for name in ("libx264", "libx265", "libsvtav1", "libaom-av1")),
    }
