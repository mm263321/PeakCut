"""Speech models for other spoken languages (Arabic first): downloading one only when asked, removing it, choosing
the language for a video or a creator, Arabic words, and the second machine never using the wrong language's model.
Runs against the code directly, with its own empty data folder; nothing is downloaded."""
import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-speech-")
os.environ.pop("PEAKCUT_MODELS", None)          # models are made and removed: only ever inside this test's folder
os.environ.update(DATABASE_URL="", PEAKCUT_ACCOUNTS="0", PEAKCUT_FETCH_MODEL="0", PEAKCUT_AI_KEY="", PEAKCUT_AI_KEY_FILE="",
                  PEAKCUT_PUBLIC_URL="http://127.0.0.1:8765")
sys.path.insert(0, ".")
from fastapi.testclient import TestClient  # noqa: E402

from studio import brain, config, creators, db, fetch_model, jobs, live, server, transcribe  # noqa: E402

db.init()
fails = []
BASE = "http://127.0.0.1:8765"
ORIGIN = {"Origin": BASE}
c = TestClient(server.app, base_url=BASE, follow_redirects=False)


def check(name, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"   got {ascii(got)}"))
    ok or fails.append(name)


assert str(config.MODELS_DIR).startswith(os.environ["PEAKCUT_DATA"]), "the test must only touch its own folder"
downloads = []


def archive(name):
    """A tiny stand-in for the real archive: the right folder name, the four files."""
    src = Path(tempfile.mkdtemp(prefix="pc-tar-")) / name
    src.mkdir()
    for n in ("tokens.txt", "encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx"):
        (src / n).write_bytes(b"model")
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:bz2") as t:
        t.add(src, arcname=name)
    return out.getvalue()


ARCHIVES = {k: archive(m[1]) for k, m in fetch_model.MODELS.items() if k not in fetch_model.DIRECT_FILES}
DIRECT_URLS = {fetch_model.file_url(lang, name): (lang, name)
               for lang, files in fetch_model.DIRECT_FILES.items() for name in files}
DIRECT_PAYLOADS = {(lang, name): ("test-model-" + lang + "-" + name).encode()
                   for lang, files in fetch_model.DIRECT_FILES.items() for name in files}
tampered = set()      # languages whose download is swapped for a different file


class Answer(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}


def fake_open(url, timeout=None):
    downloads.append(url)
    if url in DIRECT_URLS:
        lang, filename = DIRECT_URLS[url]
        data = DIRECT_PAYLOADS[(lang, filename)]
        return Answer(data + (b"changed" if lang in tampered else b""))
    lang = next(k for k, m in fetch_model.MODELS.items() if m[2] == url)
    return Answer(ARCHIVES[lang] + (b"changed" if lang in tampered else b""))


# ---- the list of models, and where Arabic comes from
check("English, Arabic and three Hinglish models are known (no Hindi option)",
      sorted(fetch_model.MODELS), ["ar", "en", "hinglish", "hinglish_apex", "hinglish_prime"])
for code, directory in (("hinglish", "hi-hinglish-swift"), ("hinglish_apex", "hi-hinglish-apex")):
    check(code + " uses its pinned Sherpa ONNX export",
          all(f"/resolve/9721eb71eea141fae0982cfcdb9dd2e3d4953c4a/{directory}/" in fetch_model.file_url(code, n)
              for n in fetch_model.DIRECT_FILES[code]), True)
check("Apex needs its two ONNX graphs and tokenizer",
      fetch_model.DIRECT_FILES["hinglish_apex"], ("encoder.int8.onnx", "decoder.int8.onnx", "tokens.txt"))
prime_file = fetch_model.DIRECT_FILES["hinglish_prime"][0]
check("Prime uses its pinned GGML Q8 export and known SHA-256",
      ("/resolve/a0c23ffdae030007639da02059256ce4eb1669e8/" in fetch_model.file_url("hinglish_prime", prime_file),
       fetch_model.DIRECT_HASHES["hinglish_prime"][prime_file]),
      (True, "e42f78e509920efc64d99f4ae2b0b39fe59b8f8f37c8bfe41fa6e8607525a2a7"))
check("Arabic is downloaded from its own address, not English's", fetch_model.MODELS["ar"][2] != fetch_model.MODELS["en"][2], True)
check("Arabic's address names one fixed version of the file, not the latest",
      fetch_model.MODELS["ar"][2], lambda u: "/resolve/main/" not in u and re.search(r"/resolve/[0-9a-f]{40}/", u))
check("Arabic's fingerprint is known, so the download is checked", fetch_model.MODELS["ar"][5], lambda h: re.fullmatch(r"[0-9a-f]{64}", h))
mirror = subprocess.run([sys.executable, "-c", "from studio import fetch_model as f; print(f.MODELS['ar'][2]); print(f.MODELS['ar'][5])"],
                        env={**os.environ, "PEAKCUT_ASR_MODEL_AR_URL": "https://mirror.example/ar.tar.bz2"},
                        capture_output=True, text=True).stdout.split()
check("a mirror set with PEAKCUT_ASR_MODEL_AR_URL is used, and still checked against the same fingerprint",
      mirror, ["https://mirror.example/ar.tar.bz2", fetch_model.MODELS["ar"][5]])
real_ar = fetch_model.MODELS["ar"]
# From here on the stand-in archive is "the real file": its fingerprint is the one expected.
fetch_model.MODELS["ar"] = real_ar[:5] + (hashlib.sha256(ARCHIVES["ar"]).hexdigest(),)
fetch_model.urllib.request.urlopen = fake_open
check("each language has its own folder", fetch_model.folder("ar") != fetch_model.folder("en"), True)
check("nothing is here to begin with",
      tuple(fetch_model.status(k) for k in ("en", "ar", "hinglish", "hinglish_apex", "hinglish_prime")),
      ("missing", "missing", "missing", "missing", "missing"))

# ---- Arabic is never downloaded unless someone asks
try:
    fetch_model.ensure("ar", start=False)
    said = ""
except RuntimeError as e:
    said = str(e)
check("a video needing Arabic says what to do instead of downloading", ("Speech models" in said, downloads), (True, []))
try:
    transcribe._new("ar")
    said = ""
except RuntimeError as e:
    said = str(e)
check("...and so does loading the model for transcribing", ("Speech models" in said, downloads), (True, []))

# ---- the routes: list, download, remove
r = c.get("/api/speech").json()["models"]
check("the page lists English, Arabic and all three Hinglish variants",
      [(m["lang"], m["state"], m["size_mb"] > 0) for m in r],
      [("en", "missing", True), ("ar", "missing", True), ("hinglish", "missing", True),
       ("hinglish_apex", "missing", True), ("hinglish_prime", "missing", True)])
check("an unknown language is refused", c.post("/api/speech/xx", headers=ORIGIN).status_code, 400)
check("another website cannot start a download", c.post("/api/speech/ar", headers={"Origin": "https://evil.example"}).status_code, 403)
check("...and nothing was downloaded", downloads, [])
tampered.add("ar")         # the file at the address was changed: it must not be unpacked
try:
    fetch_model.ensure("ar")
    said = ""
except RuntimeError as e:
    said = str(e)
check("a downloaded file with the wrong fingerprint is refused, in plain words",
      ("not the one it expects" in said and "Nothing was unpacked" in said, fetch_model.ready("ar")), (True, False))
check("...it says which fingerprint it got and which it expected", fetch_model.MODELS["ar"][5] in said and "SHA-256" in said, True)
check("...the reason is shown on the Speech models page", "not the expected one" in fetch_model.state["ar"]["error"], True)
check("...and nothing is left behind", sorted(p.name for p in config.MODELS_DIR.iterdir()) if config.MODELS_DIR.exists() else [], [])
tampered.clear()
downloads.clear()
check("the owner can start the Arabic download", c.post("/api/speech/ar", headers=ORIGIN).status_code, 200)
for _ in range(100):
    if fetch_model.status("ar") == "ready":
        break
    time.sleep(0.05)
check("Arabic arrives whole, in its own folder", (fetch_model.ready("ar"), sorted(p.name for p in fetch_model.folder("ar").iterdir())),
      (True, ["decoder.int8.onnx", "encoder.int8.onnx", "joiner.int8.onnx", "tokens.txt"]))
check("English was not touched", fetch_model.ready("en"), False)
check("nothing is left over from the download", sorted(p.name for p in config.MODELS_DIR.iterdir()), [fetch_model.MODELS["ar"][1]])
check("the status tells every page Arabic is ready", c.get("/api/status").json()["speech"]["ar"]["state"], "ready")
check("asking again downloads nothing more", (c.post("/api/speech/ar", headers=ORIGIN).status_code, len(downloads)), (200, 1))
check("English can't be removed", c.delete("/api/speech/en", headers=ORIGIN).status_code, 400)

transcribe._pool("ar").made += 1                  # pretend a video is transcribing in Arabic right now
check("a model in use is not removed", (c.delete("/api/speech/ar", headers=ORIGIN).status_code, fetch_model.ready("ar")), (409, True))
transcribe._pool("ar").made -= 1
check("Arabic can be removed when nothing uses it", (c.delete("/api/speech/ar", headers=ORIGIN).status_code, fetch_model.folder("ar").exists()), (200, False))

# ---- Hinglish Swift download, use, timestamps, and removal
downloads.clear()
check("the owner can start the Hinglish download", c.post("/api/speech/hinglish", headers=ORIGIN).status_code, 200)
for _ in range(100):
    if fetch_model.status("hinglish") == "ready":
        break
    time.sleep(0.05)
check("Hinglish arrives with all three Whisper files",
      (fetch_model.ready("hinglish"), sorted(p.name for p in fetch_model.folder("hinglish").iterdir())),
      (True, sorted(fetch_model.DIRECT_FILES["hinglish"])))
check("the Hinglish download fetches exactly the three pinned files",
      sorted(url.rsplit("/", 1)[-1] for url in downloads),
      sorted(fetch_model.DIRECT_FILES["hinglish"]))
check("the installed model is visible in API status", c.get("/api/status").json()["speech"]["hinglish"]["state"], "ready")

# Exercise the actual Whisper loader configuration without downloading or loading 160 MB during the test.
hd = fetch_model.folder("hinglish")
class FakeWhisperRecognizer:
    @staticmethod
    def from_whisper(**kwargs):
        return kwargs
class FakeSherpa:
    OfflineRecognizer = FakeWhisperRecognizer
for filename in fetch_model.DIRECT_FILES["hinglish"]:
    (hd / filename).write_bytes(b"test-model")
old_sherpa = transcribe._sherpa
transcribe._sherpa = lambda: FakeSherpa
try:
    whisper_config = transcribe._new("hinglish")
finally:
    transcribe._sherpa = old_sherpa
check("Hinglish Swift uses the Hindi Whisper token and word timestamps",
      (whisper_config["language"], whisper_config["task"], whisper_config["enable_token_timestamps"]),
      ("hi", "transcribe", True))
whisper_words = transcribe._words(["Hello", " there", "!", " how", " are", " you"],
                                  [0.0, 0.2, 0.4, 0.6, 0.8, 1.0], 0, 32000)
check("Whisper's space-prefixed pieces become correctly separated words",
      [w["w"] for w in whisper_words], ["Hello", "there!", "how", "are", "you"])

transcribe._pool("hinglish").made += 1
check("a Hinglish model in use is not removed",
      (c.delete("/api/speech/hinglish", headers=ORIGIN).status_code, fetch_model.ready("hinglish")),
      (409, True))
transcribe._pool("hinglish").made -= 1
check("Hinglish can be removed and its files are deleted",
      (c.delete("/api/speech/hinglish", headers=ORIGIN).status_code, fetch_model.folder("hinglish").exists()),
      (200, False))

# ---- Hinglish Apex download, Sherpa loader and removal
downloads.clear()
check("the owner can start the Hinglish Apex download",
      c.post("/api/speech/hinglish_apex", headers=ORIGIN).status_code, 200)
for _ in range(100):
    if fetch_model.status("hinglish_apex") == "ready":
        break
    time.sleep(0.05)
check("Hinglish Apex arrives with all required files",
      (fetch_model.ready("hinglish_apex"), sorted(p.name for p in fetch_model.folder("hinglish_apex").iterdir())),
      (True, sorted(fetch_model.DIRECT_FILES["hinglish_apex"])))
apex_folder = fetch_model.folder("hinglish_apex")
for filename in fetch_model.DIRECT_FILES["hinglish_apex"]:
    (apex_folder / filename).write_bytes(b"test-model")
old_sherpa = transcribe._sherpa
transcribe._sherpa = lambda: FakeSherpa
try:
    apex_config = transcribe._new("hinglish_apex")
finally:
    transcribe._sherpa = old_sherpa
check("Apex uses the Hindi Whisper token and word timestamp support",
      (apex_config["language"], apex_config["task"], apex_config["enable_token_timestamps"]),
      ("hi", "transcribe", True))
transcribe._pool("hinglish_apex").made += 1
check("Apex cannot be removed while it is in use",
      (c.delete("/api/speech/hinglish_apex", headers=ORIGIN).status_code,
       fetch_model.ready("hinglish_apex")), (409, True))
transcribe._pool("hinglish_apex").made -= 1
check("Apex can be removed when idle",
      (c.delete("/api/speech/hinglish_apex", headers=ORIGIN).status_code,
       fetch_model.folder("hinglish_apex").exists()), (200, False))

# ---- Hinglish Prime download, SHA-256, whisper.cpp backend and removal
prime_file = fetch_model.DIRECT_FILES["hinglish_prime"][0]
fake_prime_data = DIRECT_PAYLOADS[("hinglish_prime", prime_file)]
old_prime_hash = fetch_model.DIRECT_HASHES["hinglish_prime"][prime_file]
fetch_model.DIRECT_HASHES["hinglish_prime"][prime_file] = hashlib.sha256(fake_prime_data).hexdigest()
downloads.clear()
check("the owner can start the Hinglish Prime download",
      c.post("/api/speech/hinglish_prime", headers=ORIGIN).status_code, 200)
for _ in range(100):
    if fetch_model.status("hinglish_prime") == "ready":
        break
    time.sleep(0.05)
check("Prime arrives with its GGML Q8 file",
      (fetch_model.ready("hinglish_prime"),
       (fetch_model.folder("hinglish_prime") / prime_file).read_bytes()),
      (True, fake_prime_data))

class FakePrimeModel:
    def __init__(self, model, **kwargs):
        self.model = model
        self.options = kwargs
    def transcribe(self, audio, **kwargs):
        return [type("Segment", (), {"t0": 0, "t1": 50, "text": "Bhai"})(),
                type("Segment", (), {"t0": 50, "t1": 100, "text": "what are you doing?"})()]

fake_pkg = type(sys)("pywhispercpp")
fake_pkg.__path__ = []
fake_model_module = type(sys)("pywhispercpp.model")
fake_model_module.Model = FakePrimeModel
old_pkg = sys.modules.get("pywhispercpp")
old_model_module = sys.modules.get("pywhispercpp.model")
sys.modules["pywhispercpp"] = fake_pkg
sys.modules["pywhispercpp.model"] = fake_model_module
try:
    prime_model = transcribe._new("hinglish_prime")
finally:
    if old_pkg is None:
        sys.modules.pop("pywhispercpp", None)
    else:
        sys.modules["pywhispercpp"] = old_pkg
    if old_model_module is None:
        sys.modules.pop("pywhispercpp.model", None)
    else:
        sys.modules["pywhispercpp.model"] = old_model_module
check("Prime selects Hindi with word split and timestamp settings",
      (prime_model.model.endswith(prime_file), prime_model.options["language"],
       prime_model.options["max_len"], prime_model.options["split_on_word"],
       prime_model.options["token_timestamps"]),
      (True, "hi", 1, True, True))
prime_result = transcribe.decode_pieces(
    [transcribe.np.zeros(16000, dtype="float32")], rec=prime_model, lang="hinglish_prime")
prime_words = transcribe._words(prime_result[0][0], prime_result[0][1], 0, 16000)
check("Prime converts word-split Whisper segments into caption words",
      [w["w"] for w in prime_words], ["Bhai", "what", "are", "you", "doing?"])
transcribe.unload("hinglish_prime")
transcribe._pool("hinglish_prime").made += 1
check("Prime cannot be removed while it is in use",
      (c.delete("/api/speech/hinglish_prime", headers=ORIGIN).status_code,
       fetch_model.ready("hinglish_prime")), (409, True))
transcribe._pool("hinglish_prime").made -= 1
check("Prime can be removed when idle",
      (c.delete("/api/speech/hinglish_prime", headers=ORIGIN).status_code,
       fetch_model.folder("hinglish_prime").exists()), (200, False))
tampered.add("hinglish_prime")
try:
    fetch_model.ensure("hinglish_prime")
    checksum_error = ""
except RuntimeError as e:
    checksum_error = str(e)
check("a changed Prime GGML file fails SHA-256 and is not installed",
      ("checksum did not match" in checksum_error, fetch_model.ready("hinglish_prime")),
      (True, False))
fetch_model.DIRECT_HASHES["hinglish_prime"][prime_file] = old_prime_hash
tampered.clear()

# ---- choosing the language
check("a video can be marked as Arabic", jobs.clean_options({"lang": "ar"}), {"lang": "ar"})
check("a video can be marked as Hinglish Swift", jobs.clean_options({"lang": "hinglish"}), {"lang": "hinglish"})
check("a video can be marked as Hinglish Apex",
      jobs.clean_options({"lang": "hinglish_apex"}), {"lang": "hinglish_apex"})
check("a video can be marked as Hinglish Prime",
      jobs.clean_options({"lang": "hinglish_prime"}), {"lang": "hinglish_prime"})
check("an unknown language becomes English", jobs.clean_options({"lang": "xx"}), {"lang": "en"})
check("videos are English unless chosen", jobs.DEFAULTS["lang"], "en")
check("a creator can speak Arabic", creators._clean({"lang": "ar"}), {"lang": "ar"})
check("a creator can speak Hinglish Swift", creators._clean({"lang": "hinglish"}), {"lang": "hinglish"})
check("a creator can speak Hinglish Apex",
      creators._clean({"lang": "hinglish_apex"}), {"lang": "hinglish_apex"})
check("a creator can speak Hinglish Prime",
      creators._clean({"lang": "hinglish_prime"}), {"lang": "hinglish_prime"})
check("...but not a made-up language", creators._clean({"lang": "<b>"}), {"lang": "en"})
r = c.post("/api/creators", json={"name": "Arabic speaker"}, headers=ORIGIN)
cid = r.json()["id"]
c.put(f"/api/creators/{cid}", json={"lang": "ar"}, headers=ORIGIN)
from studio import auth, ctx  # noqa: E402
with ctx.as_user(auth.local_user().id):
    cr = creators.get(cid)
    check("the creator's language is kept", cr.get("lang"), "ar")
    try:
        live.start_session(cr, "https://www.twitch.tv/someone")
        said = ""
    except ValueError as e:
        said = str(e)
    check("recording an Arabic creator without the model says what to do", "Speech models" in said, True)

# ---- Arabic words
tokens = ["▁ال", "ك", "ت", "ا", "بُ", "▁جـ", "ميل", "،", "▁ok"]
words = transcribe._words(tokens, [0.0, 0.1, 0.2, 0.3, 0.4, 0.6, 0.7, 0.8, 1.0], 0, 32000)
check("Arabic pieces join into words, vowel marks and the stretching line removed, punctuation kept",
      [w["w"] for w in words], ["الكتاب", "جميل،", "ok"])
check("live word matching works in Arabic letters", (live._plain("الكتابُ"), live._plain("Clip-That!")), ("الكتاب", "clipthat"))

from studio import roman  # noqa: E402
check("Arabic without the AI is spelled in Roman letters the caption font can draw, hamza and commas too",
      roman.to_roman("قابلت نوران أنا، إن شاء الله؟"), lambda t: not roman.OTHER_SCRIPT.search(t) and "," in t and "?" in t)

# ---- the AI is told about English words in Arabic letters, only when the transcript is in Arabic letters
arabic = "[1] " + "مرحبا بكم في الحلقة الجديدة سبسكرايب " * 3
check("an Arabic transcript gets the note", brain.ARABIC_NOTE in brain._rules(15, 60, arabic), True)
check("an English one does not", brain.ARABIC_NOTE in brain._rules(15, 60, "[1] hello and welcome back " * 5), False)

# ---- the second machine: never the wrong language's model
class Reply:
    def __init__(self, code, body):
        self.status_code, self.body = code, body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        return self.body


import httpx  # noqa: E402
real_post = httpx.post
piece = [transcribe.np.zeros(16000, dtype="float32")]
old = {"pieces": [{"tokens": ["▁hi"], "timestamps": [0.0]}]}
httpx.post = lambda *a, **k: Reply(200, old)               # an older machine: answers in English, says no language
try:
    transcribe._decode_remote(piece, "ar")
    got = "used"
except transcribe.RemoteLacks:
    got = "refused"
check("an older machine's English answer is not used for Arabic", got, "refused")
check("...but still used for English", transcribe._decode_remote(piece, "en"), [(["▁hi"], [0.0])])
httpx.post = lambda *a, **k: Reply(409, {})
try:
    transcribe._decode_remote(piece, "ar")
    got = "used"
except transcribe.RemoteLacks:
    got = "refused"
check("a machine without the Arabic model says so", got, "refused")
httpx.post = lambda *a, **k: Reply(200, dict(old, lang="ar"))
check("a machine with the Arabic model is used", transcribe._decode_remote(piece, "ar"), [(["▁hi"], [0.0])])
httpx.post = real_post

print("ALL PASSED" if not fails else f"{len(fails)} failed")
shutil.rmtree(os.environ["PEAKCUT_DATA"], ignore_errors=True)
sys.exit(1 if fails else 0)
