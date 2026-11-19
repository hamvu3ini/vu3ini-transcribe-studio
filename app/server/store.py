"""Projects: each transcript lives in its own folder with media, peaks and version history."""
import json
import shutil
import threading
import time
import uuid
from pathlib import Path

from .config import PROJECTS_DIR

_lock = threading.RLock()
MAX_VERSIONS = 30


def _dir(pid: str) -> Path:
    if not pid or not all(c.isalnum() or c in "-_" for c in pid):
        raise KeyError(pid)
    return PROJECTS_DIR / pid


def new_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


def create(name: str, media_src: Path | None, **fields) -> dict:
    pid = new_id()
    d = _dir(pid)
    d.mkdir(parents=True)
    p = {"id": pid, "name": name, "created": time.strftime("%Y-%m-%d %H:%M"), "updated": time.strftime("%Y-%m-%d %H:%M"),
         "status": "new", "segments": [], "speakers": {}, "tags": [], "language": None, "engine": None,
         "duration": 0, "media": None, "notes": [], **fields}
    if media_src:
        dst = d / ("source" + Path(media_src).suffix.lower())
        shutil.move(str(media_src), dst)
        p["media"] = dst.name
    _write(p)
    return p


def _write(p: dict):
    d = _dir(p["id"])
    tmp = d / "project.json.tmp"
    tmp.write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(d / "project.json")


def get(pid: str) -> dict:
    with _lock:
        return json.loads((_dir(pid) / "project.json").read_text(encoding="utf-8"))


def update(pid: str, snapshot=False, **fields) -> dict:
    with _lock:
        p = get(pid)
        if snapshot and p.get("segments"):
            vd = _dir(pid) / "versions"
            vd.mkdir(exist_ok=True)
            (vd / (time.strftime("%Y%m%d-%H%M%S") + ".json")).write_text(
                json.dumps({"segments": p["segments"], "speakers": p.get("speakers")}, ensure_ascii=False), encoding="utf-8")
            vs = sorted(vd.glob("*.json"))
            for old in vs[:-MAX_VERSIONS]:
                old.unlink()
        p.update(fields)
        p["updated"] = time.strftime("%Y-%m-%d %H:%M")
        _write(p)
        return p


def versions(pid: str) -> list:
    vd = _dir(pid) / "versions"
    return [v.stem for v in sorted(vd.glob("*.json"), reverse=True)] if vd.exists() else []


def restore(pid: str, version: str) -> dict:
    v = json.loads((_dir(pid) / "versions" / f"{Path(version).name}.json").read_text(encoding="utf-8"))
    return update(pid, snapshot=True, segments=v["segments"], speakers=v.get("speakers") or {})


def list_all() -> list:
    out = []
    for f in sorted(PROJECTS_DIR.glob("*/project.json"), reverse=True):
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        out.append({k: p.get(k) for k in ("id", "name", "created", "updated", "status", "language", "engine",
                                          "duration", "tags")} | {"segments": len(p.get("segments") or [])})
    return out


def delete(pid: str):
    with _lock:
        shutil.rmtree(_dir(pid), ignore_errors=True)


def path(pid: str, name: str) -> Path:
    f = (_dir(pid) / name).resolve()
    if not str(f).startswith(str(_dir(pid).resolve())):
        raise KeyError(name)
    return f


def search(q: str, limit=200) -> list:
    q = q.strip().lower()
    if not q:
        return []
    hits = []
    for f in sorted(PROJECTS_DIR.glob("*/project.json"), reverse=True):
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        name_hit = q in (p.get("name") or "").lower() or any(q in t.lower() for t in p.get("tags") or [])
        if name_hit:
            hits.append({"id": p["id"], "name": p["name"], "start": 0, "text": "(name or tag match)"})
        for s in p.get("segments") or []:
            if q in s["text"].lower():
                hits.append({"id": p["id"], "name": p["name"], "start": s["start"], "text": s["text"]})
                if len(hits) >= limit:
                    return hits
    return hits
