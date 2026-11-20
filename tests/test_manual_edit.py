"""Manual trim-range validation and optional video-filter settings."""
import json
import os
import sys
import tempfile
from unittest.mock import patch

os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-manual-edit-")
os.environ["DATABASE_URL"] = ""
os.environ["PEAKCUT_ACCOUNTS"] = "0"
sys.path.insert(0, ".")

from studio import auth, ctx, db, jobs, render  # noqa: E402

fails = []


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)


# The default stays visually unchanged, while all filter choices are opt-in.
check("Original is the default and adds no FFmpeg colour filters",
      jobs.DEFAULTS["filter"] == "original" and render._color_filter("original", 100) == "")
check("Gaming Vibrant increases saturation and contrast",
      "saturation=1.340" in render._color_filter("gaming", 100)
      and "contrast=1.090" in render._color_filter("gaming", 100))
check("filter strength zero disables any selected look",
      render._color_filter("warm", 0) == "")
check("black and white reaches zero saturation at full strength",
      render._color_filter("bw", 100) == "eq=saturation=0.000")
check("unknown presets safely fall back to Original",
      render._color_filter("not-a-filter", 100) == "")
clean = jobs.clean_options({"filter": "cool", "filter_strength": 55})
check("valid filter preferences are accepted",
      clean == {"filter": "cool", "filter_strength": 55})
check("filter strength is limited to the 0–100 range",
      jobs.clean_options({"filter_strength": 180})["filter_strength"] == 100
      and jobs.clean_options({"filter_strength": -4})["filter_strength"] == 0)
check("unknown manual filter selections default to Original",
      jobs.clean_options({"filter": "made-up"})["filter"] == "original")

db.init()
try:
    user = auth.local_user().id
    with ctx.as_user(user):
        job = jobs.create({"type": "file", "name": "Manual edit test"},
                          {"filter": "gaming", "filter_strength": 80}, enqueue=False)
        check("new jobs keep their manually selected filter",
              (job["options"]["filter"], job["options"]["filter_strength"]) == ("gaming", 80))
        check("clip render inherits the job's manual filter",
              jobs.clip_video_settings(job, {"id": "inherit"}) == {
                  "filter": "gaming", "filter_strength": 80
              })
        check("clip-level filter can override the job default",
              jobs.clip_video_settings(job, {"id": "override", "filter": "warm", "filter_strength": 35})
              == {"filter": "warm", "filter_strength": 35})

        clip = {"id": "manual-clip", "start": 55.0, "end": 75.0, "src_offset": 50.0,
                "src_end": 90.0, "status": "done", "filter": "gaming", "filter_strength": 80}
        job["clips"].append(clip)
        with patch.object(jobs._q, "put") as queued:
            jobs.request_render(job["id"], clip["id"], {
                "start": 48.0, "end": 88.0, "filter": "cinematic", "filter_strength": 45,
            })
            check("drag trim can extend the clip within its saved source window",
                  clip["start"] == 50.0 and clip["end"] == 88.0)
            check("clip filter override is saved on re-make",
                  clip["filter"] == "cinematic" and clip["filter_strength"] == 45)
            check("manual trim/filter changes queue a new render", queued.called)

            saved = json.loads((__import__("pathlib").Path(job["dir"]) / "job.json")
                               .read_text(encoding="utf-8"))
            saved_clip = saved["clips"][0]
            check("trim and filter changes persist to job.json",
                  saved_clip["start"] == 50.0 and saved_clip["end"] == 88.0
                  and saved_clip["filter"] == "cinematic" and saved_clip["filter_strength"] == 45)

        too_short = False
        try:
            jobs.request_render(job["id"], clip["id"], {"start": 85.0, "end": 87.0})
        except ValueError:
            too_short = True
        check("server rejects manual trims shorter than three seconds", too_short)
        # Full-source uploads use the complete video duration as their trim bound.
        full_job = jobs.create({"type": "file", "name": "Full source trim test"}, {}, enqueue=False)
        full_job["duration"] = 120.0
        full_clip = {"id": "full-source", "start": 100.0, "end": 120.0, "status": "done"}
        full_job["clips"].append(full_clip)
        with patch.object(jobs._q, "put"):
            jobs.request_render(full_job["id"], full_clip["id"], {"start": 150.0, "end": 200.0})
            check("full-source trim cannot extend beyond the video's real duration",
                  full_clip["start"] == 117.0 and full_clip["end"] == 120.0)
        jobs.delete(full_job["id"])
        jobs.delete(job["id"])
finally:
    db.engine.dispose()

if fails:
    print("FAILED: " + ", ".join(fails))
    sys.exit(1)
print("All manual trim and filter checks passed.")
