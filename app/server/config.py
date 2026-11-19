"""Paths, version and persistent settings for VU3INI Transcribe Studio."""
import json
import os
import sys
import threading
from pathlib import Path

APP_NAME = "VU3INI Transcribe Studio"
AUTHOR = "Sasanka Boruah -VU3INI"
EMAIL = "hamvu3ini@gmail.com"

# app/ folder (contains server/, web/, launcher/)
APP_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = APP_DIR.parent  # install root: python/, ffmpeg/, app/, VERSION
WEB_DIR = APP_DIR / "web"


def _read_version() -> str:
    for p in (ROOT_DIR / "VERSION", APP_DIR / "VERSION"):
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
    return "0.0.0-dev"


VERSION = _read_version()


def _data_dir() -> Path:
    env = os.environ.get("VTS_DATA_DIR")
    if env:
        return Path(env)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME
    return Path.home() / ".local" / "share" / "vu3ini-transcribe-studio"


DATA_DIR = _data_dir()
PROJECTS_DIR = DATA_DIR / "projects"
PACKS_DIR = Path(os.environ.get("VTS_PACKS_DIR") or (DATA_DIR / "packs"))
TMP_DIR = DATA_DIR / "tmp"
LOG_DIR = DATA_DIR / "logs"
SETTINGS_FILE = DATA_DIR / "settings.json"
for _d in (DATA_DIR, PROJECTS_DIR, PACKS_DIR, TMP_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)

DEFAULT_SETTINGS = {
    "device": "auto",            # auto | cpu | cuda
    "compute_type": "auto",      # auto | int8 | float16 | int8_float16 | float32
    "default_engine": "auto",    # auto (route by language) or a pack id
    "default_language": "auto",
    "beam_size": 5,
    "vad_filter": True,
    "word_timestamps": True,
    "custom_vocabulary": [],     # words/phrases fed to the model as an initial prompt
    "replacements": [],          # [{"from": "...", "to": "..."}] applied after transcription
    "hallucination_guard": True,
    "code_switching": True,      # per-segment language detection for mixed-language speech
    "denoise": False,
    "normalize": True,
    "trim_silence": False,
    "max_speakers": 0,           # 0 = automatic
    "diarize_default": False,
    "translation_target": "eng_Latn",
    "cpu_threads": 0,
    "language_engines": {},      # {"as": "<pack id>", ...}; missing or "auto" = best installed pack
}

_lock = threading.Lock()


def load_settings() -> dict:
    s = dict(DEFAULT_SETTINGS)
    try:
        s.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    except Exception:
        pass
    return s


def save_settings(new: dict) -> dict:
    with _lock:
        s = load_settings()
        for k, v in new.items():
            if k in DEFAULT_SETTINGS:
                s[k] = v
        SETTINGS_FILE.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")
        return s


def find_tool(name: str) -> str:
    """Locate a bundled binary (ffmpeg/ffprobe), falling back to PATH."""
    exe = name + (".exe" if sys.platform == "win32" else "")
    for cand in (ROOT_DIR / "ffmpeg" / exe, ROOT_DIR / "ffmpeg" / "bin" / exe, ROOT_DIR / "bin" / exe):
        if cand.exists():
            return str(cand)
    return name
