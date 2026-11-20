"""Optional Advanced AI clipping method defaults and per-job overrides."""
import os
import sys
import tempfile

os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-method-")
os.environ["DATABASE_URL"] = ""
os.environ["PEAKCUT_ACCOUNTS"] = "0"
sys.path.insert(0, ".")
from studio import auth, creators, ctx, db, jobs  # noqa: E402

db.init()
failures = []

def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        failures.append(name)

user = auth.local_user().id
with ctx.as_user(user):
    default_creator = creators.create({"name": "Classic creator"})
    advanced_creator = creators.create({"name": "Advanced creator", "clip_method": "advanced"})
    inherited_classic = jobs.create({"type": "file", "name": "classic"}, {}, enqueue=False,
                                    creator=default_creator["id"])
    inherited_advanced = jobs.create({"type": "file", "name": "advanced"}, {}, enqueue=False,
                                     creator=advanced_creator["id"])
    overridden = jobs.create({"type": "file", "name": "override"}, {"clip_method": "peakcut"},
                             enqueue=False, creator=advanced_creator["id"])
    standalone = jobs.create({"type": "file", "name": "standalone"}, {}, enqueue=False)
    check("new creators default to PeakCut Automatic", default_creator["clip_method"] == "peakcut")
    check("creator can save Advanced AI as its preferred method", advanced_creator["clip_method"] == "advanced")
    check("creator method is inherited by new video jobs", inherited_advanced["options"]["clip_method"] == "advanced")
    check("PeakCut Automatic remains the default for existing behaviour", inherited_classic["options"]["clip_method"] == "peakcut"
          and standalone["options"]["clip_method"] == "peakcut")
    check("an individual video can override its creator's method", overridden["options"]["clip_method"] == "peakcut")
    check("unknown values safely fall back to PeakCut Automatic",
          jobs.clean_options({"clip_method": "not-a-method"})["clip_method"] == "peakcut")
    check("Advanced AI is accepted by the job option validator",
          jobs.clean_options({"clip_method": "advanced"})["clip_method"] == "advanced")

db.engine.dispose()
print("ALL PASSED" if not failures else f"{len(failures)} failed")
sys.exit(1 if failures else 0)
