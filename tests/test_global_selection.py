"""Global Top N selects the highest-scoring non-overlapping moments across the full video."""
import os
import sys
import tempfile

os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-global-")
os.environ["DATABASE_URL"] = ""
sys.path.insert(0, ".")
from studio import brain, creators, jobs  # noqa: E402

fails = []


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)


candidates = [
    {"id": "late-best", "start": 300, "end": 330, "score": 99},
    {"id": "overlap", "start": 315, "end": 345, "score": 98},
    {"id": "middle", "start": 100, "end": 130, "score": 94},
    {"id": "early", "start": 20, "end": 50, "score": 91},
    {"id": "touching", "start": 50, "end": 75, "score": 88},
    {"id": "invalid", "start": -1, "end": 10, "score": 100},
]

picked = brain.select_global_top(candidates, 3)
check("selects the three highest-scoring non-overlapping clips",
      [c["id"] for c in picked] == ["late-best", "middle", "early"])
check("does not let an overlapping high-score moment take another slot",
      "overlap" not in [c["id"] for c in picked])
check("a clip touching the previous clip boundary is not treated as overlapping",
      "touching" in [c["id"] for c in brain.select_global_top(candidates, 4)])
check("does not exceed the requested clip count",
      len(brain.select_global_top(candidates, 2)) == 2)
check("returns no clips for an empty candidate pool",
      brain.select_global_top([], 3) == [])
check("job options accept Global Top N",
      jobs.clean_options({"clip_selection": "global"})["clip_selection"] == "global")
check("invalid job selection safely falls back to balanced",
      jobs.clean_options({"clip_selection": "unknown"})["clip_selection"] == "balanced")
check("creator preferences accept Global Top N",
      creators._clean({"clip_selection": "global"})["clip_selection"] == "global")

print("ALL PASSED" if not fails else f"{len(fails)} failed")
sys.exit(1 if fails else 0)
