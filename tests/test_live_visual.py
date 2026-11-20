"""Advanced live mode asks the visual judge; PeakCut Automatic keeps its two-judge path."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-live-visual-")
os.environ["DATABASE_URL"] = ""
sys.path.insert(0, ".")
import numpy as np  # noqa: E402
from studio import live  # noqa: E402

fails = []
def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)

def make_session(method):
    job = {"id": "live-test", "dir": os.path.join(os.environ["PEAKCUT_DATA"], "job"),
           "source": {"url": "https://example.test/live", "name": "Test stream"},
           "creator": "test", "title": "Test stream", "uploader": "Tester", "options": {"clip_method": method},
           "clips": [], "ai": {}}
    Path(job["dir"]).mkdir(parents=True, exist_ok=True)
    settings = {"clip_method": method, "ai_every_min": 3, "min_len": 15, "max_len": 60,
                "min_score": 50, "live_per_hour": 4, "must_clip_min": 0, "min_gap_min": 0,
                "decide_mode": "both", "game": ""}
    session = live.Session(job, settings)
    session.words = [{"w": f"word{i}", "s": float(i * 2), "e": float(i * 2 + 1)} for i in range(50)]
    session.t_done = 100.0
    session.db = [-20.0] * 120
    session._add_clip = lambda clip: job["clips"].append(dict(clip))
    session._visual_frames = lambda clip: [b"fake-jpeg-1", b"fake-jpeg-2", b"fake-jpeg-3"]
    return session

candidate = {"start": 20.0, "end": 40.0, "score": 90, "hook": "WOW", "title": "Big moment",
             "description": "A moment", "hashtags": [], "highlight_words": [], "reason": "An exciting moment."}
sig = [{"start": 20.0, "end": 40.0, "score": 85, "reason": "Strong reaction"}]
with patch.object(live.usage, "set_context"), \
     patch.object(live.brain, "judge_transcript", return_value=([dict(candidate)], 10)), \
     patch.object(live.brain, "judge_signals", return_value=(sig, 5)), \
     patch.object(live.brain, "judge_visual", return_value={"available": True, "scores": {"live01": 92},
                                                             "reasons": {"live01": "A clear visual event."}, "tokens": 7}) as visual:
    advanced = make_session("advanced")
    advanced._ai_check()
    check("Advanced AI calls the third visual judge", visual.called)
    check("Advanced AI saves all three judge scores", len(advanced.job["clips"]) == 1 and
          advanced.job["clips"][0]["judges"].get("visual") == 92 and
          advanced.job["clips"][0].get("visual_reason") == "A clear visual event.")

with patch.object(live.usage, "set_context"), \
     patch.object(live.brain, "judge_transcript", return_value=([dict(candidate)], 10)), \
     patch.object(live.brain, "judge_signals", return_value=(sig, 5)), \
     patch.object(live.brain, "judge_visual") as visual:
    classic = make_session("peakcut")
    classic._ai_check()
    check("PeakCut Automatic does not call the visual judge", not visual.called)
    check("PeakCut Automatic keeps its original two-judge result", len(classic.job["clips"]) == 1 and
          "visual" not in classic.job["clips"][0].get("judges", {}))

with patch.object(live.usage, "set_context"), \
     patch.object(live.brain, "judge_transcript", return_value=([dict(candidate)], 10)), \
     patch.object(live.brain, "judge_signals", return_value=(sig, 5)), \
     patch.object(live.brain, "judge_visual", return_value={"available": True, "scores": {},
                                                             "reasons": {}, "tokens": 1}):
    partial = make_session("advanced")
    partial._ai_check()
    check("Advanced AI preserves a candidate if its sampled frames are unavailable", len(partial.job["clips"]) == 1 and
          partial.job["clips"][0]["judges"].get("visual") is None)

print("ALL PASSED" if not fails else f"{len(fails)} failed")
sys.exit(1 if fails else 0)
