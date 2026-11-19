"""Automated tests for VU3INI Transcribe Studio.

Run (Linux, network disabled):
    unshare -n sh -c "ip link set lo up && python -m pytest -q tests"
They start the real launcher (no tray, no browser), drive the API and the web UI in
Chrome, then check that shutdown leaves no processes behind.
"""
import asyncio
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import psutil
import pytest

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
DATA = Path("/tmp/vts-test-data")
MODEL = Path("/tmp/vts-test-model")
CHROME = shutil.which("google-chrome") or shutil.which("chromium")
sys.path.insert(0, str(ROOT / "app" / "tools"))
sys.path.insert(0, str(ROOT / "tests"))


def http(port, path, data=None, method=None, raw=False, timeout=60):
    body = None
    headers = {}
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body, headers=headers,
                                 method=method or ("POST" if data is not None else "GET"))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        b = r.read()
        return b if raw else json.loads(b)


def wait_job(port, jid, timeout=180):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = {x["id"]: x for x in http(port, "/api/jobs")["jobs"]}.get(jid)
        if j and j["status"] not in ("queued", "running"):
            return j
        time.sleep(0.3)
    raise TimeoutError(jid)


def upload(port, path: Path, **fields):
    import httpx
    with open(path, "rb") as f:
        r = httpx.post(f"http://127.0.0.1:{port}/api/projects", files={"file": (path.name, f)},
                       data={k: str(v) for k, v in fields.items()}, timeout=60)
    r.raise_for_status()
    return r.json()


def make_audio(path: Path, seconds=6, video=False):
    src = ["-f", "lavfi", "-i", f"anoisesrc=d={seconds}:a=0.2"]
    if video:
        src = ["-f", "lavfi", "-i", f"testsrc=s=640x360:d={seconds}"] + src + ["-shortest"]
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *src, str(path)], check=True)
    return path


# ---------------------------------------------------------------- fixtures
@pytest.fixture(scope="session")
def test_pack():
    """A .vtpack containing a tiny random Whisper model, built with the real pack writer."""
    import make_packs
    from make_test_model import main as build_model
    shutil.rmtree(MODEL, ignore_errors=True)
    stage = MODEL / "stage"
    build_model(str(stage / "model"))
    return make_packs.write_pack(stage, {"id": "test-whisper", "name": "Test Whisper", "type": "asr-ct2",
                                         "languages": ["*"], "model_dir": "model", "license": "test"}, MODEL / "out")


@pytest.fixture(scope="session")
def app(test_pack):
    shutil.rmtree(DATA, ignore_errors=True)
    DATA.mkdir(parents=True)
    # settings that suit the random test model (it produces repetitive text)
    (DATA / "settings.json").write_text(json.dumps({"hallucination_guard": False, "vad_filter": False, "beam_size": 1}))
    env = dict(os.environ, VTS_DATA_DIR=str(DATA), VTS_NO_TRAY="1", VTS_NO_BROWSER="1", PYTHONPATH=str(APP))
    proc = subprocess.Popen([sys.executable, str(APP / "launcher" / "launcher.py")], env=env, start_new_session=True)
    port_file = DATA / "run" / "port"
    t0 = time.time()
    while time.time() - t0 < 60:
        if port_file.exists():
            port = int(port_file.read_text())
            try:
                if http(port, "/api/ping")["ok"]:
                    break
            except Exception:
                pass
        time.sleep(0.3)
    else:
        proc.kill()
        pytest.fail("server did not start")
    yield {"port": port, "launcher": proc, "env": env}
    if proc.poll() is None:
        try:
            http(port, "/api/shutdown", {})
        except Exception:
            pass
        try:
            proc.wait(15)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)


# ---------------------------------------------------------------- offline startup
def test_network_disabled_environment():
    """The suite is meant to run without a network: only loopback should be reachable."""
    import socket
    with pytest.raises(OSError):
        socket.create_connection(("1.1.1.1", 443), timeout=3)


def test_startup_binds_localhost_only(app):
    port = app["port"]
    conns = [c for c in psutil.net_connections("tcp") if c.laddr and c.laddr.port == port and c.status == "LISTEN"]
    assert conns, "server is not listening"
    assert all(c.laddr.ip in ("127.0.0.1",) for c in conns)
    assert http(port, "/api/ping")["version"] == (ROOT / "VERSION").read_text().strip()


def test_page_has_no_external_references(app):
    html = http(app["port"], "/", raw=True).decode()
    js = http(app["port"], "/app.js", raw=True).decode()
    css = http(app["port"], "/style.css", raw=True).decode()
    for text in (html, js, css):
        assert "https://" not in text and "http://" not in text, "page references an external URL"


def test_netguard_blocks_and_logs(app):
    sys.path.insert(0, str(APP))
    from server import netguard
    netguard.install()
    with pytest.raises(OSError):
        urllib.request.urlopen("http://example.com", timeout=3)
    assert any(a["host"] == "example.com" for a in netguard.attempts())


# ---------------------------------------------------------------- packs
def test_install_pack_from_path(app, test_pack):
    port = app["port"]
    j = http(port, "/api/packs/install-path", {"path": str(test_pack)})
    assert wait_job(port, j["id"])["status"] == "done"
    packs = http(port, "/api/packs")
    assert [p["id"] for p in packs] == ["test-whisper"]
    assert http(port, "/api/info")["asr_packs"][0]["id"] == "test-whisper"


def test_pack_catalog_and_offline_download(app):
    """Get model packs: the catalogue lists packs; with no internet the download fails with a clear message."""
    port = app["port"]
    cat = http(port, "/api/packs/catalog")["catalog"]
    ids = [c["id"] for c in cat]
    assert "whisper-large-v3-turbo" in ids and "diarization" in ids and "gpu-runtime" in ids
    j = http(port, "/api/packs/download", {"ids": ["diarization"], "token": "", "keep": False})
    r = wait_job(port, j["id"], timeout=240)
    assert r["status"] == "failed" and "internet" in r["error"].lower(), r


def test_custom_pack_id_validated(app):
    import urllib.error
    with pytest.raises(urllib.error.HTTPError):
        http(app["port"], "/api/packs/download", {"custom": {"repo": "not a model id"}})


def test_reject_bad_pack(app, tmp_path):
    bad = tmp_path / "bad.vtpack"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("../evil.txt", "x")
    j = http(app["port"], "/api/packs/install-path", {"path": str(bad)})
    r = wait_job(app["port"], j["id"])
    assert r["status"] == "failed"


# ---------------------------------------------------------------- core features
@pytest.fixture(scope="session")
def project(app, test_pack):
    port = app["port"]
    if not http(port, "/api/packs"):
        wait_job(port, http(port, "/api/packs/install-path", {"path": str(test_pack)})["id"])
    wav = make_audio(Path("/tmp/vts-test.wav"))
    r = upload(port, wav, language="auto", engine="auto")
    j = wait_job(port, r["job"]["id"])
    assert j["status"] == "done", j
    return http(port, f"/api/projects/{r['project']['id']}")


def test_transcribe_file(project):
    assert project["status"] == "done"
    assert project["segments"], "no segments"
    s = project["segments"][0]
    assert s["words"] and all(k in s["words"][0] for k in ("w", "s", "e", "p"))
    assert 5.5 < project["duration"] < 6.5


def test_waveform_and_player(app, project):
    peaks = http(app["port"], f"/api/projects/{project['id']}/peaks")
    assert len(peaks) > 1000
    m = http(app["port"], f"/api/projects/{project['id']}/media", raw=True)
    assert m[4:8] == b"ftyp"


@pytest.mark.parametrize("fmt", ["srt", "vtt", "txt", "json", "csv", "docx", "pdf", "html"])
def test_exports(app, project, fmt):
    b = http(app["port"], f"/api/projects/{project['id']}/export?fmt={fmt}", raw=True)
    assert b
    if fmt == "srt":
        assert b.startswith(b"1\n00:00:")
    elif fmt == "vtt":
        assert b.startswith(b"WEBVTT")
    elif fmt == "json":
        assert json.loads(b)["segments"]
    elif fmt == "docx":
        import docx
        assert docx.Document(io.BytesIO(b)).paragraphs
    elif fmt == "pdf":
        assert b.startswith(b"%PDF")
    elif fmt == "html":
        assert b"<audio" in b and b"data:audio/mp4;base64," in b


def test_edit_save_history_restore(app, project):
    port, pid = app["port"], project["id"]
    p = http(port, f"/api/projects/{pid}")
    original = p["segments"][0]["text"]
    p["segments"][0]["text"] = "অসমীয়া সম্পাদনা পৰীক্ষা"
    http(port, f"/api/projects/{pid}", {"segments": p["segments"], "speakers": {"S1": "Sasanka"}, "tags": ["test"]}, "PUT")
    p2 = http(port, f"/api/projects/{pid}")
    assert p2["segments"][0]["text"] == "অসমীয়া সম্পাদনা পৰীক্ষা" and p2["tags"] == ["test"]
    vs = http(port, f"/api/projects/{pid}/versions")
    assert vs
    time.sleep(1.1)
    http(port, f"/api/projects/{pid}/restore", {"version": vs[-1]})
    assert http(port, f"/api/projects/{pid}")["segments"][0]["text"] == original


def test_search_across_transcripts(app, project):
    word = project["segments"][0]["text"].split()[0]
    hits = http(app["port"], "/api/search?q=" + urllib.request.quote(word))
    assert any(h["id"] == project["id"] for h in hits)


def test_custom_corrections_applied(app, project):
    port = app["port"]
    word = project["segments"][0]["text"].split()[0]
    http(port, "/api/settings", {"replacements": [{"from": word, "to": "VU3INI"}]})
    j = http(port, f"/api/projects/{project['id']}/transcribe", {"language": "en"})
    assert wait_job(port, j["id"])["status"] == "done"
    assert "VU3INI" in http(port, f"/api/projects/{project['id']}")["segments"][0]["text"]
    http(port, "/api/settings", {"replacements": []})


def test_language_engine_choice(app, test_pack, tmp_path):
    """A pack chosen for a language in Model packs is used for that language."""
    port = app["port"]
    alt = tmp_path / "alt.vtpack"
    with zipfile.ZipFile(test_pack) as zin, zipfile.ZipFile(alt, "w", zipfile.ZIP_STORED) as zout:
        for item in zin.infolist():
            data = zin.read(item)
            if item.filename == "pack.json":
                m = json.loads(data)
                m.update(id="alt-whisper", name="Alt Whisper", languages=["as"])
                data = json.dumps(m).encode()
            zout.writestr(item, data)
    assert wait_job(port, http(port, "/api/packs/install-path", {"path": str(alt)})["id"])["status"] == "done"
    http(port, "/api/settings", {"language_engines": {"en": "alt-whisper"}})
    r = upload(port, make_audio(Path("/tmp/vts-le.wav"), 3), language="en", engine="auto")
    j = wait_job(port, r["job"]["id"])
    assert j["status"] == "done" and any("Alt Whisper" in n for n in j["notes"]), j
    assert http(port, f"/api/projects/{r['project']['id']}")["engine"] == "Alt Whisper"
    http(port, "/api/settings", {"language_engines": {}})
    r = upload(port, make_audio(Path("/tmp/vts-le2.wav"), 3), language="en", engine="auto")
    wait_job(port, r["job"]["id"])
    assert http(port, f"/api/projects/{r['project']['id']}")["engine"] == "Test Whisper"


def test_hallucination_guard_drops_repeats():
    sys.path.insert(0, str(APP))
    from server import engines
    segs = [{"start": 0, "end": 1, "text": "Thank you for watching!", "words": []},
            {"start": 1, "end": 2, "text": "real speech here", "words": []},
            {"start": 2, "end": 3, "text": "la la la la la la la la la la", "words": []}]
    out = engines.postprocess(segs, {"hallucination_guard": True}, [])
    assert [s["text"] for s in out] == ["real speech here"]


def test_batch_folder(app, tmp_path):
    port = app["port"]
    for i in range(2):
        make_audio(tmp_path / f"clip{i}.wav", 3)
    r = http(port, "/api/batch", {"folder": str(tmp_path), "language": "en"})
    assert len(r["jobs"]) == 2
    for j in r["jobs"]:
        assert wait_job(port, j["id"])["status"] == "done"
    assert (tmp_path / "clip0.wav").exists(), "original must not be moved"


def test_queue_pause_cancel(app):
    port = app["port"]
    http(port, "/api/queue/pause", {})
    r = upload(port, make_audio(Path("/tmp/vts-q.wav"), 3), language="en")
    time.sleep(1)
    j = {x["id"]: x for x in http(port, "/api/jobs")["jobs"]}[r["job"]["id"]]
    assert j["status"] in ("queued", "running")
    http(port, f"/api/jobs/{r['job']['id']}/cancel", {})
    http(port, "/api/queue/resume", {})
    assert wait_job(port, r["job"]["id"])["status"] == "cancelled"


def test_settings_persist(app):
    port = app["port"]
    http(port, "/api/settings", {"custom_vocabulary": ["VU3INI", "Agartala"], "beam_size": 2})
    s = json.loads((DATA / "settings.json").read_text())
    assert s["custom_vocabulary"] == ["VU3INI", "Agartala"] and s["beam_size"] == 2
    http(port, "/api/settings", {"custom_vocabulary": [], "beam_size": 1})


def test_romanize(app):
    r = http(app["port"], "/api/romanize", {"lang": "hi", "texts": ["नमस्ते"]})
    assert r["texts"][0] and r["texts"][0] != "नमस्ते"


def test_live_websocket(app):
    import websockets

    async def run():
        uri = f"ws://127.0.0.1:{app['port']}/api/live"
        async with websockets.connect(uri, max_size=None) as ws:
            await ws.send(json.dumps({"type": "start", "language": "en", "name": "live test"}))
            assert json.loads(await ws.recv())["type"] == "ready"
            sr = 16000
            t = np.arange(sr * 4) / sr
            speech = (np.sin(2 * np.pi * 220 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 3 * t)) * 0.4)
            pcm = (np.concatenate([speech, np.zeros(sr)]) * 32767).astype(np.int16).tobytes()
            for i in range(0, len(pcm), 3200):
                await ws.send(pcm[i:i + 3200])
                await asyncio.sleep(0.01)
            await ws.send(json.dumps({"type": "stop"}))
            msgs = []
            while True:
                m = json.loads(await asyncio.wait_for(ws.recv(), 120))
                msgs.append(m)
                if m["type"] in ("saved", "error"):
                    break
            return msgs

    msgs = asyncio.run(run())
    assert msgs[-1]["type"] == "saved" and msgs[-1]["project_id"], msgs[-3:]
    p = http(app["port"], f"/api/projects/{msgs[-1]['project_id']}")
    assert p["name"] == "live test" and 4.5 < p["duration"] < 5.5


def test_diarization_and_translation_need_packs(app, project):
    port = app["port"]
    j = http(port, f"/api/projects/{project['id']}/diarize", {})
    r = wait_job(port, j["id"])
    assert r["status"] == "failed" and "diarization pack" in r["error"]
    j = http(port, f"/api/projects/{project['id']}/translate", {"target": "eng_Latn", "source": "hi"})
    r = wait_job(port, j["id"])
    assert r["status"] == "failed" and "IndicTrans2" in r["error"]


# ---------------------------------------------------------------- browser UI (splash, theme, help, about, burn-in)
@pytest.fixture(scope="session")
def browser():
    if not CHROME:
        pytest.skip("Chrome not available")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        yield b
        b.close()


def _open(browser, app, agree=True):
    ctx = browser.new_context(viewport={"width": 1366, "height": 860}, accept_downloads=True)
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    external = []
    pg.on("request", lambda r: external.append(r.url) if not r.url.startswith(("http://127.0.0.1", "data:", "blob:", "ws://127.0.0.1")) else None)
    pg.goto(f"http://127.0.0.1:{app['port']}/")
    pg._vts = (errors, external)
    if agree:
        pg.wait_for_timeout(3100)
        pg.click("#splashOk")
    return pg


def test_splash(browser, app):
    pg = _open(browser, app, agree=False)
    box = pg.locator("#splashBox").bounding_box()
    assert (box["width"], box["height"]) == (384, 288)
    vw = pg.viewport_size
    assert abs(box["x"] + 192 - vw["width"] / 2) < 2 and abs(box["y"] + 144 - vw["height"] / 2) < 2
    assert pg.eval_on_selector(".splash .logo-circle", "e => getComputedStyle(e).borderRadius") == "50%"
    assert "VU3INI Transcribe Studio" in pg.inner_text("#splashTitle")
    assert "By Sasanka Boruah -VU3INI" in pg.inner_text("#splashBox")
    terms = pg.inner_text("#terms")
    for phrase in ("non-commercial", "indemnify", "AS IS", "github.com/openai/whisper", "Guwahati",
                   "By clicking 'Agree / OK'"):
        assert phrase in terms
    assert pg.is_disabled("#splashOk")
    pg.wait_for_timeout(1500)
    assert pg.is_disabled("#splashOk"), "button must stay disabled before 3 s"
    pg.wait_for_timeout(1700)
    assert not pg.is_disabled("#splashOk")
    pg.click("#splashOk")
    assert pg.is_hidden("#splash")
    assert not pg._vts[0], pg._vts[0]
    assert not pg._vts[1], f"external requests: {pg._vts[1]}"
    pg.context.close()


def test_logo_footer_theme(browser, app):
    pg = _open(browser, app)
    logo = pg.locator("#brandLogo").bounding_box()
    assert logo["x"] < 40 and logo["y"] < 20, logo
    foot = pg.locator(".footer")
    assert foot.inner_text().strip() == "By Sasanka Boruah -VU3INI"
    fb = foot.bounding_box()
    assert fb["x"] == 0 and abs(fb["y"] + fb["height"] - 860) < 1
    assert pg.eval_on_selector(".footer", "e => getComputedStyle(e).position") == "fixed"
    start = pg.get_attribute("html", "data-theme")
    pg.click("#themeBtn")
    flipped = pg.get_attribute("html", "data-theme")
    assert flipped != start
    pg.reload()
    assert pg.get_attribute("html", "data-theme") == flipped, "theme not remembered"
    pg.context.close()


def test_help_and_about(browser, app):
    pg = _open(browser, app)
    pg.keyboard.press("F1")
    pg.wait_for_selector("#helpContent section")
    total = pg.locator("#helpContent section").count()
    assert total >= 20
    pg.fill("#helpSearch", "burned")
    assert 0 < pg.locator("#helpContent section").count() < total
    assert pg.locator("#helpContent mark").count() > 0
    pg.fill("#helpSearch", "zzqqxx")
    assert "Nothing matches" in pg.inner_text("#helpContent")
    pg.keyboard.press("Escape")
    pg.click("#helpBtn")
    pg.click("#helpMenu [data-act=about]")
    txt = pg.inner_text("#aboutModal")
    for s in ("hamvu3ini@gmail.com", "By Sasanka Boruah -VU3INI", "openai/whisper", "AI4Bharat/vistaar", "Version "):
        assert s in txt
    assert pg.locator("#aboutComps tr").count() >= 20
    assert not pg._vts[0]
    pg.context.close()


def test_get_packs_card(browser, app):
    pg = _open(browser, app)
    pg.click("#tabs [data-view=packs]")
    pg.wait_for_selector("#catTbl input[data-pack=whisper-large-v3-turbo]")
    assert pg.locator("#catTbl input[data-pack]").count() >= 10
    pg.click("#customBox summary")
    assert pg.eval_on_selector("#cLang", "s => s.value") == "as"
    assert pg.get_attribute("#hfToken", "type") == "password"
    assert not pg._vts[0]
    pg.context.close()


def test_language_engine_dropdowns(browser, app):
    pg = _open(browser, app)
    pg.click("#tabs [data-view=packs]")
    pg.wait_for_selector("#langEngines select[data-lang=as]")
    assert pg.locator("#langEngines select").count() == 15
    opts = pg.eval_on_selector("#langEngines select[data-lang=as]", "s => [...s.options].map(o => o.value)")
    assert opts[0] == "auto" and "test-whisper" in opts
    pg.select_option("#langEngines select[data-lang=as]", "test-whisper")
    pg.click("#leSave")
    pg.wait_for_timeout(500)
    assert http(app["port"], "/api/settings")["language_engines"] == {"as": "test-whisper"}
    pg.reload(); pg.wait_for_timeout(3100); pg.click("#splashOk"); pg.click("#tabs [data-view=packs]")
    pg.wait_for_selector("#langEngines select[data-lang=as]")
    assert pg.eval_on_selector("#langEngines select[data-lang=as]", "s => s.value") == "test-whisper"
    pg.click("#leReset"); pg.wait_for_timeout(500)
    assert http(app["port"], "/api/settings")["language_engines"] == {}
    assert not pg._vts[0]
    pg.context.close()


def test_editor_click_word_and_burn_subtitles(browser, app):
    port = app["port"]
    r = upload(port, make_audio(Path("/tmp/vts-video.mp4"), 4, video=True), language="en")
    assert wait_job(port, r["job"]["id"])["status"] == "done"
    pid = r["project"]["id"]
    pg = _open(browser, app)
    pg.evaluate(f"openProject('{pid}')")
    pg.wait_for_selector("#txList .seg .w")
    pg.locator("#txList .seg .w").nth(3).dblclick()
    pg.wait_for_timeout(600)
    assert pg.evaluate("document.getElementById('audio').currentTime") > 0
    pg.click("#edExportBtn")
    pg.click("#burnBtn")
    t0 = time.time()
    jid = None
    while time.time() - t0 < 120 and jid is None:
        js = [j for j in http(port, "/api/jobs")["jobs"] if j["kind"] == "burn" and j["project_id"] == pid]
        jid = js[0]["id"] if js else None
        time.sleep(0.5)
    assert jid and wait_job(port, jid)["status"] == "done"
    vid = http(port, f"/api/projects/{pid}/subtitled", raw=True)
    assert vid[4:8] == b"ftyp"
    assert not pg._vts[0] and not pg._vts[1]
    pg.context.close()


# ---------------------------------------------------------------- single instance and clean shutdown (run last)
def test_single_instance(app):
    t0 = time.time()
    r = subprocess.run([sys.executable, str(APP / "launcher" / "launcher.py")], env=app["env"], timeout=30)
    assert r.returncode == 0 and time.time() - t0 < 20
    servers = [p for p in psutil.process_iter(["cmdline"])
               if "server.run" in " ".join(p.info["cmdline"] or []) and str(DATA) in " ".join(p.info["cmdline"] or [])]
    assert len(servers) == 1, "a second server was started"


def test_zz_splash_exit_shuts_everything_down(browser, app):
    """Clicking Exit on the start-up splash must stop the server, the launcher and every child."""
    launcher = psutil.Process(app["launcher"].pid)
    kids = launcher.children(recursive=True)
    assert kids, "launcher has no server child"
    pg = _open(browser, app, agree=False)
    pg.click("#splashExit")
    pg.wait_for_selector("#closedScreen:not(.hidden)", timeout=10000)
    app["launcher"].wait(20)
    gone, alive = psutil.wait_procs(kids, timeout=10)
    assert not alive, f"leftover processes: {alive}"
    assert not (DATA / "run" / "port").exists()
    with pytest.raises(OSError):
        http(app["port"], "/api/ping", timeout=2)
    pg.context.close()
