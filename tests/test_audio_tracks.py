"""YouTube dubbed audio discovery and exact track selection."""
import os
import sys
import tempfile

os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-audio-tracks-")
os.environ["DATABASE_URL"] = ""
os.environ["PEAKCUT_ACCOUNTS"] = "0"
sys.path.insert(0, ".")

from studio import auth, ctx, db, jobs, media  # noqa: E402

fails = []


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)


formats = [
    {"acodec": "opus", "vcodec": "none", "language": "en", "format_note": "English original (default), medium"},
    {"acodec": "opus", "vcodec": "none", "language": "hi", "format_note": "Hindi, medium"},
    {"acodec": "opus", "vcodec": "none", "language": "hi", "format_note": "Hindi, low"},
    {"acodec": "none", "vcodec": "avc1", "language": "en", "format_note": "English video only"},
    {"acodec": "opus", "vcodec": "none", "language": "pt-BR", "format_note": "Portuguese (Brazil), medium"},
    {"acodec": "opus", "vcodec": "none", "format_note": "No language metadata"},
    {"acodec": "opus", "vcodec": "none", "language": "bad code", "format_note": "Unsafe"},
]
tracks = media.audio_tracks(formats)
resolution_formats = [
    {"acodec": "opus", "vcodec": "none", "width": 7680, "height": 4320},
    {"acodec": "none", "vcodec": "avc1", "width": 1920, "height": 1080},
    {"acodec": "none", "vcodec": "vp9", "width": 2560, "height": 1440},
]
check("maximum source resolution ignores audio-only formats and finds the highest video format",
      media.max_video_resolution(resolution_formats) == "1440p")
check("portrait source resolution uses its shorter dimension",
      media.max_video_resolution([{"vcodec": "avc1", "width": 1080, "height": 1920}]) == "1080p")
check("source resolution falls back to the video's reported dimensions",
      media.max_video_resolution([], 1920, 1080) == "1080p")
check("unknown source resolution stays unavailable",
      media.max_video_resolution([]) is None)
check("only audio formats with valid language codes are listed",
      [x["code"] for x in tracks] == ["en", "hi", "pt-BR"])
check("duplicate audio formats do not duplicate the same language",
      len([x for x in tracks if x["code"] == "hi"]) == 1)
check("human-readable language names are kept",
      next(x["label"] for x in tracks if x["code"] == "hi") == "Hindi")
check("audio selector uses the exact selected language",
      media._audio_format("hi") == "ba[language=hi][ext=m4a]/ba[language=hi]")
check("video selector pairs video with the selected language audio",
      "ba[language=hi]" in media._video_format(2160, "hi")
      and "ba[language=hi][ext=m4a]" in media._video_format(2160, "hi"))
check("selected-language format does not silently fall back to the default dub",
      media._video_format(2160, "hi").count("ba[language=hi]") == 3
      and "b[height<=2160][language=hi]" in media._video_format(2160, "hi"))
check("default audio selector keeps previous behaviour",
      media._audio_format(None) == "ba[ext=m4a]/ba/worst")
check("default video selector remains unchanged",
      media._video_format(2160) ==
      "bv*[height<=2160][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=2160]+ba/b[height<=2160]/b")

check("empty audio language remains the default",
      jobs.clean_options({"audio_language": ""}) == {})
check("valid regional track code is accepted",
      jobs.clean_options({"audio_language": "pt-BR"}) == {"audio_language": "pt-BR"})
invalid = False
try:
    jobs.clean_options({"audio_language": "hi] / ba"})
except ValueError:
    invalid = True
check("format expressions cannot be injected as language codes", invalid)

db.init()
try:
    user = auth.local_user().id
    with ctx.as_user(user):
        job = jobs.create({"type": "url", "url": "https://www.youtube.com/watch?v=abc12345678"},
                          {"audio_language": "hi", "lang": "hinglish"}, enqueue=False)
        check("job stores the selected audio track and matching speech model",
              job["options"]["audio_language"] == "hi" and job["options"]["lang"] == "hinglish")
        jobs.delete(job["id"])
finally:
    db.engine.dispose()

if fails:
    print("FAILED: " + ", ".join(fails))
    sys.exit(1)
print("All audio track tests passed.")
