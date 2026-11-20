"""Drag-position validation, ASS placement, and clip re-make persistence."""
import json
import os
import sys
import tempfile
from unittest.mock import patch

os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-positions-")
os.environ["DATABASE_URL"] = ""
os.environ["PEAKCUT_ACCOUNTS"] = "0"
sys.path.insert(0, ".")

from studio import auth, ctx, db, jobs, render  # noqa: E402

fails = []

def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)

words = [{"w": "WOW", "s": 1.0, "e": 1.6}]
base = render.build_ass(words, 0, 4, "BIG TEXT", "bounce", [], 300, 1380, 1080, 1920)
defaults = render.build_ass(words, 0, 4, "BIG TEXT", "bounce", [], 300, 1380, 1080, 1920,
                            hook_position=None, caption_position=None)
check("clips without saved positions keep the existing default placement", base == defaults)

moved = render.build_ass(words, 0, 4, "BIG TEXT", "bounce", [], 300, 1380, 1080, 1920,
                         hook_position={"x": 0.25, "y": 0.20},
                         caption_position={"x": 0.75, "y": 0.80})
hook_events = [line for line in moved.splitlines() if line.startswith("Dialogue: 4,")]
caption_events = [line for line in moved.splitlines() if line.startswith("Dialogue: 2,")]
check("big text is placed at the dragged horizontal centre", bool(hook_events) and r"\pos(270," in hook_events[0])
check("caption group is placed at the dragged horizontal centre", bool(caption_events) and r"\pos(810," in caption_events[0])
check("dragged vertical positions change the generated subtitle script", moved != base)

check("position JSON strings from the browser are accepted",
      render.clean_position('{"x":0.3,"y":0.4}') == {"x":0.3, "y":0.4})
check("positions are clamped to the visible output frame",
      render.clean_position({"x": 1.5, "y": -0.2}) == {"x": 1.0, "y": 0.0})
try:
    render.clean_position({"x": "not-a-number", "y": 0.5})
    valid_bad = False
except ValueError:
    valid_bad = True
check("invalid dragged coordinates are rejected", valid_bad)

db.init()
try:
    user = auth.local_user().id
    with ctx.as_user(user):
        job = jobs.create({"type": "file", "name": "Position test"}, {}, enqueue=False)
        clip = {"id": "clip-position", "start": 10.0, "end": 30.0, "status": "done",
                "hook": "BIG TEXT", "title": "Position test", "description": "", "hashtags": [],
                "style": "bounce", "layout": "blur", "captions": True, "score": 90}
        job["clips"].append(clip)
        with patch.object(jobs._q, "put") as queue:
            jobs.request_render(job["id"], clip["id"], {
                "hook_position": {"x": 0.32, "y": 0.24},
                "caption_position": {"x": 0.68, "y": 0.82},
            })
            check("clip re-make saves both dragged positions", clip["hook_position"] == {"x": 0.32, "y": 0.24}
                  and clip["caption_position"] == {"x": 0.68, "y": 0.82})
            check("position changes queue a fresh render", queue.called)
            saved = json.loads((__import__("pathlib").Path(job["dir"]) / "job.json").read_text(encoding="utf-8"))
            saved_clip = saved["clips"][0]
            check("dragged positions persist in job.json", saved_clip["hook_position"] == clip["hook_position"]
                  and saved_clip["caption_position"] == clip["caption_position"])

            jobs.request_render(job["id"], clip["id"], {"hook_position": "", "caption_position": ""})
            check("Reset positions restores the renderer's original layout defaults",
                  clip["hook_position"] is None and clip["caption_position"] is None)
finally:
    db.engine.dispose()

print("ALL PASSED" if not fails else f"{len(fails)} failed")
sys.exit(1 if fails else 0)
