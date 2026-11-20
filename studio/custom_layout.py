"""Validation and FFmpeg composition for PeakCut's custom two-source vertical layout."""
from __future__ import annotations

import json
import math

_NAMES = ("facecam", "gameplay")


def clean(value) -> dict:
    """Validate normalized source and output rectangles before they reach FFmpeg."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError) as e:
            raise ValueError("The custom layout data is not valid. Select the facecam and gameplay areas again.") from e
    if not isinstance(value, dict):
        raise ValueError("Choose the facecam and gameplay areas before re-making this clip.")

    out = {}
    for group in ("source", "frames"):
        raw = value.get(group)
        if not isinstance(raw, dict):
            raise ValueError("The custom layout is incomplete. Select both source areas.")
        out[group] = {}
        for name in _NAMES:
            box = raw.get(name)
            if not isinstance(box, (list, tuple)) or len(box) != 4:
                raise ValueError(f"Select the {name} area in the original video.")
            try:
                x, y, w, h = (float(n) for n in box)
            except (TypeError, ValueError, OverflowError) as e:
                raise ValueError(f"The {name} area is not valid. Select it again.") from e
            if not all(math.isfinite(n) for n in (x, y, w, h)):
                raise ValueError(f"The {name} area is not valid. Select it again.")
            minimum = 0.015 if group == "source" else 0.04
            if x < 0 or y < 0 or w < minimum or h < minimum or x + w > 1.000001 or y + h > 1.000001:
                raise ValueError(f"The {name} area must be inside the video and large enough.")
            out[group][name] = [round(max(0.0, min(1.0, n)), 6) for n in (x, y, w, h)]
    return {"version": 1, **out}


def _even_pos(value: float, maximum: int) -> int:
    """An even pixel position; zero is a valid edge of the output."""
    n = int(round(value / 2.0) * 2)
    return max(0, min(maximum - 2, n))


def _even_size(value: float, maximum: int) -> int:
    """An even pixel size, for yuv420p output."""
    n = int(round(value / 2.0) * 2)
    return max(2, min(maximum - maximum % 2, n))


def _frame_pixels(box, width: int, height: int):
    x, y, w, h = box
    px, py = _even_pos(x * width, width), _even_pos(y * height, height)
    pw, ph = _even_size(w * width, width), _even_size(h * height, height)
    pw, ph = min(pw, width - px), min(ph, height - py)
    pw, ph = pw - pw % 2, ph - ph % 2
    if pw < 2 or ph < 2:
        raise ValueError("One of the custom output frames is too small.")
    return px, py, pw, ph


def filter_complex(value, width: int, height: int, fps: int, duration: float) -> str:
    """Crop each selected region from source pixels, scale it into its output frame and overlay both."""
    layout = clean(value)
    if width < 2 or height < 2 or fps < 1 or duration <= 0:
        raise ValueError("The custom layout render settings are not valid.")

    crops = []
    for name, label in (("gameplay", "game"), ("facecam", "face")):
        sx, sy, sw, sh = layout["source"][name]
        x, y, w, h = _frame_pixels(layout["frames"][name], width, height)
        crops.append(
            f"[{label}_src]crop=iw*{sw:.6f}:ih*{sh:.6f}:iw*{sx:.6f}:ih*{sy:.6f},"
            f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1[{label}]"
        )

    gx, gy, _, _ = _frame_pixels(layout["frames"]["gameplay"], width, height)
    fx, fy, _, _ = _frame_pixels(layout["frames"]["facecam"], width, height)
    return (
        f"[0:v]fps={fps},split=2[game_src][face_src];"
        + ";".join(crops)
        + f";color=c=black:s={width}x{height}:r={fps}:d={duration:.3f}[background];"
        + f"[background][game]overlay={gx}:{gy}:shortest=1:format=auto[with_game];"
        + f"[with_game][face]overlay={fx}:{fy}:shortest=1:format=auto[v0]"
    )
