"""Creator-specific export preferences flow into live clips and allow per-clip overrides."""
import os
import sys
import tempfile
import threading

os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-creator-live-export-")
os.environ["DATABASE_URL"] = ""
sys.path.insert(0, ".")

from studio import auth, creators, ctx, db, jobs, live  # noqa: E402

db.init()
fails = []


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)


user, _ = auth._create("creator-export@example.com", "Creator export", password_hash="x")
with ctx.as_user(user.id):
    streamer = creators.create({
        "name": "Streamer A",
        "channel": "https://www.twitch.tv/streamer_a",
        "description_text": "Test description",
        "export_resolution": "2k",
        "export_encoder": "hevc",
        "export_quality": "maximum",
    })
    other = creators.create({
        "name": "Streamer B",
        "channel": "https://www.twitch.tv/streamer_b",
    })

    check("creator stores its own 2K HEVC maximum preferences",
          (streamer["export_resolution"], streamer["export_encoder"], streamer["export_quality"])
          == ("2k", "hevc", "maximum"))
    check("another creator keeps independent default export preferences",
          (other["export_resolution"], other["export_encoder"], other["export_quality"])
          == ("1080p", "h264", "balanced"))

    # Live jobs retain a copy of the creator's preferences as job-level defaults.
    job = jobs.create(
        {"type": "live", "url": streamer["channel"], "name": "Streamer A live"},
        {}, enqueue=False, creator=streamer["id"], kind="live",
    )
    check("new live job inherits the creator export defaults",
          (job["options"]["export_resolution"], job["options"]["export_encoder"], job["options"]["export_quality"])
          == ("2k", "hevc", "maximum"))

    # Exercise the same _add_clip funnel used by AI highlights, 30/60 second manual clips,
    # and transcript trigger-word clips. No stream or FFmpeg process is started by this test.
    session = object.__new__(live.Session)
    session.n = 0
    session.settings = streamer
    session.job = job
    session.lock = threading.RLock()
    session.words = []
    real_submit_live = jobs.submit_live
    jobs.submit_live = lambda fn: None
    try:
        session._add_clip({"start": 10.0, "end": 40.0, "score": 90})
        first = job["clips"][-1]
        check("live clip inherits creator export preferences",
              (first["export_resolution"], first["export_encoder"], first["export_quality"])
              == ("2k", "hevc", "maximum"))

        # The API replaces Session.settings after a Creator Setup update. The next live clip
        # therefore sees the updated settings without changing clips already rendered.
        streamer = creators.update(streamer["id"], {
            "export_resolution": "4k",
            "export_encoder": "av1",
            "export_quality": "high",
        })
        session.settings = streamer
        session._add_clip({"start": 50.0, "end": 80.0, "score": 91})
        second = job["clips"][-1]
        check("next live clip uses updated settings during an active session",
              (second["export_resolution"], second["export_encoder"], second["export_quality"])
              == ("4k", "av1", "high"))
        check("already-created clip keeps its original export preference",
              (first["export_resolution"], first["export_encoder"], first["export_quality"])
              == ("2k", "hevc", "maximum"))
    finally:
        jobs.submit_live = real_submit_live

    inherited = jobs.clip_export_settings(job, {"id": "clip-default"})
    check("render selection falls back to live job creator preferences",
          (inherited["export_resolution"], inherited["export_encoder"], inherited["export_quality"])
          == ("2k", "hevc", "maximum"))

    overridden = jobs.clip_export_settings(job, {
        "id": "clip-override",
        "export_resolution": "1080p",
        "export_encoder": "h264",
        "export_quality": "balanced",
    })
    check("individual clip export override takes precedence on re-render",
          (overridden["export_resolution"], overridden["export_encoder"], overridden["export_quality"])
          == ("1080p", "h264", "balanced"))

    jobs.delete(job["id"])

if fails:
    print("FAILED: " + ", ".join(fails))
    sys.exit(1)
print("All creator live export checks passed.")
