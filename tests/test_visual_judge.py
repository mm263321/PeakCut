"""The visual judge uses sampled stills, parses scores, and degrades safely when vision is unavailable."""
import io
import json
import os
import sys
import tempfile
from unittest.mock import patch

os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-visual-")
os.environ["DATABASE_URL"] = ""
sys.path.insert(0, ".")
from PIL import Image  # noqa: E402
from studio import brain  # noqa: E402

fails = []
def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)

buf = io.BytesIO()
Image.new("RGB", (64, 36), (40, 100, 180)).save(buf, format="JPEG")
frame = buf.getvalue()
candidates = [{"id": "clip01"}, {"id": "clip02"}]
frames = {"clip01": [frame, frame, frame], "clip02": [frame, frame, frame]}
answer = json.dumps([
    {"id": "clip01", "score": 91, "reason": "A clear visible gameplay climax."},
    {"id": "clip02", "score": 22, "reason": "Mostly static menu imagery."},
])
with patch.object(brain.ai, "see", return_value=(answer, 120, 18)) as see, \
     patch.object(brain.usage, "record") as record:
    result = brain.judge_visual(candidates, frames, "Test stream", "Tester", game="gta 6")
    check("visual judge returns parsed candidate scores", result["available"] and result["scores"] == {"clip01": 91, "clip02": 22})
    check("visual judge accounts for image-model tokens", result["tokens"] == 138 and record.called)
    check("multiple candidates are sent in one contact sheet", see.call_count == 1 and "CANDIDATE" not in see.call_args.args[0])

with patch.object(brain.ai, "see", return_value=("", 0, 0)):
    result = brain.judge_visual(candidates, frames)
    check("text-only or unavailable vision model reports graceful fallback", not result["available"])

result = brain.judge_visual(candidates, {})
check("no available frames reports graceful fallback", not result["available"])
print("ALL PASSED" if not fails else f"{len(fails)} failed")
sys.exit(1 if fails else 0)
