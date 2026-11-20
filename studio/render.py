"""Turns a time range into a vertical clip: 9:16 layout, bouncy word captions, hook title, cover."""
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import config, roman, custom_layout as custom_layouts, export_settings
from .media import NO_WINDOW, run

W, H = config.OUT_W, config.OUT_H

# ASS colours are &HBBGGRR. `size` is the ASS font size (line height); _Font turns it into real pixels.
STYLES = {
    "bounce": {"label": "Bounce", "font": "Poppins ExtraBold", "size": 132, "base": "FFFFFF", "active": "00F0FF",
               "strong": "FFFFFF", "outline": 7, "pop": 112, "upper": True, "per": 3},
    "hype": {"label": "Hype", "font": "Anton", "size": 152, "base": "FFFFFF", "active": "3C3CFF",
             "strong": "00D7FF", "outline": 7, "pop": 114, "upper": True, "per": 2},
    "clean": {"label": "Clean", "font": "Poppins ExtraBold", "size": 100, "base": "FFFFFF", "active": "6BD7FF",
              "strong": "FFFFFF", "outline": 5, "pop": 106, "upper": False, "per": 4},

    "karaoke": {"label": "Karaoke", "font": "Poppins ExtraBold", "size": 112, "base": "FFFFFF",
                "active": "00E6FF", "strong": "35AEFF", "outline": 6, "pop": 108, "upper": False, "per": 1},
    "impact": {"label": "Impact", "font": "Anton", "size": 168, "base": "FFFFFF",
               "active": "00E6FF", "strong": "3C3CFF", "outline": 10, "pop": 116, "upper": True, "per": 2},
    "neon": {"label": "Neon Glow", "font": "Archivo Black", "size": 126, "base": "FFFFFF",
             "active": "FFE835", "strong": "FF73BE", "outline": 8, "pop": 116, "upper": True, "per": 2,
             "glow": True},
    "redalert": {"label": "Red Alert", "font": "Anton", "size": 150, "base": "FFFFFF",
                 "active": "3C3CFF", "strong": "3C3CFF", "outline": 9, "pop": 114, "upper": True, "per": 2},
    "gaming": {"label": "Gaming", "font": "Archivo Black", "size": 132, "base": "FFFFFF",
               "active": "4DFF72", "strong": "00E6FF", "outline": 9, "pop": 116, "upper": True, "per": 2},
    "gradient": {"label": "Gradient", "font": "Poppins ExtraBold", "size": 118, "base": "FFFFFF",
                 "active": "FFE835", "strong": "FF73BE", "outline": 6, "pop": 110, "upper": True, "per": 3,
                 "gradient": True},
}
HOOK = {"font": "Poppins ExtraBold", "size": 96, "ink": "14100E", "box": "FFFFFF", "pad_x": 36, "pad_y": 22, "radius": 26,
        "max_w": 900}
FONT_FILES = {"Poppins ExtraBold": "Poppins-ExtraBold.ttf", "Anton": "Anton-Regular.ttf", "Archivo Black": "ArchivoBlack-Regular.ttf"}
CAP_MAX_W = 960   # captions never run wider than this, whatever is said

FILTER_PRESETS = {
    "original": "Original",
    "gaming": "Gaming Vibrant",
    "cinematic": "Cinematic",
    "clean": "Clean & Sharp",
    "warm": "Warm",
    "cool": "Cool",
    "bw": "Black & White",
}


def _color_filter(preset="original", strength=70) -> str:
    """A restrained, optional colour look. It runs on video only, before the captions are drawn."""
    preset = preset if preset in FILTER_PRESETS else "original"
    try:
        power = max(0.0, min(100.0, float(strength))) / 100.0
    except (TypeError, ValueError):
        power = 0.7
    if preset == "original" or power <= 0:
        return ""
    if preset == "gaming":
        return (f"eq=contrast={1 + 0.09 * power:.3f}:saturation={1 + 0.34 * power:.3f}:"
                f"brightness={0.012 * power:.3f}")
    if preset == "cinematic":
        return (f"eq=contrast={1 + 0.12 * power:.3f}:saturation={1 - 0.16 * power:.3f}:"
                f"brightness={-0.018 * power:.3f},colorbalance=rs={0.035 * power:.3f}:"
                f"gs={-0.006 * power:.3f}:bs={-0.035 * power:.3f}")
    if preset == "clean":
        return (f"eq=contrast={1 + 0.05 * power:.3f}:saturation={1 + 0.025 * power:.3f},"
                f"unsharp=5:5:{0.65 * power:.3f}:3:3:{0.30 * power:.3f}")
    if preset == "warm":
        return (f"colorbalance=rs={0.08 * power:.3f}:gs={0.025 * power:.3f}:"
                f"bs={-0.075 * power:.3f}")
    if preset == "cool":
        return (f"colorbalance=rs={-0.07 * power:.3f}:gs={0.005 * power:.3f}:"
                f"bs={0.085 * power:.3f}")
    if preset == "bw":
        return f"eq=saturation={1 - power:.3f}"
    return ""


class _Font:
    """Measures text exactly as the renderer will draw it, so every word can be placed by hand: the highlighted
    word can grow without pushing its neighbours, and the heading box fits its text."""
    _cache: dict = {}

    def __init__(self, name):
        import struct
        path = Path(__file__).resolve().parent / "fonts" / FONT_FILES.get(name, FONT_FILES["Poppins ExtraBold"])
        d = path.read_bytes()
        tables = {}
        for i in range(struct.unpack(">H", d[4:6])[0]):
            tag, _, off, _ = struct.unpack(">4sIII", d[12 + 16 * i: 28 + 16 * i])
            tables[tag] = off
        self.upm = struct.unpack(">H", d[tables[b"head"] + 18: tables[b"head"] + 20])[0]
        o = tables[b"OS/2"]
        self.asc, self.desc = struct.unpack(">HH", d[o + 74: o + 78])      # what the renderer sizes the font by
        self.cap = struct.unpack(">h", d[o + 88: o + 90])[0] or int(self.upm * 0.7)
        self.path = str(path)
        self._pil = {}

    @classmethod
    def get(cls, name):
        if name not in cls._cache:
            cls._cache[name] = cls(name)
        return cls._cache[name]

    def em(self, size):
        return size * self.upm / (self.asc + self.desc)

    def width(self, text, size):
        """Pixels wide at this ASS size."""
        try:
            from PIL import ImageFont
            if "f" not in self._pil:
                self._pil["f"] = ImageFont.truetype(self.path, 200)
            return self._pil["f"].getlength(text) * self.em(size) / 200
        except Exception:  # noqa: BLE001 - no measuring library: a fair estimate keeps clips rendering
            return len(text) * self.em(size) * 0.62

    def cap_shift(self, size):
        """How far below the anchor the middle of a capital letter sits when text is centred on a point."""
        return ((self.asc - self.desc) / 2 - self.cap / 2) * size / (self.asc + self.desc)


CAPTION_LEAD = 0.0  # measured: word stamps are within 0.15 s of the voice, so no shift is needed


def clean_position(value):
    """Validate a normalized (0..1) centre position saved by the draggable clip editor."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        import json
        try:
            value = json.loads(value)
        except (TypeError, ValueError) as e:
            raise ValueError("The text position is not valid. Drag it into place again.") from e
    if not isinstance(value, dict):
        raise ValueError("The text position is not valid. Drag it into place again.")
    out = {}
    for axis in ("x", "y"):
        raw = value.get(axis)
        if isinstance(raw, bool):
            raise ValueError("The text position is not valid. Drag it into place again.")
        try:
            number = float(raw)
        except (TypeError, ValueError, OverflowError) as e:
            raise ValueError("The text position is not valid. Drag it into place again.") from e
        if not math.isfinite(number):
            raise ValueError("The text position is not valid. Drag it into place again.")
        out[axis] = round(max(0.0, min(1.0, number)), 6)
    return out
def install_fonts():
    """Copy the bundled caption fonts next to the data, so captions look the same on every machine and server."""
    src = Path(__file__).resolve().parent / "fonts"
    for f in src.glob("*.ttf"):
        if not (config.FONTS_DIR / f.name).exists():
            shutil.copyfile(f, config.FONTS_DIR / f.name)


LAYOUTS = {"blur": "Full frame + blurred fill", "zoom": "Zoomed in + blurred fill", "crop": "Fill the screen (centre crop)",
           "left": "Fill the screen, keep the left side", "right": "Fill the screen, keep the right side",
           "fit": "Full frame on black", "split": "Split screen: left half on top, right half below (two people)",
           "gameplay": "Gameplay fills the screen, facecam in the corner"}
_FILLS = ("crop", "left", "right", "gameplay")      # layouts where the picture covers the whole frame


def _ts(t):
    t = max(0.0, t)
    h, m = int(t // 3600), int(t % 3600 // 60)
    return f"{h}:{m:02d}:{t % 60:05.2f}"


def _clean(text):
    return re.sub(r"[\x00-\x1f\x7f]+", " ", re.sub(r"[{}\\]", "", str(text))).strip()


def _key(word):
    return re.sub(r"[^a-z0-9']", "", word.lower())


def _groups(words, per):
    out, cur = [], []
    for w in words:
        if cur and (len(cur) >= per or sum(len(x["w"]) for x in cur) + len(w["w"]) > 16
                    or w["s"] - cur[-1]["e"] > 0.45 or cur[-1]["w"][-1:] in ".?!"):
            out.append(cur)
            cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    return out


def geometry(src_w, src_h, layout, width=W, height=H):
    """Where the source sits in the selected portrait output, with positions scaled from 1080p."""
    scale = width / W
    if layout == "custom":
        return layout, height, round(300 * scale), round(1380 * scale)
    if src_h >= src_w and layout != "crop":
        layout = "crop"  # already vertical or square: nothing to gain from a blurred fill
    if layout not in LAYOUTS:
        layout = "blur"
    if layout in ("blur", "fit"):
        fg_h = min(height, int(round(width * src_h / src_w / 2)) * 2)
    elif layout == "zoom":
        fg_h = round(1000 * scale)
    else:
        fg_h = height
    top = (height - fg_h) // 2
    if layout in _FILLS:
        return layout, fg_h, round(300 * scale), round(1380 * scale)
    if layout == "split":
        return layout, fg_h, round(230 * scale), height // 2
    return layout, fg_h, max(round(230 * scale), top - round(190 * scale)), min(round(1640 * scale), top + fg_h + round(180 * scale))


def _hook_events(hook, dur, y, width=W, height=H, scale=1.0, position=None):
    """The heading: dark text in a white rounded box that fits it, on one line or two balanced ones."""
    cfg = dict(HOOK)
    for key in ("size", "pad_x", "pad_y", "radius", "max_w"):
        cfg[key] = round(cfg[key] * scale)
    f, size = _Font.get(cfg["font"]), cfg["size"]
    words = hook.split()
    if not words:
        return []
    lines = [" ".join(words)]
    if f.width(lines[0], size) > cfg["max_w"] and len(words) > 1:      # two lines, split where they come out most even
        cut = min(range(1, len(words)), key=lambda i: max(f.width(" ".join(words[:i]), size), f.width(" ".join(words[i:]), size)))
        lines = [" ".join(words[:cut]), " ".join(words[cut:])]
    widest = max(f.width(l, size) for l in lines)
    if widest > cfg["max_w"]:
        size = max(round(40 * scale), int(size * cfg["max_w"] / widest))
        widest = max(f.width(l, size) for l in lines)
    line_h = f.em(size) * 1.16
    bw, bh = widest + 2 * cfg["pad_x"], line_h * len(lines) + 2 * cfg["pad_y"]
    cx = width * position["x"] if position else width / 2
    cy_center = height * position["y"] if position else y
    cx = max(bw / 2 + 8, min(width - bw / 2 - 8, cx)) if bw <= width - 16 else width / 2
    cy_center = max(bh / 2 + 8, min(height - bh / 2 - 8, cy_center)) if bh <= height - 16 else height / 2
    x0, y0, r = cx - bw / 2, cy_center - bh / 2, min(cfg["radius"], bh / 2)
    x1, y1 = x0 + bw, y0 + bh
    n = lambda v: f"{v:.0f}"                                                         # noqa: E731
    box = (f"m {n(x0 + r)} {n(y0)} l {n(x1 - r)} {n(y0)} b {n(x1)} {n(y0)} {n(x1)} {n(y0)} {n(x1)} {n(y0 + r)} "
           f"l {n(x1)} {n(y1 - r)} b {n(x1)} {n(y1)} {n(x1)} {n(y1)} {n(x1 - r)} {n(y1)} "
           f"l {n(x0 + r)} {n(y1)} b {n(x0)} {n(y1)} {n(x0)} {n(y1)} {n(x0)} {n(y1 - r)} "
           f"l {n(x0)} {n(y0 + r)} b {n(x0)} {n(y0)} {n(x0)} {n(y0)} {n(x0 + r)} {n(y0)}")
    span = f"{_ts(0)},{_ts(dur)}"
    ev = [f"Dialogue: 3,{span},Hook,,0,0,0,,{{\\an7\\pos(0,0)\\fad(160,0)\\c&H{HOOK['box']}&\\p1}}{box}{{\\p0}}"]
    for i, line in enumerate(lines):
        cy = cy_center - line_h * (len(lines) - 1) / 2 + i * line_h - f.cap_shift(size)
        ev.append(f"Dialogue: 4,{span},Hook,,0,0,0,,{{\\an5\\pos({cx:.0f},{cy:.0f})\\fad(160,0)\\fs{size}}}{line}")
    return ev


def build_ass(words, start, end, hook, style_name, highlight, hook_y, cap_y, width=W, height=H,
              hook_position=None, caption_position=None) -> str:
    scale = width / W
    st = dict(STYLES.get(style_name, STYLES["bounce"]))
    st["size"] = round(st["size"] * scale)
    st["outline"] = max(1, round(st["outline"] * scale))
    cap_max_w = round(CAP_MAX_W * scale)
    words = [dict(w, s=w["s"] - CAPTION_LEAD, e=w["e"] - CAPTION_LEAD) for w in words]
    strong = {_key(h) for h in highlight if _key(h)}
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{st['font']},{st['size']},&H00{st['base']},&H00{st['base']},&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,{st['outline']},0,5,0,0,0,1
Style: Hook,{HOOK['font']},{HOOK['size']},&H00{HOOK['ink']},&H00{HOOK['ink']},&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    dur = end - start
    hook_position = clean_position(hook_position)
    caption_position = clean_position(caption_position)
    caption_cx = width * caption_position["x"] if caption_position else width / 2
    caption_center_y = height * caption_position["y"] if caption_position else cap_y
    ev = _hook_events(_clean(hook), dur, hook_y, width, height, scale, hook_position)
    f = _Font.get(st["font"])
    inside = [dict(w, w=_clean(w["w"])) for w in words if w["s"] >= start - 0.05 and w["s"] < end]
    inside = sorted((w for w in inside if w["w"]), key=lambda w: w["s"])
    for i, w in enumerate(inside[:-1]):
        w["e"] = max(w["s"], min(w["e"], inside[i + 1]["s"]))
    groups = _groups(inside, st["per"])
    for gi, g in enumerate(groups):
        g_start = max(0.0, g[0]["s"] - start)
        g_end = min(g[-1]["e"] + 0.25, groups[gi + 1][0]["s"] if gi + 1 < len(groups) else end) - start
        if g_end - g_start < 0.02:
            continue
        texts = []
        for x in g:
            t = re.sub(r"[.,;:]+$", "", x["w"])
            texts.append(t.upper() if st["upper"] else t)
        if not all(roman.drawable(t) for t in texts):
            # A script the caption font cannot draw (Japanese, Thai, Chinese...): its words cannot be measured, so
            # they are not placed one by one. The line is drawn whole and centred, in a font the system has for it.
            line = " ".join(texts)
            fs = max(round(44 * scale), min(int(st["size"] * 0.7), int(1500 * scale / max(1, len(line)) * 1.6)))
            approx_w = min(cap_max_w, max(1, len(line) * fs * 0.55))
            cx = max(approx_w / 2 + 6, min(width - approx_w / 2 - 6, caption_cx))
            cy = max(fs * 0.8, min(height - fs * 0.8, caption_center_y))
            ev.append(f"Dialogue: 1,{_ts(g_start)},{_ts(g_end)},Cap,,60,60,0,,{{\\an5\\pos({cx:.0f},{cy:.0f})\\q0\\fs{fs}}}{line}")
            continue
        size = st["size"]
        gap = f.width("n n", size) - 2 * f.width("n", size) + (2 * st["outline"] + 6) * size / st["size"]   # a space, plus room for both outlines
        total = sum(f.width(t, size) for t in texts) + gap * (len(texts) - 1)
        if total > cap_max_w:                                  # a long phrase: shrink it to fit, never run off the frame
            size = max(round(36 * scale), int(size * cap_max_w / total))
            gap = f.width("n n", size) - 2 * f.width("n", size) + (2 * st["outline"] + 6) * size / st["size"]   # a space, plus room for both outlines
            total = sum(f.width(t, size) for t in texts) + gap * (len(texts) - 1)
        cx = max(total / 2 + 6, min(width - total / 2 - 6, caption_cx))
        cy = max(size * 0.8, min(height - size * 0.8, caption_center_y)) - f.cap_shift(size)
        x = cx - total / 2
        p = st["pop"]
        for i, (w, t) in enumerate(zip(g, texts)):
            wd = f.width(t, size)
            p = max(104, min(st["pop"], 100 + int(2200 / max(wd, 1))))   # long words grow less, so they never touch their neighbours
            pos = f"\\an5\\pos({x + wd / 2:.0f},{cy:.0f})\\fs{size}"
            x += wd + gap
            a = max(g_start, w["s"] - start)
            b = (g[i + 1]["s"] - start) if i + 1 < len(g) else g_end
            base = st["strong"] if _key(w["w"]) in strong else st["base"]
            active = st["active"]
            if st.get("gradient"):
                spectrum = ("00E6FF", "4DFF72", "FF73BE", "35AEFF", "3C3CFF")
                active = spectrum[(gi * 2 + i) % len(spectrum)]
            if a - g_start >= 0.02:                                                   # waiting to be said
                ev.append(f"Dialogue: 1,{_ts(g_start)},{_ts(a)},Cap,,0,0,0,,{{{pos}\\c&H{base}&}}{t}")
            if b - a >= 0.02:
                if st.get("glow"):
                    glow_outline = max(10, st["outline"] + 4)
                    ev.append(f"Dialogue: 1,{_ts(a)},{_ts(b)},Cap,,0,0,0,,{{{pos}\\c&H{active}&\\3c&H{active}&\\bord{glow_outline}\\blur3\\alpha&H55&}}{t}")                                                         # being said: colour and a quick pop, in front
                ev.append(f"Dialogue: 2,{_ts(a)},{_ts(b)},Cap,,0,0,0,,{{{pos}\\c&H{active}&\\fscx94\\fscy94"
                          f"\\t(0,90,\\fscx{p}\\fscy{p})\\t(90,200,\\fscx{p - 5}\\fscy{p - 5})}}{t}")
            if g_end - b >= 0.02:                                                     # said
                ev.append(f"Dialogue: 1,{_ts(b)},{_ts(g_end)},Cap,,0,0,0,,{{{pos}\\c&H{base}&\\fscx{p - 5}\\fscy{p - 5}"
                          f"\\t(0,90,\\fscx100\\fscy100)}}{t}")
    return head + "\n".join(ev) + "\n"


PIP_W = 380            # how wide the facecam is in the 1080-wide frame
PIP_MARGIN = 26


def _filter(layout, fg_h, facecam=None, custom=None, duration=60.0, width=W, height=H):
    scale = width / W
    if layout == "custom":
        return custom_layouts.filter_complex(custom, width, height, config.OUT_FPS, duration) + ";"
    if layout == "gameplay" and facecam:
        # The game fills the screen, and the webcam sits in the top corner of it.
        fx, fy, fw, fh = (int(v) for v in facecam)
        if fw > 8 and fh > 8:
            pip_w, pip_margin = round(PIP_W * scale), round(PIP_MARGIN * scale)
            pip_h = max(2, int(round(pip_w * fh / fw)))
            return (f"[0:v]fps={config.OUT_FPS},split=2[base][fc];"
                    f"[base]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1[b];"
                    f"[fc]crop={fw}:{fh}:{fx}:{fy},scale={pip_w}:{pip_h},setsar=1[p];"
                    f"[b][p]overlay={width - pip_w - pip_margin}:{pip_margin}[v0];")
    fill = f"[0:v]fps={config.OUT_FPS},scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
    if layout == "crop" or (layout == "gameplay" and not facecam):
        return fill + ",setsar=1[v0];"
    if layout == "left":
        return fill + ":0:0,setsar=1[v0];"
    if layout == "right":
        return fill + ":in_w-out_w:0,setsar=1[v0];"
    if layout == "fit":
        return f"[0:v]fps={config.OUT_FPS},scale={width}:{fg_h},pad={width}:{height}:0:(oh-ih)/2:black,setsar=1[v0];"
    if layout == "split":
        half_h = height // 2
        half = f"scale={width}:{half_h}:force_original_aspect_ratio=increase,crop={width}:{half_h}"
        return (f"[0:v]fps={config.OUT_FPS},split=2[l][r];[l]crop=iw/2:ih:0:0,{half}[t];"
                f"[r]crop=iw/2:ih:iw/2:0,{half}[u];[t][u]vstack,setsar=1[v0];")
    blur_w, blur_h = round(270 * scale), round(480 * scale)
    blur = max(1, round(6 * scale))
    return (f"[0:v]fps={config.OUT_FPS},split=2[a][b];"
            f"[a]scale={blur_w}:{blur_h}:force_original_aspect_ratio=increase,crop={blur_w}:{blur_h},boxblur={blur}:2,"
            f"scale={width}:{height},eq=brightness=-0.14:saturation=1.15[bg];"
            f"[b]scale={width}:{fg_h}:force_original_aspect_ratio=increase,crop={width}:{fg_h}[fg];"
            f"[bg][fg]overlay=0:({height}-h)/2,setsar=1[v0];")

def _hook_y(layout, hook_y, facecam=None, width=W):
    """Where the heading goes. In the gameplay layout the webcam sits in the top corner, so a heading
    across the top would run under it: it goes just below the picture instead."""
    if layout == "gameplay" and facecam and len(facecam) == 4 and facecam[2] > 8:
        scale = width / W
        return round(PIP_MARGIN * scale) + int(round(PIP_W * scale * facecam[3] / facecam[2])) + round(32 * scale)
    return hook_y


_qsv_ok = None
RENDER_SECONDS = 600      # one clip's video encode; far beyond normal, so a frozen encoder is stopped, not waited on


def render_clip(src: Path, out_dir: Path, name: str, clip: dict, words: list, src_w: int, src_h: int) -> dict:
    """Write the selected portrait resolution using the requested codec and quality profile."""
    out_dir.mkdir(parents=True, exist_ok=True)
    start, end = clip["start"], clip["end"]
    settings = export_settings.clean(clip)
    width, height = export_settings.dimensions(settings)
    layout, fg_h, hook_y, cap_y = geometry(src_w, src_h, clip.get("layout", "blur"), width, height)
    face = clip.get("facecam")
    if layout == "gameplay" and not (face and len(face) == 4):
        layout = "crop"     # no webcam found: the game fills the screen, which is still the right shape
    hook_y = _hook_y(layout, hook_y, face, width)
    ass = build_ass(words if clip.get("captions", True) else [], start, end, clip.get("hook", ""), clip.get("style", "bounce"),
                    clip.get("highlight_words", []), hook_y, cap_y, width, height,
                    clip.get("hook_position"), clip.get("caption_position"))
    # Keep FFmpeg's ASS/font working directory short. This avoids Windows' 260-character path limit.
    work = Path(tempfile.mkdtemp(prefix="pk"))
    try:
        meta = {"title": clip.get("title") or "", "description": clip.get("description") or "",
                "comment": clip.get("description") or ""}
        return _render_in(
            work, src, out_dir, name, start, end, layout, fg_h, ass, face=face, meta=meta,
            custom=clip.get("custom_layout"), duration=end - start, width=width, height=height,
            codec=settings["export_encoder"], quality=settings["export_quality"],
            filter_preset=clip.get("filter", "original"), filter_strength=clip.get("filter_strength", 70),
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)

def _render_in(work: Path, src: Path, out_dir: Path, name: str, start, end, layout, fg_h, ass: str,
               face=None, meta=None, custom=None, duration=60.0, width=W, height=H,
               codec="h264", quality="balanced", filter_preset="original", filter_strength=70) -> dict:
    (work / f"{name}.ass").write_text(ass, encoding="utf-8")
    (work / "f").mkdir()
    for f in config.FONTS_DIR.glob("*.ttf"):
        shutil.copyfile(f, work / "f" / f.name)
    base_filter = _filter(layout, fg_h, face, custom=custom, duration=duration, width=width, height=height)
    look = _color_filter(filter_preset, filter_strength)
    if look:
        fc = base_filter + f"[v0]{look}[v1];[v1]ass={name}.ass:fontsdir=f[v]"
    else:
        fc = base_filter + f"[v0]ass={name}.ass:fontsdir=f[v]"
    base = ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}", "-t", f"{end - start:.2f}", "-i", str(src),
            "-filter_complex", fc, "-map", "[v]", "-map", "0:a:0", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000"]
    for key, value in (meta or {}).items():
        if value:
            base += ["-metadata", f"{key}={value}"]
    base += ["-movflags", "+faststart"]
    candidates = export_settings.encoder_candidates(codec, quality)
    if not candidates:
        raise RuntimeError(
            f"This FFmpeg installation has no available {codec.upper()} encoder. "
            f"Install an FFmpeg build with a {codec.upper()} encoder, then try again."
        )
    err, selected = None, None
    for label, encoder_args in candidates:
        output = work / f"{name}.mp4"
        output.unlink(missing_ok=True)
        p = subprocess.run(base + encoder_args + [f"{name}.mp4"], cwd=work, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", creationflags=NO_WINDOW, timeout=RENDER_SECONDS)
        if p.returncode == 0 and output.is_file() and output.stat().st_size > 0:
            selected = label
            break
        err = p.stderr[-1200:] or f"{label} returned exit code {p.returncode}"
    if not selected:
        raise RuntimeError(f"Export failed with the available {codec.upper()} encoders: {err}")
    cover_t = min(1.2, (end - start) / 2)
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{cover_t:.2f}", "-i", f"{name}.mp4", "-frames:v", "1",
         "-q:v", "3", f"{name}.jpg"], cwd=work)
    for ext in ("mp4", "jpg", "ass"):
        shutil.move(str(work / f"{name}.{ext}"), str(out_dir / f"{name}.{ext}"))
    return {"file": f"{name}.mp4", "cover": f"{name}.jpg", "layout": layout,
            "encoder": selected, "resolution": f"{width}x{height}", "export_quality": quality}
