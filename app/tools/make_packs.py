"""Make-Packs: build VU3INI Transcribe Studio model packs (.vtpack) on a PC with internet.

Run with the app's own Python (Make-Packs.bat does this):
    python\\python.exe app\\tools\\make_packs.py [pack numbers...] [--out folder] [--token HF_TOKEN]

Each pack is a zip with a pack.json manifest. Install the files in the app:
Model packs -> Install pack from file.
"""
import argparse
import getpass
import json
import os
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_DEFAULT = Path(os.environ.get("VTS_PACKS_OUT") or (HERE.parent.parent / "packs-out"))

SHERPA = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
CATALOG = [
    {"id": "whisper-large-v3-turbo", "name": "Whisper large-v3-turbo (multilingual, recommended)", "kind": "hf-ct2",
     "repo": "openai/whisper-large-v3-turbo", "quant": "float16", "languages": ["*"], "license": "MIT", "size": "≈1.6 GB"},
    {"id": "whisper-large-v3", "name": "Whisper large-v3 (multilingual, most accurate, slower)", "kind": "hf-ct2",
     "repo": "openai/whisper-large-v3", "quant": "float16", "languages": ["*"], "license": "MIT", "size": "≈3.1 GB"},
    {"id": "whisper-small", "name": "Whisper small (multilingual, fast; good for CPU and live mode)", "kind": "hf-ct2",
     "repo": "openai/whisper-small", "quant": "float16", "languages": ["*"], "license": "MIT", "size": "≈0.5 GB"},
    {"id": "indicwhisper-hindi", "name": "AI4Bharat IndicWhisper — Hindi", "kind": "zip-ct2",
     "url": "https://indicwhisper.objectstore.e2enetworks.net/hindi_models.zip", "languages": ["hi"],
     "preferred_for": ["hi"], "license": "MIT", "size": "≈1.5 GB (download ≈3 GB)"},
    {"id": "indicwhisper-bengali", "name": "AI4Bharat IndicWhisper — Bengali", "kind": "zip-ct2",
     "url": "https://indicwhisper.objectstore.e2enetworks.net/bengali_models.zip", "languages": ["bn"],
     "preferred_for": ["bn"], "license": "MIT", "size": "≈1.5 GB (download ≈3 GB)"},
    {"id": "diarization", "name": "Speaker diarization (pyannote segmentation 3.0 + 3D-Speaker ERes2Net, ONNX)",
     "kind": "diarization", "license": "MIT (segmentation) / Apache-2.0 (embedding)", "size": "≈40 MB",
     "seg_url": f"{SHERPA}/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2",
     "emb_url": f"{SHERPA}/speaker-recongition-models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"},
    {"id": "indictrans2-en-indic", "name": "IndicTrans2 English → Indic (distilled 200M)", "kind": "hf-raw",
     "repo": "ai4bharat/indictrans2-en-indic-dist-200M", "type": "translation", "direction": "en-indic", "license": "MIT", "size": "≈0.9 GB"},
    {"id": "indictrans2-indic-en", "name": "IndicTrans2 Indic → English (distilled 200M)", "kind": "hf-raw",
     "repo": "ai4bharat/indictrans2-indic-en-dist-200M", "type": "translation", "direction": "indic-en", "license": "MIT", "size": "≈0.9 GB"},
    {"id": "indictrans2-indic-indic", "name": "IndicTrans2 Indic → Indic (distilled 320M)", "kind": "hf-raw",
     "repo": "ai4bharat/indictrans2-indic-indic-dist-320M", "type": "translation", "direction": "indic-indic", "license": "MIT", "size": "≈1.3 GB"},
    {"id": "gpu-runtime", "name": "NVIDIA GPU runtime (cuBLAS + cuDNN for CUDA 12)", "kind": "gpu",
     "wheels": ["nvidia-cublas-cu12", "nvidia-cudnn-cu12", "nvidia-cuda-runtime-cu12"],
     "license": "NVIDIA Software License (redistributable)", "size": "≈1.9 GB"},
]


JSON_PROGRESS = False


def say(*a):
    if JSON_PROGRESS:
        print(json.dumps({"msg": " ".join(str(x) for x in a).strip()}, ensure_ascii=False), flush=True)
    else:
        print(*a, flush=True)


def report(**kw):
    if JSON_PROGRESS:
        print(json.dumps(kw, ensure_ascii=False), flush=True)


def download(url, dst: Path, headers=None):
    say(f"  downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "VU3INI-Make-Packs/1.0", **(headers or {})})
    with urllib.request.urlopen(req, timeout=60) as r, open(dst, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done, last = 0, 0
        while chunk := r.read(4 * 1024 * 1024):
            f.write(chunk)
            done += len(chunk)
            if time.time() - last > 1:
                last = time.time()
                pct = f"{done * 100 // total}%" if total else ""
                if JSON_PROGRESS:
                    report(dl_mb=round(done / 1e6, 1), dl_frac=(done / total) if total else None)
                else:
                    say(f"    {done / 1e6:,.0f} MB {pct}")
    return dst


def hf_download(repo, dst: Path, token=None):
    from huggingface_hub import snapshot_download
    say(f"  downloading {repo} from Hugging Face")
    try:
        return Path(snapshot_download(repo, local_dir=str(dst), token=token,
                                      allow_patterns=["*.json", "*.txt", "*.model", "*.py", "*.safetensors", "*.bin", "*.tiktoken", "*.spm"]))
    except Exception as e:
        if "401" in str(e) or "403" in str(e) or "gated" in str(e).lower():
            raise SystemExit(f"{repo} is gated on Hugging Face. Open https://huggingface.co/{repo}, accept its terms, "
                             "create an access token (Settings -> Access Tokens) and paste it into the token box.")
        raise


def convert_ct2(src: Path, dst: Path, quant="float16"):
    """Convert a Hugging Face Whisper checkpoint to CTranslate2 for faster-whisper."""
    from ctranslate2.converters import TransformersConverter
    from transformers import WhisperTokenizerFast
    tok_json = src / "tokenizer.json"
    if not tok_json.exists():
        WhisperTokenizerFast.from_pretrained(str(src)).save_pretrained(str(src))
    copy = [f for f in ("tokenizer.json", "preprocessor_config.json") if (src / f).exists()]
    say(f"  converting to CTranslate2 ({quant})…")
    TransformersConverter(str(src), copy_files=copy, load_as_float16=quant == "float16").convert(
        str(dst), quantization=quant, force=True)
    return dst


def find_model_dir(root: Path) -> Path:
    cands = [p.parent for p in root.rglob("config.json") if (p.parent / "generation_config.json").exists()
             or any((p.parent / f).exists() for f in ("pytorch_model.bin", "model.safetensors"))]
    if not cands:
        raise SystemExit(f"No Whisper checkpoint found inside {root}")
    return sorted(cands, key=lambda p: len(str(p)))[0]


def write_pack(stage: Path, manifest: dict, out_dir: Path) -> Path:
    manifest = {"format": 1, "version": time.strftime("%Y.%m.%d"), **manifest}
    (stage / "pack.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / f"{manifest['id']}.vtpack"
    say(f"  writing {dst.name}")
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_STORED, allowZip64=True) as z:
        for f in sorted(stage.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(stage).as_posix())
    say(f"  done: {dst} ({dst.stat().st_size / 1e9:.2f} GB)")
    return dst


def build(item: dict, out_dir: Path, token=None) -> Path:
    say(f"\n=== {item['name']} ({item['size']}) ===")
    work = Path(tempfile.mkdtemp(prefix="vtpack-"))
    stage = work / "pack"
    stage.mkdir()
    base = {"id": item["id"], "name": item["name"].split(" (")[0], "license": item["license"]}
    try:
        k = item["kind"]
        if k == "hf-ct2":
            src = hf_download(item["repo"], work / "src", token)
            convert_ct2(src, stage / "model", item.get("quant", "float16"))
            m = {**base, "type": "asr-ct2", "languages": item["languages"], "preferred_for": item.get("preferred_for", []),
                 "model_dir": "model", "source": f"https://huggingface.co/{item['repo']}"}
        elif k == "zip-ct2":
            z = download(item["url"], work / "src.zip")
            say("  unpacking…")
            with zipfile.ZipFile(z) as zf:
                zf.extractall(work / "src")
            z.unlink()
            convert_ct2(find_model_dir(work / "src"), stage / "model", "float16")
            m = {**base, "type": "asr-ct2", "languages": item["languages"], "preferred_for": item.get("preferred_for", []),
                 "model_dir": "model", "source": "https://github.com/AI4Bharat/vistaar"}
        elif k == "diarization":
            t = download(item["seg_url"], work / "seg.tar.bz2")
            with tarfile.open(t) as tf:
                tf.extractall(work / "seg", filter="data")
            seg = next((work / "seg").rglob("model.onnx"))
            shutil.copy2(seg, stage / "segmentation.onnx")
            download(item["emb_url"], stage / "embedding.onnx")
            m = {**base, "type": "diarization", "segmentation": "segmentation.onnx", "embedding": "embedding.onnx",
                 "threshold": 0.5, "source": "https://github.com/k2-fsa/sherpa-onnx"}
        elif k == "hf-raw":
            hf_download(item["repo"], stage / "model", token)
            shutil.rmtree(stage / "model" / ".cache", ignore_errors=True)
            m = {**base, "type": item["type"], "direction": item.get("direction"), "model_dir": "model",
                 "trust_remote_code": True, "source": f"https://huggingface.co/{item['repo']}"}
        elif k == "gpu":
            (stage / "bin").mkdir()
            for pkg in item["wheels"]:
                meta = json.loads(urllib.request.urlopen(f"https://pypi.org/pypi/{pkg}/json", timeout=60).read())
                # newest release that actually ships a Windows wheel (some releases are Linux-only)
                files = []
                from packaging.version import InvalidVersion, Version

                def _v(x):
                    try:
                        return Version(x)
                    except InvalidVersion:
                        return Version("0")
                for ver in sorted(meta.get("releases", {}), key=_v, reverse=True):
                    if _v(ver).is_prerelease:
                        continue
                    files = [f for f in meta["releases"][ver] if f["filename"].endswith("win_amd64.whl") and not f.get("yanked")]
                    if files:
                        say(f"  {pkg} {ver}")
                        break
                if not files:
                    raise SystemExit(f"No Windows wheel for {pkg}")
                whl = download(files[0]["url"], work / files[0]["filename"])
                with zipfile.ZipFile(whl) as zf:
                    for n in zf.namelist():
                        if n.lower().endswith(".dll"):
                            with zf.open(n) as s, open(stage / "bin" / Path(n).name, "wb") as d:
                                shutil.copyfileobj(s, d)
                whl.unlink()
            m = {**base, "type": "gpu-runtime", "dll_dir": "bin", "languages": [], "source": "https://pypi.org/project/nvidia-cudnn-cu12/"}
        elif k == "custom":
            src = hf_download(item["repo"], work / "src", token)
            if item["engine"] == "ct2":
                convert_ct2(src, stage / "model", "float16")
                m = {**base, "type": "asr-ct2", "model_dir": "model"}
            else:
                shutil.copytree(src, stage / "model", ignore=shutil.ignore_patterns(".cache"))
                m = {**base, "type": "asr-hf", "model_dir": "model", "trust_remote_code": False}
            m.update({"languages": item["languages"], "preferred_for": item["languages"] if item["languages"] != ["*"] else [],
                      "source": f"https://huggingface.co/{item['repo']}"})
        else:
            raise SystemExit(f"Unknown pack kind {k}")
        return write_pack(stage, m, out_dir)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def custom_item():
    repo = input("Hugging Face model id (e.g. someone/whisper-small-assamese): ").strip()
    eng = input("Engine: [1] Whisper-type model, convert to CTranslate2 (fast)   [2] other model, run with transformers: ").strip()
    langs = input("Language codes it is for, comma-separated (e.g. as) or * for many: ").strip() or "*"
    pid = "custom-" + repo.split("/")[-1].lower().replace("_", "-")
    return {"id": pid, "name": f"Custom: {repo}", "kind": "custom", "repo": repo, "engine": "ct2" if eng != "2" else "hf",
            "languages": [x.strip() for x in langs.split(",") if x.strip()], "license": "see model card", "size": "varies"}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("packs", nargs="*", help="numbers or ids from the list (blank = ask)")
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    ap.add_argument("--token", default=os.environ.get("HF_TOKEN"))
    ap.add_argument("--json-progress", action="store_true", help="print JSON lines (used by the app)")
    ap.add_argument("--custom-repo", help="Hugging Face model id for a custom speech pack")
    ap.add_argument("--custom-engine", choices=["ct2", "hf"], default="ct2")
    ap.add_argument("--custom-langs", default="*")
    ap.add_argument("--list", action="store_true", help="print the catalogue as JSON and exit")
    a = ap.parse_args()
    global JSON_PROGRESS
    JSON_PROGRESS = a.json_progress
    interactive = not (a.packs or a.custom_repo or a.json_progress)
    if a.list:
        print(json.dumps(CATALOG, ensure_ascii=False))
        return 0
    for k in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
        os.environ.pop(k, None)
    if interactive:
        say("VU3INI Transcribe Studio — Make model packs\n")
        for i, it in enumerate(CATALOG, 1):
            say(f"  {i:2d}. {it['name']}  [{it['size']}]")
        say("   C. Custom Hugging Face speech model (e.g. a community Assamese fine-tune)\n")
    picks = a.packs if not interactive else input("Type the numbers to build, separated by spaces (e.g. 1 6 7 10): ").split()
    items = []
    if a.custom_repo:
        repo = a.custom_repo.strip()
        items.append({"id": "custom-" + repo.split("/")[-1].lower().replace("_", "-"), "name": f"Custom: {repo}",
                      "kind": "custom", "repo": repo, "engine": a.custom_engine,
                      "languages": [x.strip() for x in a.custom_langs.split(",") if x.strip()] or ["*"],
                      "license": "see model card", "size": "varies"})
    for p in picks:
        if p.lower() == "c":
            items.append(custom_item())
        elif p.isdigit() and 1 <= int(p) <= len(CATALOG):
            items.append(CATALOG[int(p) - 1])
        else:
            items += [c for c in CATALOG if c["id"] == p]
    if not items:
        say("Nothing selected.")
        return 1
    token = a.token
    if not token and interactive and any(it["kind"] in ("hf-raw",) for it in items):
        token = getpass.getpass("Hugging Face access token for gated models (press Enter to skip): ").strip() or None
    made = []
    for i, it in enumerate(items):
        report(pack=it["id"], name=it["name"], index=i, total=len(items))
        try:
            dst = build(it, a.out, token)
            made.append(dst)
            report(done=it["id"], file=str(dst))
        except SystemExit as e:
            say(f"  SKIPPED: {e}")
            report(failed=it["id"], error=str(e))
        except Exception as e:  # noqa: BLE001
            say(f"  FAILED: {e}")
            report(failed=it["id"], error=str(e))
    if a.json_progress:
        return 0 if made else 1
    say("\nFinished. Packs created:")
    for m in made:
        say("  " + str(m))
    say(f"\nInstall them in the app: Model packs -> Install pack from file. Folder: {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
