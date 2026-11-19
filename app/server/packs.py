"""Model packs: optional add-ons installed from local files.

A pack is a .vtpack (zip) with a pack.json manifest at its root, e.g.

    {"format": 1, "id": "whisper-large-v3-turbo", "type": "asr-ct2",
     "name": "Whisper large-v3-turbo", "version": "1", "languages": ["*"],
     "preferred_for": [], "model_dir": "model", "license": "MIT", "source": "https://..."}

Types: asr-ct2 (CTranslate2 Whisper/IndicWhisper), asr-hf (any Hugging Face
speech-recognition model run through transformers), diarization (sherpa-onnx
segmentation + embedding ONNX), translation (IndicTrans2), gpu-runtime
(NVIDIA cuBLAS/cuDNN DLLs for GPU decoding).
"""
import json
import os
import shutil
import sys
import threading
import zipfile
from pathlib import Path

from .config import PACKS_DIR, TMP_DIR

TYPES = {"asr-ct2", "asr-hf", "diarization", "translation", "gpu-runtime"}
_lock = threading.Lock()
_dll_handles = []


class PackError(Exception):
    pass


def _read_manifest(folder: Path) -> dict:
    mf = folder / "pack.json"
    if not mf.exists():
        raise PackError("This file is not a VU3INI model pack (pack.json is missing).")
    try:
        m = json.loads(mf.read_text(encoding="utf-8"))
    except Exception as e:
        raise PackError(f"pack.json is not valid JSON: {e}")
    for key in ("id", "type", "name"):
        if not m.get(key):
            raise PackError(f"pack.json is missing '{key}'.")
    if m["type"] not in TYPES:
        raise PackError(f"Unknown pack type '{m['type']}'.")
    if not all(c.isalnum() or c in "-_." for c in m["id"]):
        raise PackError("Pack id may only contain letters, digits, '-', '_' and '.'.")
    return m


def list_packs() -> list:
    out = []
    for d in sorted(PACKS_DIR.iterdir()) if PACKS_DIR.exists() else []:
        if d.is_dir() and (d / "pack.json").exists():
            try:
                m = _read_manifest(d)
            except PackError:
                continue
            m["path"] = str(d)
            m["size_mb"] = round(sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) / 1e6, 1)
            out.append(m)
    return out


def get(pack_id: str) -> dict | None:
    for p in list_packs():
        if p["id"] == pack_id:
            return p
    return None


def by_type(t: str) -> list:
    return [p for p in list_packs() if p["type"] == t]


def _safe_extract(zf: zipfile.ZipFile, dest: Path, progress=None):
    dest = dest.resolve()
    members = zf.infolist()
    total = sum(m.file_size for m in members) or 1
    done = 0
    for m in members:
        target = (dest / m.filename).resolve()
        if not str(target).startswith(str(dest)):
            raise PackError(f"Unsafe path inside pack: {m.filename}")
        if m.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(m) as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst, 1024 * 1024)
        done += m.file_size
        if progress:
            progress(done / total)


def install_from_file(path: Path, progress=None) -> dict:
    path = Path(path)
    if not path.exists():
        raise PackError(f"File not found: {path}")
    if not zipfile.is_zipfile(path):
        raise PackError("A pack must be a .vtpack (zip) file.")
    with _lock:
        stage = TMP_DIR / f"pack-stage-{os.getpid()}-{threading.get_ident()}"
        shutil.rmtree(stage, ignore_errors=True)
        stage.mkdir(parents=True)
        try:
            with zipfile.ZipFile(path) as zf:
                _safe_extract(zf, stage, progress)
            root = stage
            if not (root / "pack.json").exists():
                subs = [p for p in stage.iterdir() if p.is_dir()]
                if len(subs) == 1 and (subs[0] / "pack.json").exists():
                    root = subs[0]
            m = _read_manifest(root)
            final = PACKS_DIR / m["id"]
            if final.exists():
                shutil.rmtree(final)
            shutil.move(str(root), str(final))
        finally:
            shutil.rmtree(stage, ignore_errors=True)
    if m["type"] == "gpu-runtime":
        register_gpu_runtime()
    m["path"] = str(final)
    return m


def remove(pack_id: str):
    p = get(pack_id)
    if not p:
        raise PackError("No such pack.")
    shutil.rmtree(p["path"])


def register_gpu_runtime():
    """Make CUDA DLLs from an installed gpu-runtime pack visible to CTranslate2."""
    for p in by_type("gpu-runtime"):
        d = Path(p["path"]) / p.get("dll_dir", "bin")
        if not d.exists():
            continue
        os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
        if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
            try:
                _dll_handles.append(os.add_dll_directory(str(d)))
            except OSError:
                pass
