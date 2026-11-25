"""Turns a time range into a vertical clip: 9:16 layout, bouncy word captions, hook title, cover."""
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import config, roman, custom_layout as custom_layouts, export_settings, templates
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
# Urdu and Hindi in their own script: drawn with these whatever the style's font (its letters are Latin only), a
# whole line at a time so the caption engine joins the letters and runs Urdu right to left
SCRIPT_FONTS = {"ur": ("Noto Nastaliq Urdu", "NotoNastaliqUrdu-Bold.ttf", 1.3), "hi": ("Noto Sans Devanagari", "NotoSansDevanagari-Bold.ttf", 1.05)}
FONT_FILES = {**templates.FONTS, **{n: f for n, f, _ in SCRIPT_FONTS.values()}}
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


# The heading may end with an emoji ("bro gave up on his own race 😭"). The caption renderer cannot draw colour emoji,
# so each one is drawn as a small picture from the system's emoji font and laid over the video where the text ends.
EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF]")
_EMOJI_EXTRA = re.compile("[\uFE0F\u200D\U0001F3FB-\U0001F3FF]")
EMOJI_FONTS = ("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf", r"C:\Windows\Fonts\seguiemj.ttf")


def emoji_font():
    """Something to draw emoji with: an emoji font on this machine, or the emoji folder."""
    font = next((f for f in EMOJI_FONTS if Path(f).is_file()), None)
    return font or (str(config.EMOJI_DIR) if _emoji_file("😭") else None)


def _emoji_file(ch: str):
    """This emoji's own picture from the emoji folder (PEAKCUT_EMOJI_DIR), named by its code points, like 1f62d.png."""
    if not config.EMOJI_DIR:
        return None
    f = Path(config.EMOJI_DIR) / ("-".join(f"{ord(c):x}" for c in ch if c not in "\ufe0f\u200d") + ".png")
    return f if f.is_file() else None


def split_hook(hook: str):
    """(the heading's words, its emoji: at most two, shown after the last word)"""
    text = _EMOJI_EXTRA.sub("", hook or "")
    return re.sub(r"\s{2,}", " ", EMOJI.sub("", text)).strip(), EMOJI.findall(text)[:2]


def emoji_png(ch: str, path: Path, px: int) -> bool:
    """One emoji as a see-through picture, px wide: from the emoji folder when it has this one, else drawn from the
    emoji font. False when there is neither (the emoji is then left out)."""
    own = _emoji_file(ch)
    if own:
        try:
            from PIL import Image
            im = Image.open(own).convert("RGBA")
            box = im.getbbox()
            im = im.crop(box) if box else im
            side = max(im.size)
            sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
            sq.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
            sq.resize((px, px), Image.LANCZOS).save(path)
            return True
        except Exception:  # noqa: BLE001 - a broken picture: the font draws it instead
            pass
    font = next((f for f in EMOJI_FONTS if Path(f).is_file()), None)
    if not font:
        return False
    try:
        from PIL import Image, ImageDraw, ImageFont
        im = Image.new("RGBA", (280, 280), (0, 0, 0, 0))
        ImageDraw.Draw(im).text((70, 60), ch, font=ImageFont.truetype(font, 109), embedded_color=True)
        box = im.getbbox()
        if not box:
            return False
        im = im.crop(box)
        side = max(im.size)
        sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        sq.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
        sq.resize((px, px), Image.LANCZOS).save(path)
        return True
    except Exception:  # noqa: BLE001 - a clip without its emoji is better than no clip
        return False


def _split_lines(words, n, widest):
    """The words on n lines, split where the widest line comes out narrowest."""
    best = [None, None]

    def go(start, left, acc):
        if left == 1:
            lines = acc + [" ".join(words[start:])]
            w = widest(lines)
            if best[0] is None or w < best[0]:
                best[0], best[1] = w, lines
            return
        for cut in range(start + 1, len(words) - left + 2):
            go(cut, left - 1, acc + [" ".join(words[start:cut])])
    go(0, n, [])
    return best[1]


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



def hook_scale(font) -> float:
    """Scale heading fonts so their capital letters have the same apparent height."""
    base, f = _Font.get(HOOK["font"]), _Font.get(font)
    return (base.cap / (base.asc + base.desc)) / (f.cap / (f.asc + f.desc))


def _hook_events(hook, dur, y, info=None, look=None, width=W, height=H, position=None):
    """Draw template-aware hook text, optional box and emoji at a scalable/adjustable position."""
    scale = width / W
    position = clean_position(position)
    if look:
        font, ink, boxc, boxed = look["font"], _bgr(look["color"]), _bgr(look["bgc"]), look["bg"]
    else:
        font, ink, boxc, boxed = HOOK["font"], HOOK["ink"], HOOK["box"], True
    f = _Font.get(font)
    size = int(round((look.get("size", HOOK["size"]) if look else HOOK["size"]) * hook_scale(font) * scale))
    text, emoji = split_hook(hook)
    if look and look.get("upper"):
        text = text.upper()
    if info is None or not emoji_font():
        emoji = []
    words = text.split()
    if not words and not emoji:
        return []

    gap = lambda sz: sz * 0.16
    e_w = lambda sz: f.em(sz) * 1.02
    extra = lambda sz: len(emoji) * (e_w(sz) + gap(sz))
    max_w = int(HOOK["max_w"] * scale)
    pad_x, pad_y, radius = (int(HOOK[k] * scale) for k in ("pad_x", "pad_y", "radius"))

    def widths(lines, sz):
        ws = [f.width(line, sz) for line in lines]
        if ws:
            ws[-1] += extra(sz)
        return ws

    lines = [" ".join(words)]
    for count in (1, 2):
        if count > max(1, len(words)):
            break
        lines = _split_lines(words, count, lambda ls: max(widths(ls, size))) if words else [""]
        if max(widths(lines, size)) <= max_w:
            break
    widest = max(widths(lines, size))
    if widest > max_w:
        size = max(int(40 * scale), int(size * max_w / widest))
        widest = max(widths(lines, size))

    line_h = f.em(size) * 1.16
    bw, bh = widest + 2 * pad_x, line_h * len(lines) + 2 * pad_y
    cx = width * position["x"] if position else width / 2
    cy_center = height * position["y"] if position else y
    x0, y0, r = cx - bw / 2, cy_center - bh / 2, min(radius, bh / 2)
    x1, y1 = x0 + bw, y0 + bh
    n = lambda v: f"{v:.0f}"
    box = (f"m {n(x0 + r)} {n(y0)} l {n(x1 - r)} {n(y0)} b {n(x1)} {n(y0)} {n(x1)} {n(y0)} {n(x1)} {n(y0 + r)} "
           f"l {n(x1)} {n(y1 - r)} b {n(x1)} {n(y1)} {n(x1)} {n(y1)} {n(x1 - r)} {n(y1)} "
           f"l {n(x0 + r)} {n(y1)} b {n(x0)} {n(y1)} {n(x0)} {n(y1)} {n(x0)} {n(y1 - r)} "
           f"l {n(x0)} {n(y0 + r)} b {n(x0)} {n(y0)} {n(x0)} {n(y0)} {n(x0 + r)} {n(y0)}")
    span = f"{_ts(0)},{_ts(dur)}"
    ev = [f"Dialogue: 3,{span},Hook,,0,0,0,,{{\\an7\\pos(0,0)\\fad(160,0)\\c&H{boxc}&\\p1}}{box}{{\\p0}}"] if boxed else []
    edge = look.get("outline", 0 if boxed else 6) if look else 0
    txt = (f"\\fn{font}\\c&H{ink}&" + (f"\\bord{edge}\\3c&H000000&" if edge else "")) if look else ""
    for i, line in enumerate(lines):
        mid = cy_center - line_h * (len(lines) - 1) / 2 + i * line_h
        line_cx = cx
        if emoji and i == len(lines) - 1:
            tw = f.width(line, size)
            line_cx = cx - extra(size) / 2
            x = cx - (tw + extra(size)) / 2 + tw + gap(size)
            for ch in emoji:
                info["emoji"].append({"ch": ch, "x": int(round(x)), "y": int(round(mid - e_w(size) / 2)),
                                      "size": int(round(e_w(size)))})
                x += e_w(size) + gap(size)
        if line:
            ev.append(f"Dialogue: 4,{span},Hook,,0,0,0,,{{\\an5\\pos({line_cx:.0f},{mid - f.cap_shift(size):.0f})\\fad(160,0)\\fs{size}{txt}}}{line}")
    if info is not None:
        info["bottom"] = y1
    return ev


def _bgr(rgb):
    return rgb[4:6] + rgb[2:4] + rgb[0:2]


def _cap_style(cap):
    """A template's caption settings (or an old style name) as what the caption drawing below needs."""
    if not isinstance(cap, dict):
        cap = templates.legacy(cap if cap in STYLES else "bounce")["cap"]
    cap = templates.clean_look({"cap": cap})["cap"]
    size = cap["size"]
    pop = cap["pop"] if cap["anim"] == "pop" else 100
    return {"font": cap["font"], "size": size, "base": _bgr(cap["color"]), "active": _bgr(cap["hi"]),
            "strong": _bgr(cap["key"]), "outline": cap["outline"], "shadow": 4 if cap["shadow"] else 0,
            "pop": pop, "upper": cap["upper"], "per": cap["per"], "anim": cap["anim"], "bg": cap["bg"], "bgc": _bgr(cap["bgc"])}


def _round_box(x0, y0, x1, y1, r):
    n = lambda v: f"{v:.0f}"                                                         # noqa: E731
    return (f"m {n(x0 + r)} {n(y0)} l {n(x1 - r)} {n(y0)} b {n(x1)} {n(y0)} {n(x1)} {n(y0)} {n(x1)} {n(y0 + r)} "
            f"l {n(x1)} {n(y1 - r)} b {n(x1)} {n(y1)} {n(x1)} {n(y1)} {n(x1 - r)} {n(y1)} "
            f"l {n(x0 + r)} {n(y1)} b {n(x0)} {n(y1)} {n(x0)} {n(y1)} {n(x0)} {n(y1 - r)} "
            f"l {n(x0)} {n(y0 + r)} b {n(x0)} {n(y0)} {n(x0)} {n(y0)} {n(x0 + r)} {n(y0)}")


_SCRIPT_RANGES = {"ur": re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]"), "hi": re.compile(r"[\u0900-\u097F]")}


def _in_script(text, script) -> bool:
    """Is this text written (mostly) in the given script's own letters (Urdu or Devanagari)?"""
    rx, letters = _SCRIPT_RANGES.get(script), [c for c in str(text or "") if c.isalpha()]
    return bool(rx and letters and sum(1 for c in letters if rx.match(c)) >= len(letters) / 2)



def build_ass(words, start, end, hook, style_name, highlight, hook_y, cap_y, note="", info=None, show_hook=True,
              hook_look=None, script="", width=W, height=H, hook_position=None, caption_position=None) -> str:
    """Build template-aware captions in the chosen output resolution, with draggable text placement.

    Backwards compatibility: older CustomPeakCut callers passed width and height as the 9th and 10th
    positional arguments immediately after cap_y. New template-aware options are passed by keyword.
    """
    if isinstance(note, (int, float)) and isinstance(info, (int, float)):
        width, height = int(note), int(info)
        note, info = "", None
    scale = width / W
    hook_position = clean_position(hook_position)
    caption_position = clean_position(caption_position)
    caption_cx = width * caption_position["x"] if caption_position else width / 2
    caption_center_y = height * caption_position["y"] if caption_position else cap_y

    st = _cap_style(style_name)
    st["size"] = max(24, int(round(st["size"] * scale)))
    st["outline"] = max(1, int(round(st["outline"] * scale)))
    cap_max_w = int(CAP_MAX_W * scale)
    if script in SCRIPT_FONTS:
        name, _font_file, grow = SCRIPT_FONTS[script]
        st.update(font=name, size=int(st["size"] * grow), upper=False)
        if _in_script(hook, script):
            hook_look = dict(hook_look or templates.clean_look({})["hook"], font=name, upper=False)

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
Style: Cap,{st['font']},{st['size']},&H00{st['base']},&H00{st['base']},&H00000000,&H70000000,0,0,0,0,100,100,0,0,1,{st['outline']},{st['shadow']},5,0,0,0,1
Style: Hook,{HOOK['font']},{int(HOOK['size'] * scale)},&H00{HOOK['ink']},&H00{HOOK['ink']},&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1
Style: Note,{HOOK['font']},{int(46 * scale)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,4,0,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    dur = end - start
    ev = _hook_events(_clean(hook), dur, hook_y, info, hook_look, width, height, hook_position) if show_hook else []
    note = _clean(note)[:60]
    if note:
        nf, ns = _Font.get(HOOK["font"]), max(18, int(46 * scale))
        if nf.width(note, ns) > width * 0.87:
            ns = max(18, int(ns * (width * 0.87) / nf.width(note, ns)))
        ny = ((info or {}).get("bottom") or hook_y) + int(50 * scale)
        ev.append(f"Dialogue: 4,{_ts(0)},{_ts(dur)},Note,,0,0,0,,{{\\an5\\pos({caption_cx:.0f},{ny:.0f})\\fs{ns}}}{note}")

    f = _Font.get(st["font"])
    inside = [dict(w, w=_clean(w["w"])) for w in words if w["s"] >= start - 0.05 and w["s"] < end]
    inside = sorted((w for w in inside if w["w"]), key=lambda w: w["s"])
    for i, w in enumerate(inside[:-1]):
        w["e"] = max(w["s"], min(w["e"], inside[i + 1]["s"]))
    groups = _groups(inside, st["per"])

    if script in SCRIPT_FONTS:
        # Urdu and Devanagari are shaped as a complete line, while timing still highlights the word being spoken.
        for gi, g in enumerate(groups):
            g_start = max(0.0, g[0]["s"] - start)
            g_end = min(g[-1]["e"] + 0.25, groups[gi + 1][0]["s"] if gi + 1 < len(groups) else end) - start
            if g_end - g_start < 0.02:
                continue
            texts = [re.sub(r"[.,;:]+$", "", x["w"]) for x in g]
            size = st["size"]
            line_text = " ".join(texts)
            wide = f.width(line_text, size)
            if wide > cap_max_w:
                size = max(int(36 * scale), int(size * cap_max_w / wide))
            cx = max(10, min(width - 10, caption_cx))
            cy = max(size, min(height - size, caption_center_y)) - f.cap_shift(size)
            pos = f"\\an5\\pos({cx:.0f},{cy:.0f})\\fs{size}"
            base = [st["strong"] if _key(x["w"]) in strong else st["base"] for x in g]

            def script_line(on):
                parts = []
                for ix, text in enumerate(texts):
                    active = st["active"]
                    if st.get("gradient"):
                        spectrum = ("00E6FF", "4DFF72", "FF73BE", "35AEFF", "3C3CFF")
                        active = spectrum[(gi * 2 + ix) % len(spectrum)]
                    lit = st["anim"] != "none" and (ix == on or (st["anim"] == "fill" and 0 <= ix < on))
                    parts.append(f"{{\\c&H{active if lit else base[ix]}&}}{text}")
                return " ".join(parts)

            marks = [max(g_start, x["s"] - start) for x in g] + [g_end]
            if st["anim"] == "none":
                ev.append(f"Dialogue: 1,{_ts(g_start)},{_ts(g_end)},Cap,,0,0,0,,{{{pos}}}{script_line(-1)}")
                continue
            if marks[0] - g_start >= 0.02:
                ev.append(f"Dialogue: 1,{_ts(g_start)},{_ts(marks[0])},Cap,,0,0,0,,{{{pos}}}{script_line(-1)}")
            for ix in range(len(g)):
                a, b = marks[ix], marks[ix + 1]
                if b - a >= 0.02:
                    ev.append(f"Dialogue: 1,{_ts(a)},{_ts(b)},Cap,,0,0,0,,{{{pos}}}{script_line(ix)}")
        return head + "\n".join(ev) + "\n"

    for gi, g in enumerate(groups):
        g_start = max(0.0, g[0]["s"] - start)
        g_end = min(g[-1]["e"] + 0.25, groups[gi + 1][0]["s"] if gi + 1 < len(groups) else end) - start
        if g_end - g_start < 0.02:
            continue

        texts = []
        for w in g:
            t = re.sub(r"[.,;:]+$", "", w["w"])
            texts.append(t.upper() if st["upper"] else t)

        if not all(roman.drawable(t) for t in texts):
            line_text = " ".join(texts)
            fs = max(int(44 * scale), min(int(st["size"] * 0.7), int(1500 * scale / max(1, len(line_text)) * 1.6)))
            approx_w = min(cap_max_w, max(1, len(line_text) * fs * 0.55))
            cx = max(approx_w / 2 + 6, min(width - approx_w / 2 - 6, caption_cx))
            cy = max(fs * 0.8, min(height - fs * 0.8, caption_center_y))
            ev.append(f"Dialogue: 1,{_ts(g_start)},{_ts(g_end)},Cap,,60,60,0,,{{\\an5\\pos({cx:.0f},{cy:.0f})\\q0\\fs{fs}}}{line_text}")
            continue

        size = st["size"]
        gap = (f.width("n n", size) - 2 * f.width("n", size)
               + (2 * st["outline"] + 6) * size / max(1, st["size"])
               + (size * 0.2 if st["anim"] == "box" else 0))
        total = sum(f.width(t, size) for t in texts) + gap * (len(texts) - 1)
        if total > cap_max_w:
            size = max(int(36 * scale), int(size * cap_max_w / total))
            gap = (f.width("n n", size) - 2 * f.width("n", size)
                   + (2 * st["outline"] + 6) * size / max(1, st["size"])
                   + (size * 0.2 if st["anim"] == "box" else 0))
            total = sum(f.width(t, size) for t in texts) + gap * (len(texts) - 1)

        cx = max(total / 2 + 6, min(width - total / 2 - 6, caption_cx))
        anchor_y = max(size * 0.8, min(height - size * 0.8, caption_center_y))
        cy = anchor_y - f.cap_shift(size)
        x = cx - total / 2

        if st["bg"]:
            ch = f.cap * size / (f.asc + f.desc)
            px, py = size * 0.28, ch * 0.55
            box = _round_box(x - px, anchor_y - ch / 2 - py, x + total + px, anchor_y + ch / 2 + py,
                             min(size * 0.22, ch))
            ev.append(f"Dialogue: 0,{_ts(g_start)},{_ts(g_end)},Cap,,0,0,0,,{{\\an7\\pos(0,0)\\bord0\\shad0\\c&H{st['bgc']}&\\p1}}{box}{{\\p0}}")

        pop_scale = st["pop"]
        for ix, (word, text) in enumerate(zip(g, texts)):
            word_width = f.width(text, size)
            pop = max(104, min(pop_scale, 100 + int(2200 / max(word_width, 1)))) if pop_scale > 100 else 100
            pos = f"\\an5\\pos({x + word_width / 2:.0f},{cy:.0f})\\fs{size}"
            x += word_width + gap
            a = max(g_start, word["s"] - start)
            b = (g[ix + 1]["s"] - start) if ix + 1 < len(g) else g_end
            base_color = st["strong"] if _key(word["w"]) in strong else st["base"]
            active_color = st["active"]
            if st.get("gradient"):
                spectrum = ("00E6FF", "4DFF72", "FF73BE", "35AEFF", "3C3CFF")
                active_color = spectrum[(gi * 2 + ix) % len(spectrum)]
            anim = st["anim"]

            if anim == "none":
                ev.append(f"Dialogue: 1,{_ts(g_start)},{_ts(g_end)},Cap,,0,0,0,,{{{pos}\\c&H{base_color}&}}{text}")
                continue
            if a - g_start >= 0.02:
                ev.append(f"Dialogue: 1,{_ts(g_start)},{_ts(a)},Cap,,0,0,0,,{{{pos}\\c&H{base_color}&}}{text}")
            if b - a >= 0.02:
                if st.get("glow"):
                    glow_outline = max(10, st["outline"] + int(4 * scale))
                    ev.append(f"Dialogue: 1,{_ts(a)},{_ts(b)},Cap,,0,0,0,,{{{pos}\\c&H{active_color}&\\3c&H{active_color}&\\bord{glow_outline}\\blur3\\alpha&H55&}}{text}")
                if anim == "pop":
                    ev.append(f"Dialogue: 2,{_ts(a)},{_ts(b)},Cap,,0,0,0,,{{{pos}\\c&H{active_color}&\\fscx94\\fscy94"
                              f"\\t(0,90,\\fscx{pop}\\fscy{pop})\\t(90,200,\\fscx{pop - 5}\\fscy{pop - 5})}}{text}")
                elif anim == "box":
                    ch = f.cap * size / (f.asc + f.desc)
                    px, py = size * 0.16, ch * 0.42
                    mid = anchor_y
                    bx = x - gap - word_width / 2
                    box = _round_box(bx - px, mid - ch / 2 - py, bx + word_width + px,
                                     mid + ch / 2 + py, min(size * 0.16, ch))
                    ev.append(f"Dialogue: 0,{_ts(a)},{_ts(b)},Cap,,0,0,0,,{{\\an7\\pos(0,0)\\bord0\\shad0\\c&H{active_color}&\\p1}}{box}{{\\p0}}")
                    ev.append(f"Dialogue: 2,{_ts(a)},{_ts(b)},Cap,,0,0,0,,{{{pos}\\bord0\\shad0\\c&H{base_color}&}}{text}")
                else:
                    ev.append(f"Dialogue: 2,{_ts(a)},{_ts(b)},Cap,,0,0,0,,{{{pos}\\c&H{active_color}&}}{text}")
            if g_end - b >= 0.02:
                if anim == "pop":
                    ev.append(f"Dialogue: 1,{_ts(b)},{_ts(g_end)},Cap,,0,0,0,,{{{pos}\\c&H{base_color}&\\fscx{pop - 5}\\fscy{pop - 5}"
                              f"\\t(0,90,\\fscx100\\fscy100)}}{text}")
                else:
                    final_color = active_color if anim == "fill" else base_color
                    ev.append(f"Dialogue: 1,{_ts(b)},{_ts(g_end)},Cap,,0,0,0,,{{{pos}\\c&H{final_color}&}}{text}")

    return head + "\n".join(ev) + "\n"



PIP_W = 380
PIP_MARGIN = 26


def _filter(layout, fg_h, facecam=None, custom=None, duration=60.0, width=W, height=H, crop=""):
    """The video composition, scaled to the selected export resolution."""
    scale = width / W
    if layout == "custom":
        return custom_layouts.filter_complex(custom, width, height, config.OUT_FPS, duration) + ";"
    if layout == "gameplay" and facecam:
        fx, fy, fw, fh = (int(v) for v in facecam)
        if fw > 8 and fh > 8:
            pip_w, pip_margin = round(PIP_W * scale), round(PIP_MARGIN * scale)
            pip_h = max(2, int(round(pip_w * fh / fw)))
            return (f"[0:v]{crop}fps={config.OUT_FPS},split=2[base][fc];"
                    f"[base]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1[b];"
                    f"[fc]crop={fw}:{fh}:{fx}:{fy},scale={pip_w}:{pip_h},setsar=1[p];"
                    f"[b][p]overlay={width - pip_w - pip_margin}:{pip_margin}[v0];")
    fill = f"[0:v]{crop}fps={config.OUT_FPS},scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
    if layout == "crop" or (layout == "gameplay" and not facecam):
        return fill + ",setsar=1[v0];"
    if layout == "left":
        return fill + ":0:0,setsar=1[v0];"
    if layout == "right":
        return fill + ":in_w-out_w:0,setsar=1[v0];"
    if layout == "fit":
        return f"[0:v]{crop}fps={config.OUT_FPS},scale={width}:{fg_h},pad={width}:{height}:0:(oh-ih)/2:black,setsar=1[v0];"
    if layout == "split":
        half_h = height // 2
        half = f"scale={width}:{half_h}:force_original_aspect_ratio=increase,crop={width}:{half_h}"
        return (f"[0:v]{crop}fps={config.OUT_FPS},split=2[l][r];[l]crop=iw/2:ih:0:0,{half}[t];"
                f"[r]crop=iw/2:ih:iw/2:0,{half}[u];[t][u]vstack,setsar=1[v0];")
    blur_w, blur_h = round(270 * scale), round(480 * scale)
    blur = max(1, round(6 * scale))
    return (f"[0:v]{crop}fps={config.OUT_FPS},split=2[a][b];"
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


def _even(v):
    return max(2, int(round(v / 2)) * 2)


def cam_plan(dst, src_box, src_w, src_h, width=W, height=H):
    """Where the streamer's cam comes from (src_box: shares of the source frame) and where it goes (dst: a style's
    box, shares of the 9:16 frame, 0-100). None without both. A cam the full width of the frame at its top or
    bottom is stacked: the game fills the rest of the frame instead of sitting behind it."""
    if not dst or not src_box:
        return None
    bx, by, bw, bh = (_even(width * dst["x"] / 100) if dst["x"] else 0), (_even(height * dst["y"] / 100) if dst["y"] else 0), _even(width * dst["w"] / 100), _even(height * dst["h"] / 100)
    bw, bh = min(bw, width - bx), min(bh, height - by)
    stack = bw >= width - 4 and (by <= 4 or by + bh >= height - 4)
    if stack:
        bx, bw = 0, width
        by = 0 if by <= 4 else height - bh
    sx, sy = _even(src_w * src_box["x"]) if src_box["x"] else 0, _even(src_h * src_box["y"]) if src_box["y"] else 0
    sw, sh = min(_even(src_w * src_box["w"]), src_w - sx), min(_even(src_h * src_box["h"]), src_h - sy)
    return {"bx": bx, "by": by, "bw": bw, "bh": bh, "sx": sx, "sy": sy, "sw": sw, "sh": sh, "stack": stack,
            "seam": by + bh if by == 0 else by}


QUALITIES = (1080, 1440, 2160)
SLACK = 1.4          # how much a part may be enlarged and still look sharp


def needed_height(look, cam_src=None, aspect=16 / 9) -> int:
    """The video quality (its height) a style needs so nothing in its clips is blown up more than SLACK: 1080 for a
    full frame, more when the style zooms in (Fill the screen, Zoomed in, a part of the video, the streamer's cam).
    The highest the video has is fetched, up to this."""
    look = templates.clean_look(look) if isinstance(look, dict) else templates.legacy()
    gs = look.get("game_src") or {"x": 0, "y": 0, "w": 1.0, "h": 1.0}
    cam = cam_plan(look.get("cam"), cam_src or {"x": 0, "y": 0, "w": 0.22, "h": 0.22}, 1920, 1080) if look.get("cam") else None

    def want(rw, rh, dw, dh):        # the source height at which this part (shares rw x rh) fills dw x dh sharply
        return max(dw / (rw * aspect), dh / rh) / SLACK
    if cam and cam["stack"]:
        dw, dh = W, H - cam["bh"]
    elif look["layout"] in _FILLS:
        dw, dh = W, H
    elif look["layout"] == "zoom":
        dw, dh = W, 1000
    elif look["layout"] == "split":          # each half of the video fills half the frame
        dw, dh = W * 2, H / 2
    else:                            # the blurred fill: the whole width, as tall as the part is
        dw, dh = W, W * gs["h"] / (gs["w"] * aspect)
    need = want(gs["w"], gs["h"], dw, dh)
    if cam:
        box = cam_src or {"w": 0.22, "h": 0.22}
        need = max(need, want(box["w"], box["h"], cam["bw"], cam["bh"]))
    return next((q for q in QUALITIES if q >= need), QUALITIES[-1])


def cam_frame(cam, look_style, out_dir: Path, name: str) -> dict:
    """The pictures that give the cam its rounded corners and border, made for this box: {"mask": the shape (white
    where the cam shows), "border": the outline on a clear background}; empty when the style has neither."""
    st = look_style or {}
    r, bw, out = int(st.get("r") or 0), int(st.get("bw") or 0), {}
    if not (r or bw):
        return out
    from PIL import Image, ImageDraw
    w, h = cam["bw"], cam["bh"]
    r = int(min(w, h) * min(r, 50) / 100)            # % of the shorter side: 50 is fully round (a circle in a square box)
    k = 3                                                  # drawn 3x larger and shrunk: smooth curved edges
    if r:
        m = Image.new("L", (w * k, h * k), 0)
        ImageDraw.Draw(m).rounded_rectangle((0, 0, w * k - 1, h * k - 1), radius=r * k, fill=255)
        out["mask"] = out_dir / f"{name}.cammask.png"
        m.resize((w, h), Image.LANCZOS).save(out["mask"])
    if bw:
        rgb = tuple(int(str(st.get("bc") or "FFFFFF")[i:i + 2], 16) for i in (0, 2, 4))
        b = Image.new("RGBA", (w * k, h * k), (0, 0, 0, 0))
        half = bw * k / 2
        ImageDraw.Draw(b).rounded_rectangle((half, half, w * k - 1 - half, h * k - 1 - half), radius=max(0, (r - bw / 2)) * k,
                                            outline=rgb + (255,), width=bw * k)
        out["border"] = out_dir / f"{name}.camborder.png"
        b.resize((w, h), Image.LANCZOS).save(out["border"])
    return out


def cam_filter(cam, layout, fg_h, crop="", frame=None, width=W, height=H, custom=None, duration=60.0):
    """The video with the streamer's cam: the game as the layout has it (or filling the rest of the frame when the
    cam is stacked), and the cam cut from the source, filling its box. `frame`: {"mask": input index, "border":
    input index} of the pictures that round its corners and draw its border."""
    frame = frame or {}
    fps = config.OUT_FPS
    if cam["stack"]:
        gy, gh = (cam["bh"], height - cam["bh"]) if cam["by"] == 0 else (0, cam["by"])
        game = (f"[s0]{crop}fps={fps},format=yuv420p,scale={width}:{gh}:force_original_aspect_ratio=increase,crop={width}:{gh},"
                f"pad={width}:{height}:0:{gy}:black,setsar=1[vg];")
    else:
        game = _filter(layout, fg_h, custom=custom, duration=duration, width=width, height=height, crop=crop).replace("[0:v]", "[s0]", 1).replace("[v0];", "[vg];")
    return ("[0:v]split=2[s0][s1];" + game +
            f"[s1]fps={fps},format=yuv420p,crop={cam['sw']}:{cam['sh']}:{cam['sx']}:{cam['sy']},"
            f"scale={cam['bw']}:{cam['bh']}:force_original_aspect_ratio=increase,crop={cam['bw']}:{cam['bh']},setsar=1"
            + (f",format=rgba[cr];[{frame['mask']}:v]format=gray,scale={cam['bw']}:{cam['bh']}[cmk];[cr][cmk]alphamerge[cm];"
               if "mask" in frame else "[cm];")
            + (f"[vg][cm]overlay={cam['bx']}:{cam['by']}:shortest=1[vc];[vc][{frame['border']}:v]overlay={cam['bx']}:{cam['by']}:shortest=1[v0];"
               if "border" in frame else f"[vg][cm]overlay={cam['bx']}:{cam['by']}:shortest=1[v0];"))


LOGO_BOX = {"s": (220, 70), "m": (320, 100), "l": (420, 130)}          # the most room a logo gets, by size
LOGO_AT = {"tl": "44:56", "tc": "(W-w)/2:56", "tr": "W-w-44:56", "bl": "44:H-h-300", "bc": "(W-w)/2:H-h-300", "br": "W-w-44:H-h-300"}
LOGO_STILL, LOGO_MOVING = (".png", ".jpg", ".jpeg", ".webp"), (".gif", ".mp4", ".mov", ".webm")


def _logo(logo, n, width=W, height=H):
    """ffmpeg inputs and the filter that scales this logo for input n. A full-frame one (a 1080x1920 template with the
    logo already in place) covers the whole clip; any other sits in a corner, clear of the heading and the captions."""
    path = Path(logo["path"])
    ext = path.suffix.lower()
    args = ["-ignore_loop", "0"] if ext == ".gif" else ["-stream_loop", "-1"] if ext in LOGO_MOVING else ["-loop", "1"]
    if logo.get("pos") == "full":
        return args + ["-i", str(path)], f"[{n}:v]scale={width}:{height},format=rgba[lg]", "0:0"
    bw, bh = LOGO_BOX.get(logo.get("size"), LOGO_BOX["m"])
    return (args + ["-i", str(path)], f"[{n}:v]scale=w={bw}:h={bh}:force_original_aspect_ratio=decrease,format=rgba[lg]",
            LOGO_AT.get(logo.get("pos"), LOGO_AT["tl"]))


_qsv_ok = None
RENDER_SECONDS = 600      # one clip's video encode; far beyond normal, so a frozen encoder is stopped, not waited on



_qsv_ok = None
RENDER_SECONDS = 600


def render_clip(src: Path, out_dir: Path, name: str, clip: dict, words: list, src_w: int, src_h: int,
                extras: dict = None) -> dict:
    """Render a template-aware clip at its chosen size, codec and quality, retaining custom filters and placement."""
    extras = extras or {}
    out_dir.mkdir(parents=True, exist_ok=True)
    start, end = float(clip["start"]), float(clip["end"])
    settings = export_settings.clean(clip)
    width, height = export_settings.dimensions(settings)

    look = (templates.clean_look(clip["look"]) if isinstance(clip.get("look"), dict)
            else templates.legacy(clip.get("style", "bounce"), clip.get("layout", "blur")))
    gs, crop = look.get("game_src"), ""
    if gs:
        gx = _even(src_w * gs["x"]) if gs["x"] else 0
        gy = _even(src_h * gs["y"]) if gs["y"] else 0
        gw = min(_even(src_w * gs["w"]), src_w - gx)
        gh = min(_even(src_h * gs["h"]), src_h - gy)
        crop = f"crop={gw}:{gh}:{gx}:{gy},"
    layout, fg_h, hook_y, cap_y = geometry(gw if gs else src_w, gh if gs else src_h,
                                           "custom" if clip.get("layout") == "custom" else look["layout"], width, height)
    cam_src = look.get("cam_src") or extras.get("cam")
    cam = cam_plan(look.get("cam"), cam_src, src_w, src_h, width, height) if look.get("cam") else None
    face = clip.get("facecam") if layout == "gameplay" and not cam and not gs else None
    if layout == "gameplay" and not (face and len(face) == 4):
        layout, face = "crop", None
    hook_y = _hook_y(layout, hook_y, face, width)
    if cam and cam["stack"]:
        cap_y = cam["seam"]
        hook_y = height - round(380 * width / W) if cam["by"] == 0 else round(300 * width / W)
    if look["cap"]["y"] is not None:
        cap_y = int(height * look["cap"]["y"] / 100)
    if look["hook"]["y"] is not None:
        hook_y = int(height * look["hook"]["y"] / 100)

    info = {"emoji": []}
    show_caps = look["cap"]["show"] and clip.get("captions", True) is not False
    ass = build_ass(
        words if show_caps else [], start, end, clip.get("hook", ""), look["cap"],
        clip.get("highlight_words", []), hook_y, cap_y, note=extras.get("note", ""),
        info=info, show_hook=look["hook"]["show"], hook_look=look["hook"],
        script=clip.get("script") or "", width=width, height=height,
        hook_position=clip.get("hook_position"), caption_position=clip.get("caption_position"),
    )
    workdir = Path(tempfile.mkdtemp(prefix="pk"))
    try:
        meta = {"title": clip.get("title") or "", "description": clip.get("description") or "",
                "comment": clip.get("description") or ""}
        return _render_in(
            workdir, src, out_dir, name, start, end, layout, fg_h, ass, look, cam, crop, face, info, extras, meta,
            width=width, height=height, custom=clip.get("custom_layout"), duration=end - start,
            codec=settings["export_encoder"], quality=settings["export_quality"],
            filter_preset=clip.get("filter", "original"), filter_strength=clip.get("filter_strength", 70),
        ) | {"layout": layout}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _render_in(work, src, out_dir, name, start, end, layout, fg_h, ass, look, cam, crop, face,
               info, extras, meta, width=W, height=H, custom=None, duration=60.0,
               codec="h264", quality="balanced", filter_preset="original", filter_strength=70) -> dict:
    """Compose template elements and encode using the requested hardware/software encoder candidates."""
    (work / f"{name}.ass").write_text(ass, encoding="utf-8")
    (work / "f").mkdir()
    for font in config.FONTS_DIR.glob("*.ttf"):
        shutil.copyfile(font, work / "f" / font.name)

    more, last, n, frame = [], "v0", 1, {}
    if cam:
        for key, picture in cam_frame(cam, look.get("cam_style"), work, name).items():
            more += ["-loop", "1", "-i", picture.name]
            frame[key] = n
            n += 1

    if cam:
        fc = cam_filter(cam, layout, fg_h, crop, frame, width=width, height=height,
                        custom=custom, duration=duration)
    else:
        fc = _filter(layout, fg_h, face, custom=custom, duration=duration,
                     width=width, height=height, crop=crop)

    color = _color_filter(filter_preset, filter_strength)
    if color:
        fc += f"[v0]{color}[vcol];[vcol]ass={name}.ass:fontsdir=f[v1]"
    else:
        fc += f"[v0]ass={name}.ass:fontsdir=f[v1]"
    last = "v1"

    logo = extras.get("logo")
    if logo and Path(logo.get("path", "")).is_file():
        args, logo_filter, at = _logo(logo, n, width, height)
        more += args
        fc += f";{logo_filter};[{last}][lg]overlay={at}:shortest=1[vl]"
        last, n = "vl", n + 1

    for ix, emoji in enumerate(info.get("emoji") or []):
        picture = work / f"{name}.e{ix}.png"
        if emoji_png(emoji["ch"], picture, emoji["size"]):
            more += ["-loop", "1", "-i", picture.name]
            fc += (f";[{n}:v]format=rgba,fade=t=in:st=0:d=0.16:alpha=1[e{ix}];"
                   f"[{last}][e{ix}]overlay={emoji['x']}:{emoji['y']}:shortest=1[ve{ix}]")
            last, n = f"ve{ix}", n + 1

    base = [
        "ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}", "-t", f"{end - start:.2f}",
        "-i", str(src), *more, "-filter_complex", fc, "-map", f"[{last}]", "-map", "0:a:0",
        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
    ]
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
    error, selected = None, None
    output = work / f"{name}.mp4"
    for label, encoder_args in candidates:
        output.unlink(missing_ok=True)
        process = subprocess.run(
            base + encoder_args + [output.name], cwd=work, capture_output=True, text=True,
            encoding="utf-8", errors="replace", creationflags=NO_WINDOW, timeout=RENDER_SECONDS,
        )
        if process.returncode == 0 and output.is_file() and output.stat().st_size > 0:
            selected = label
            break
        error = process.stderr[-1200:] or f"{label} returned exit code {process.returncode}"
    if not selected:
        raise RuntimeError(f"Export failed with the available {codec.upper()} encoders: {error}")

    cover_t = min(1.2, (end - start) / 2)
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{cover_t:.2f}", "-i", output.name,
         "-frames:v", "1", "-q:v", "3", f"{name}.jpg"], cwd=work)
    for ext in ("mp4", "jpg", "ass"):
        shutil.move(str(work / f"{name}.{ext}"), str(out_dir / f"{name}.{ext}"))
    return {
        "file": f"{name}.mp4", "cover": f"{name}.jpg", "encoder": selected,
        "resolution": f"{width}x{height}", "export_quality": quality,
    }
