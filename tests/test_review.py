"""Clip review defaults, validation and approval queue behaviour."""
import os
import sys
import tempfile

os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-review-")
os.environ["DATABASE_URL"] = ""
os.environ["PEAKCUT_ACCOUNTS"] = "0"
sys.path.insert(0, ".")

from studio import auth, ctx, db, jobs  # noqa: E402

db.init()
failures = []


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        failures.append(name)


user = auth.local_user().id
with ctx.as_user(user):
    check("review before rendering is enabled for new videos by default",
          jobs.DEFAULTS["review_before_render"] is True)
    check("the option can be disabled to keep automatic rendering",
          jobs.clean_options({"review_before_render": False}) == {"review_before_render": False})
    check("the option accepts explicit review mode",
          jobs.clean_options({"review_before_render": True}) == {"review_before_render": True})

    bad = False
    try:
        jobs.clean_options({"review_before_render": "yes"})
    except ValueError:
        bad = True
    check("the option rejects non-boolean values", bad)

    job = jobs.create({"type": "file", "path": "", "name": "review-test.mp4"},
                      {"max_clips": 1, "review_before_render": True}, enqueue=False)
    try:
        job["clips"] = [
            {"id": "clip01", "status": "review", "score": 90, "start": 10, "end": 25},
            {"id": "clip02", "status": "review", "score": 70, "start": 40, "end": 55},
        ]
        job["status"] = "review"
        jobs.save(job)

        empty = False
        try:
            jobs.render_selected(job["id"], [])
        except ValueError:
            empty = True
        check("approval requires at least one selected clip", empty)

        over_limit = False
        try:
            jobs.render_selected(job["id"], ["clip01", "clip02"])
        except ValueError:
            over_limit = True
        check("approval cannot exceed the requested clip limit", over_limit)

        unknown = False
        try:
            jobs.render_selected(job["id"], ["missing"])
        except ValueError:
            unknown = True
        check("approval rejects candidate ids that do not belong to the video", unknown)

        approved = jobs.render_selected(job["id"], ["clip02"])
        check("only the approved clip is queued for rendering",
              [x["id"] for x in approved["clips"]] == ["clip02"]
              and approved["clips"][0]["status"] == "queued")
        check("the approved job leaves review and enters the render queue",
              approved["status"] == "running" and approved["review_rendering"] is True)
        check("unselected candidates are counted and discarded",
              approved["review_skipped"] == 1)
    finally:
        jobs.delete(job["id"])

db.engine.dispose()
print("ALL PASSED" if not failures else f"{len(failures)} failed")
sys.exit(1 if failures else 0)
