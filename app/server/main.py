"""VU3INI Transcribe Studio — local web server (FastAPI)."""
import json
import logging
import os
import shutil
import threading
import time
from pathlib import Path

from . import netguard

netguard.install()  # before anything else can open a socket

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket  # noqa: E402
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from . import audio, components, config, diarize, engines, exporters, live, packs, store, translate  # noqa: E402
from .jobs import QUEUE, Job  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s",
                    handlers=[logging.FileHandler(config.LOG_DIR / "server.log", encoding="utf-8"), logging.StreamHandler()])
log = logging.getLogger("vts")
for _n in ("fontTools", "httpx", "httpx2", "faster_whisper"):
    logging.getLogger(_n).setLevel(logging.WARNING)

app = FastAPI(title=config.APP_NAME, docs_url=None, redoc_url=None, openapi_url=None)
SERVER = {"uvicorn": None}
MEDIA_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".webm", ".mp4", ".mkv", ".mov",
             ".avi", ".wmv", ".3gp", ".amr", ".mpeg", ".mpg", ".m4v", ".ts"}

packs.register_gpu_runtime()


# ---------------------------------------------------------------- static UI
@app.get("/", response_class=HTMLResponse)
def index():
    html = (config.WEB_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html.replace("{{VERSION}}", config.VERSION), headers={"Cache-Control": "no-store"})


app.mount("/assets", StaticFiles(directory=str(config.WEB_DIR / "assets")), name="assets")


@app.get("/app.js")
def appjs():
    return FileResponse(config.WEB_DIR / "app.js", media_type="text/javascript", headers={"Cache-Control": "no-store"})


@app.get("/style.css")
def css():
    return FileResponse(config.WEB_DIR / "style.css", media_type="text/css", headers={"Cache-Control": "no-store"})


@app.get("/help.json")
def help_json():
    return FileResponse(config.WEB_DIR / "help.json", media_type="application/json")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    # The page may only load from this local server.
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self' ws://127.0.0.1:* ws://localhost:*; font-src 'self'")
    return resp


# ---------------------------------------------------------------- info & settings
@app.get("/api/ping")
def ping():
    return {"ok": True, "app": config.APP_NAME, "version": config.VERSION, "pid": os.getpid()}


@app.get("/api/info")
def info():
    dev, ct = engines.resolve_device(config.load_settings())
    return {"name": config.APP_NAME, "version": config.VERSION, "author": config.AUTHOR, "email": config.EMAIL,
            "sources": components.SOURCES, "components": [{"name": n, "licence": l} for n, l in components.COMPONENTS],
            "device": dev, "compute_type": ct, "cuda": engines.cuda_available(), "data_dir": str(config.DATA_DIR),
            "packs_dir": str(config.PACKS_DIR), "diarization": bool(diarize.available()),
            "translation": translate.available_directions(),
            "asr_packs": [{"id": p["id"], "name": p["name"], "languages": p.get("languages")} for p in engines.asr_packs()]}


@app.get("/api/settings")
def get_settings():
    return config.load_settings()


@app.post("/api/settings")
def set_settings(data: dict = Body(...)):
    s = config.save_settings(data)
    engines.unload_all()
    return s


@app.get("/api/netlog")
def netlog():
    return {"blocked": netguard.attempts()}


# ---------------------------------------------------------------- packs
@app.get("/api/packs")
def list_packs():
    return packs.list_packs()


def _install_job(src: Path, cleanup: bool):
    def run(job: Job):
        job.set("Installing pack", 0)
        try:
            m = packs.install_from_file(src, progress=lambda f: job.set(progress=f))
            job.notes.append(f"Installed {m['name']}.")
            engines.unload_all()
        finally:
            if cleanup:
                src.unlink(missing_ok=True)
    return QUEUE.submit(Job("pack", f"Install pack {src.name}", run))


@app.post("/api/packs/install")
async def install_pack_upload(file: UploadFile = File(...)):
    dst = config.TMP_DIR / f"upload-{int(time.time() * 1000)}-{Path(file.filename or 'pack').name}"
    with open(dst, "wb") as f:
        while chunk := await file.read(8 * 1024 * 1024):
            f.write(chunk)
    return _install_job(dst, True).to_dict()


@app.post("/api/packs/install-path")
def install_pack_path(data: dict = Body(...)):
    src = Path(str(data.get("path") or "").strip().strip('"'))
    if not src.is_file():
        raise HTTPException(400, f"File not found: {src}")
    return _install_job(src, False).to_dict()


# ---------------------------------------------------------------- making packs inside the app (online step)
TOOLS = config.APP_DIR / "tools" / "make_packs.py"
PACKS_OUT = config.DATA_DIR / "packs-out"


def _catalog():
    import importlib.util
    spec = importlib.util.spec_from_file_location("vts_make_packs", TOOLS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.CATALOG


@app.get("/api/packs/catalog")
def packs_catalog():
    installed = {p["id"] for p in packs.list_packs()}
    out = []
    for i, c in enumerate(_catalog(), 1):
        out.append({"id": c["id"], "name": c["name"], "size": c["size"], "languages": c.get("languages", []),
                    "kind": c["kind"], "gated": c["kind"] == "hf-raw", "installed": c["id"] in installed})
    return {"catalog": out, "keep_dir": str(PACKS_OUT)}


@app.post("/api/packs/download")
def packs_download(data: dict = Body(...)):
    import subprocess
    import sys as _sys
    ids = [str(x) for x in data.get("ids") or []]
    custom = data.get("custom") or {}
    repo = (custom.get("repo") or "").strip()
    if repo and ("/" not in repo or " " in repo):
        raise HTTPException(400, "A Hugging Face model id looks like owner/model-name, e.g. anuragshas/whisper-large-v2-as")
    valid = {c["id"] for c in _catalog()}
    bad = [i for i in ids if i not in valid]
    if bad:
        raise HTTPException(400, f"Unknown pack: {', '.join(bad)}")
    if not ids and not repo:
        raise HTTPException(400, "Choose at least one pack, or enter a custom model id.")
    token = (data.get("token") or "").strip()
    keep = bool(data.get("keep"))
    work = PACKS_OUT if keep else config.TMP_DIR / f"packs-{int(time.time())}"
    work.mkdir(parents=True, exist_ok=True)
    args = [_sys.executable, str(TOOLS), *ids, "--out", str(work), "--json-progress"]
    if repo:
        args += ["--custom-repo", repo, "--custom-engine", custom.get("engine") or "ct2",
                 "--custom-langs", custom.get("languages") or "*"]
    total = len(ids) + (1 if repo else 0)

    def run(job: Job):
        env = {k: v for k, v in os.environ.items() if k not in netguard.OFFLINE_ENV or k == "TOKENIZERS_PARALLELISM"}
        env["PYTHONIOENCODING"] = "utf-8"
        if token:
            env["HF_TOKEN"] = token  # used for this download only, never saved
        log.info("Pack download started: %s", ", ".join(ids + ([repo] if repo else [])))
        job.set("Connecting to the internet", 0.01)
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, text=True,
                                encoding="utf-8", errors="replace", creationflags=0x08000000 if os.name == "nt" else 0)
        idx, name, installed, failed, last = 0, "", [], [], ""
        try:
            for line in proc.stdout:
                if job.cancel.is_set():
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    m = json.loads(line)
                except ValueError:
                    last = line[-200:]
                    continue
                if "pack" in m:
                    idx, name = m["index"], m["name"]
                    job.set(f"{name}: starting", idx / total)
                elif "dl_mb" in m:
                    frac = m.get("dl_frac")
                    job.set(f"{name}: downloading {m['dl_mb']:,.0f} MB" + (f" ({frac:.0%})" if frac else ""),
                            (idx + 0.7 * (frac or 0.3)) / total)
                elif "msg" in m and m["msg"]:
                    last = m["msg"]
                    if any(w in last for w in ("converting", "unpacking", "writing")):
                        job.set(f"{name}: {last.strip(' .…')}", (idx + 0.8) / total)
                elif "done" in m:
                    job.set(f"{name}: installing", (idx + 0.9) / total)
                    f = Path(m["file"])
                    meta = packs.install_from_file(f)
                    installed.append(meta["name"])
                    if not keep:
                        f.unlink(missing_ok=True)
                elif "failed" in m:
                    failed.append(f"{m['failed']}: {m['error']}")
        finally:
            if proc.poll() is None:
                try:
                    import psutil
                    for c in psutil.Process(proc.pid).children(recursive=True):
                        c.kill()
                except Exception:
                    pass
                proc.kill()
            proc.wait()
            if not keep:
                shutil.rmtree(work, ignore_errors=True)
            engines.unload_all()
        if job.cancel.is_set():
            return
        if installed:
            job.notes.append("Installed: " + ", ".join(installed))
        if keep and installed:
            job.notes.append(f"Pack files kept in {work}")
        job.notes += [f"Failed — {x}" for x in failed]
        if not installed:
            msg = "; ".join(failed) or last or "nothing was created"
            if "getaddrinfo" in msg or "urlopen error" in msg or "ConnectError" in msg or "Network" in msg or "resolve" in msg.lower():
                msg = "No internet connection: " + msg
            raise RuntimeError(msg)

    label = ", ".join(ids + ([repo] if repo else []))
    return QUEUE.submit(Job("pack", f"Get model packs: {label}", run)).to_dict()


@app.delete("/api/packs/{pack_id}")
def delete_pack(pack_id: str):
    engines.unload_all()
    try:
        packs.remove(pack_id)
    except packs.PackError as e:
        raise HTTPException(404, str(e))
    return {"ok": True}


# ---------------------------------------------------------------- projects
def _transcribe_job(pid: str, opts: dict) -> Job:
    def run(job: Job):
        settings = config.load_settings()
        settings.update({k: v for k, v in opts.items() if k in config.DEFAULT_SETTINGS})
        p = store.get(pid)
        store.update(pid, status="processing")
        src = store.path(pid, p["media"])
        job.set("Decoding audio", 0.02)
        samples = audio.decode(src, settings.get("denoise"), settings.get("normalize", True), settings.get("trim_silence"))
        duration = round(len(samples) / audio.SR, 2)
        try:
            store.path(pid, "peaks.json").write_text(json.dumps(audio.peaks(samples)))
            if not store.path(pid, "playback.m4a").exists():
                audio.make_playback(src, store.path(pid, "playback.m4a"))
        except Exception as e:  # noqa: BLE001
            job.notes.append(f"Waveform/player copy failed: {e}")
        info = audio.probe(src)
        do_diar = bool(opts.get("diarize"))
        span = 0.75 if do_diar else 0.95
        job.set("Transcribing", 0.05)
        segs, lang, eng, dev, notes = engines.transcribe(
            samples, settings, language=opts.get("language") or "auto", engine=opts.get("engine") or "auto",
            progress=lambda f: job.set(progress=0.05 + f * span), cancel=job.cancel)
        job.notes += notes
        speakers = {}
        if do_diar and not job.cancel.is_set():
            job.set("Finding speakers", 0.8)
            try:
                turns = diarize.diarize(samples, int(opts.get("max_speakers") or settings.get("max_speakers") or 0),
                                        progress=lambda f: job.set(progress=0.8 + f * 0.18), cancel=job.cancel)
                segs, speakers = diarize.assign(segs, turns)
            except Exception as e:  # noqa: BLE001
                job.notes.append(f"Speaker diarization skipped: {e}")
        if job.cancel.is_set():
            store.update(pid, status="cancelled")
            return
        store.update(pid, snapshot=True, status="done", segments=segs, speakers=speakers, language=lang,
                     engine=eng, device=dev, duration=duration, has_video=info["has_video"], notes=job.notes)
    def safe_run(job: Job):
        try:
            run(job)
        except Exception:
            try:
                store.update(pid, status="cancelled" if job.cancel.is_set() else "failed")
            except Exception:
                pass
            raise
    return QUEUE.submit(Job("transcribe", f"Transcribe {store.get(pid)['name']}", safe_run, pid))


def _opts_from_form(language, engine, diarize_, max_speakers, denoise, normalize, trim_silence):
    o = {"language": language, "engine": engine, "diarize": diarize_ in ("1", "true", "on", True),
         "max_speakers": int(max_speakers or 0)}
    for k, v in (("denoise", denoise), ("normalize", normalize), ("trim_silence", trim_silence)):
        if v is not None:
            o[k] = v in ("1", "true", "on", True)
    return o


@app.post("/api/projects")
async def create_project(file: UploadFile = File(...), language: str = Form("auto"), engine: str = Form("auto"),
                         diarize: str = Form("0"), max_speakers: str = Form("0"), denoise: str | None = Form(None),
                         normalize: str | None = Form(None), trim_silence: str | None = Form(None)):
    name = Path(file.filename or "recording").name
    if Path(name).suffix.lower() not in MEDIA_EXT:
        raise HTTPException(400, f"Unsupported file type: {Path(name).suffix}")
    tmp = config.TMP_DIR / f"in-{int(time.time() * 1000)}{Path(name).suffix.lower()}"
    with open(tmp, "wb") as f:
        while chunk := await file.read(8 * 1024 * 1024):
            f.write(chunk)
    p = store.create(Path(name).stem, tmp, status="queued")
    job = _transcribe_job(p["id"], _opts_from_form(language, engine, diarize, max_speakers, denoise, normalize, trim_silence))
    return {"project": p, "job": job.to_dict()}


@app.post("/api/batch")
def batch_folder(data: dict = Body(...)):
    folder = Path(str(data.get("folder") or "").strip().strip('"'))
    if not folder.is_dir():
        raise HTTPException(400, f"Folder not found: {folder}")
    files = sorted(f for f in (folder.rglob("*") if data.get("recursive") else folder.iterdir())
                   if f.is_file() and f.suffix.lower() in MEDIA_EXT)
    if not files:
        raise HTTPException(400, "No audio or video files found in that folder.")
    opts = {k: data.get(k) for k in ("language", "engine", "diarize", "max_speakers", "denoise", "normalize", "trim_silence")
            if data.get(k) is not None}
    out = []
    for f in files:
        tmp = config.TMP_DIR / f"in-{int(time.time() * 1000)}-{len(out)}{f.suffix.lower()}"
        shutil.copy2(f, tmp)
        p = store.create(f.stem, tmp, status="queued", tags=["batch"])
        out.append(_transcribe_job(p["id"], opts).to_dict())
    return {"jobs": out}


@app.get("/api/projects")
def projects():
    return store.list_all()


def _get(pid):
    try:
        return store.get(pid)
    except (KeyError, FileNotFoundError):
        raise HTTPException(404, "Project not found")


@app.get("/api/projects/{pid}")
def project(pid: str):
    return _get(pid)


@app.put("/api/projects/{pid}")
def save_project(pid: str, data: dict = Body(...)):
    _get(pid)
    allowed = {k: v for k, v in data.items() if k in ("name", "segments", "speakers", "tags", "translation")}
    return store.update(pid, snapshot="segments" in allowed, **allowed)


@app.delete("/api/projects/{pid}")
def delete_project(pid: str):
    store.delete(pid)
    return {"ok": True}


@app.get("/api/projects/{pid}/media")
def media(pid: str):
    _get(pid)
    f = store.path(pid, "playback.m4a")
    if not f.exists():
        raise HTTPException(404, "No playback copy")
    return FileResponse(f, media_type="audio/mp4")


@app.get("/api/projects/{pid}/peaks")
def get_peaks(pid: str):
    f = store.path(pid, "peaks.json")
    return Response(f.read_text() if f.exists() else "[]", media_type="application/json")


@app.get("/api/projects/{pid}/versions")
def get_versions(pid: str):
    return store.versions(pid)


@app.post("/api/projects/{pid}/restore")
def restore(pid: str, data: dict = Body(...)):
    return store.restore(pid, data["version"])


@app.post("/api/projects/{pid}/transcribe")
def retranscribe(pid: str, data: dict = Body(default={})):
    _get(pid)
    return _transcribe_job(pid, data).to_dict()


@app.post("/api/projects/{pid}/diarize")
def rediarize(pid: str, data: dict = Body(default={})):
    p = _get(pid)

    def run(job: Job):
        job.set("Decoding audio", 0.05)
        samples = audio.decode(store.path(pid, p["media"]))
        job.set("Finding speakers", 0.1)
        turns = diarize.diarize(samples, int(data.get("max_speakers") or 0),
                                progress=lambda f: job.set(progress=0.1 + f * 0.85), cancel=job.cancel)
        segs, speakers = diarize.assign(store.get(pid)["segments"], turns)
        store.update(pid, snapshot=True, segments=segs, speakers=speakers)
    return QUEUE.submit(Job("diarize", f"Speakers for {p['name']}", run, pid)).to_dict()


@app.post("/api/projects/{pid}/translate")
def do_translate(pid: str, data: dict = Body(...)):
    p = _get(pid)
    tgt = data.get("target") or "eng_Latn"
    src = data.get("source") or p.get("language") or "hi"

    def run(job: Job):
        job.set("Translating", 0.02)
        texts = [s["text"] for s in store.get(pid)["segments"]]
        out = translate.translate(texts, src, tgt, progress=lambda f: job.set(progress=f), cancel=job.cancel)
        store.update(pid, translation={"source": translate.to_flores(src), "target": tgt, "texts": out})
    return QUEUE.submit(Job("translate", f"Translate {p['name']} → {tgt}", run, pid)).to_dict()


@app.get("/api/projects/{pid}/export")
def export(pid: str, fmt: str = "srt", text: str = "original", speakers: int = 1, timestamps: int = 1):
    p = _get(pid)
    base = "".join(c for c in (p.get("name") or "transcript") if c not in '\\/:*?"<>|').strip() or "transcript"
    sp, tsm = bool(speakers), bool(timestamps)
    simple = {"srt": (exporters.to_srt, "application/x-subrip"), "vtt": (exporters.to_vtt, "text/vtt"),
              "txt": (exporters.to_txt, "text/plain"), "json": (exporters.to_json, "application/json"),
              "csv": (exporters.to_csv, "text/csv")}
    disp = lambda ext: {"Content-Disposition": f"attachment; filename*=UTF-8''{_q(base)}.{ext}"}  # noqa: E731
    if fmt in simple:
        fn, mt = simple[fmt]
        kw = {"text_mode": text, "speakers": sp}
        if fmt == "txt":
            kw["timestamps"] = tsm
        body = fn(p, **kw)
        return Response(body.encode("utf-8"), media_type=mt + "; charset=utf-8", headers=disp(fmt))
    if fmt in ("docx", "pdf"):
        dst = config.TMP_DIR / f"export-{pid}.{fmt}"
        (exporters.to_docx if fmt == "docx" else exporters.to_pdf)(p, dst, text_mode=text, speakers=sp, timestamps=tsm)
        mt = "application/pdf" if fmt == "pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        return FileResponse(dst, media_type=mt, headers=disp(fmt))
    if fmt == "html":
        import base64
        f = store.path(pid, "playback.m4a")
        b64 = base64.b64encode(f.read_bytes()).decode() if f.exists() else None
        return Response(exporters.to_html(p, text_mode=text, speakers=sp, media_b64=b64).encode("utf-8"),
                        media_type="text/html; charset=utf-8", headers=disp("html"))
    raise HTTPException(400, "Unknown format")


def _q(s: str) -> str:
    from urllib.parse import quote
    return quote(s)


@app.get("/api/projects/{pid}/videoinfo")
def videoinfo(pid: str):
    p = _get(pid)
    if not p.get("has_video"):
        raise HTTPException(400, "This project has no video.")
    w, h = audio.video_size(store.path(pid, p["media"]))
    return {"width": w, "height": h}


@app.post("/api/projects/{pid}/burn")
async def burn(pid: str, request: Request):
    p = _get(pid)
    if not p.get("has_video"):
        raise HTTPException(400, "This project has no video to burn subtitles into.")
    form = await request.form()
    timings = json.loads(form.get("cues") or "[]")
    work = config.TMP_DIR / f"burn-{pid}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    cues = []
    for i, c in enumerate(timings):
        f = form.get(f"cue{i}")
        if f is None:
            continue
        png = work / f"cue{i}.png"
        png.write_bytes(await f.read())
        cues.append((float(c["start"]), float(c["end"]), png))

    def run(job: Job):
        job.set("Burning subtitles", 0.1)
        audio.burn_subtitles(store.path(pid, p["media"]), cues, store.path(pid, "subtitled.mp4"), work)
        shutil.rmtree(work, ignore_errors=True)
        job.notes.append("Saved subtitled video.")
    return QUEUE.submit(Job("burn", f"Burn subtitles: {p['name']}", run, pid)).to_dict()


@app.get("/api/projects/{pid}/subtitled")
def subtitled(pid: str):
    f = store.path(pid, "subtitled.mp4")
    if not f.exists():
        raise HTTPException(404, "Not created yet")
    return FileResponse(f, media_type="video/mp4", filename=f"{_get(pid)['name']}-subtitled.mp4")


# ---------------------------------------------------------------- jobs, search, tools
@app.get("/api/jobs")
def jobs():
    return {"paused": QUEUE.paused.is_set(), "jobs": QUEUE.list()}


@app.post("/api/jobs/{jid}/cancel")
def cancel_job(jid: str):
    QUEUE.cancel(jid)
    return {"ok": True}


@app.post("/api/queue/{action}")
def queue_action(action: str):
    if action == "pause":
        QUEUE.paused.set()
    elif action == "resume":
        QUEUE.paused.clear()
    elif action == "clear":
        QUEUE.clear_finished()
    return {"paused": QUEUE.paused.is_set()}


@app.get("/api/search")
def search(q: str = ""):
    return store.search(q)


@app.post("/api/romanize")
def romanize(data: dict = Body(...)):
    from indicnlp.transliterate.unicode_transliterate import ItransTransliterator
    lang = {"as": "bn"}.get(data.get("lang"), data.get("lang") or "hi")
    texts = data.get("texts") or []
    out = []
    for t in texts:
        try:
            out.append(ItransTransliterator.to_itrans(t, lang))
        except Exception:
            out.append(t)
    return {"texts": out}


@app.websocket("/api/live")
async def live_ws(ws: WebSocket):
    await live.handle(ws)


@app.post("/api/shutdown")
def shutdown():
    def stop():
        time.sleep(0.4)
        QUEUE.stopping.set()
        for j in list(QUEUE.jobs.values()):
            j.cancel.set()
        srv = SERVER.get("uvicorn")
        if srv:
            srv.should_exit = True
        time.sleep(3)
        os._exit(0)
    threading.Thread(target=stop, daemon=True).start()
    return {"ok": True}


@app.exception_handler(Exception)
async def err(request: Request, exc: Exception):
    log.exception("Unhandled error on %s", request.url.path)
    return JSONResponse({"detail": str(exc)}, status_code=500)
