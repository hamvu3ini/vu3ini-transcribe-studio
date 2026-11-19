"""Speech recognition engines.

* asr-ct2: Whisper and AI4Bharat IndicWhisper checkpoints converted to CTranslate2,
  run with faster-whisper (CPU int8 or NVIDIA GPU float16).
* asr-hf: any Hugging Face speech-recognition model (Whisper fine-tunes, wav2vec2/CTC
  Indic models) run through transformers on CPU.

Engines are chosen per job: an explicit pack, or automatic routing by language.
"""
import logging
import re
import threading
from pathlib import Path

import numpy as np

from . import packs
from .audio import SR

log = logging.getLogger("vts.engines")

LANG_NAMES = {"as": "Assamese", "hi": "Hindi", "bn": "Bengali", "en": "English"}

HALLUCINATIONS = [
    r"thank(s| you) for watching", r"please subscribe", r"subtitles? by", r"amara\.org", r"like and subscribe",
    r"^\s*\.+\s*$", r"^\s*♪+\s*$", r"transcribed by", r"copyright",
]


class Cancelled(Exception):
    pass


class _ModelCache:
    def __init__(self):
        self.lock = threading.RLock()
        self.key = None
        self.model = None
        self.device = None

    def clear(self):
        with self.lock:
            self.key = self.model = self.device = None
            import gc
            gc.collect()


_cache = _ModelCache()
_hf_cache = _ModelCache()


def cuda_available() -> bool:
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def resolve_device(settings: dict) -> tuple[str, str]:
    dev = settings.get("device", "auto")
    if dev == "auto":
        dev = "cuda" if cuda_available() else "cpu"
    if dev == "cuda" and not cuda_available():
        dev = "cpu"
    ct = settings.get("compute_type", "auto")
    if ct == "auto":
        ct = "float16" if dev == "cuda" else "int8"
    if dev == "cpu" and ct in ("float16", "int8_float16"):
        ct = "int8"
    return dev, ct


def _model_dir(pack: dict) -> str:
    return str(Path(pack["path"]) / pack.get("model_dir", "model"))


def _load_ct2(pack: dict, settings: dict, notes: list, force_cpu=False):
    from faster_whisper import WhisperModel
    dev, ct = resolve_device(settings)
    if force_cpu:
        dev, ct = "cpu", "int8"
    key = (pack["id"], dev, ct)
    with _cache.lock:
        if _cache.key == key:
            return _cache.model, dev
        _cache.clear()
        threads = int(settings.get("cpu_threads") or 0)
        try:
            m = WhisperModel(_model_dir(pack), device=dev, compute_type=ct, cpu_threads=threads)
        except Exception as e:
            if dev == "cuda":
                notes.append(f"GPU load failed ({str(e)[:120]}); using CPU instead.")
                dev, ct = "cpu", "int8"
                key = (pack["id"], dev, ct)
                m = WhisperModel(_model_dir(pack), device=dev, compute_type=ct, cpu_threads=threads)
            else:
                raise
        _cache.key, _cache.model, _cache.device = key, m, dev
        return m, dev


def asr_packs() -> list:
    return [p for p in packs.list_packs() if p["type"] in ("asr-ct2", "asr-hf")]


def _is_multilingual(p: dict) -> bool:
    return "*" in (p.get("languages") or []) or bool(p.get("multilingual"))


def detector_pack() -> dict | None:
    cands = [p for p in asr_packs() if p["type"] == "asr-ct2" and _is_multilingual(p)]
    return cands[0] if cands else None


def detect_language(samples: np.ndarray, settings: dict, notes: list) -> tuple[str | None, float]:
    p = detector_pack()
    if not p:
        return None, 0.0
    m, _ = _load_ct2(p, settings, notes)
    if not m.model.is_multilingual:
        return None, 0.0
    clip = samples[: SR * 30]
    try:
        lang, prob, _ = m.detect_language(clip)
    except Exception as e:  # noqa: BLE001
        notes.append(f"Language detection failed ({e}); using the engine's default.")
        return None, 0.0
    return lang, float(prob)


def choose_pack(language: str | None, engine: str, notes: list, settings: dict | None = None) -> dict:
    all_packs = asr_packs()
    if not all_packs:
        raise RuntimeError("No speech recognition model is installed. Open Model packs and install one "
                           "(for example the Whisper large-v3-turbo pack).")
    if engine and engine != "auto":
        p = packs.get(engine)
        if not p:
            raise RuntimeError(f"The selected engine pack '{engine}' is not installed.")
        return p
    chosen = ((settings or {}).get("language_engines") or {}).get(language or "")
    if language and chosen and chosen != "auto":
        p = next((x for x in all_packs if x["id"] == chosen), None)
        if p:
            notes.append(f"Using {p['name']} for {LANG_NAMES.get(language, language)} (your choice in Model packs).")
            return p
        notes.append(f"The pack chosen for {LANG_NAMES.get(language, language)} is no longer installed; choosing automatically.")
    if language:
        pref = [p for p in all_packs if language in (p.get("preferred_for") or [])]
        if pref:
            notes.append(f"Routed {LANG_NAMES.get(language, language)} to {pref[0]['name']}.")
            return pref[0]
        specific = [p for p in all_packs if language in (p.get("languages") or [])]
        if specific:
            return specific[0]
    multi = [p for p in all_packs if _is_multilingual(p)]
    if multi:
        return multi[0]
    if language:
        notes.append(f"No pack lists {language}; using {all_packs[0]['name']}.")
    return all_packs[0]


def _is_hallucination(text: str) -> bool:
    t = text.strip().lower()
    if not t:
        return True
    if any(re.search(p, t) for p in HALLUCINATIONS):
        return True
    words = t.split()
    if len(words) >= 8:
        # the same short n-gram repeated over and over
        for n in (1, 2, 3):
            grams = [" ".join(words[i:i + n]) for i in range(0, len(words) - n + 1, n)]
            if grams and max(grams.count(g) for g in set(grams)) / len(grams) > 0.6:
                return True
    return False


def _apply_replacements(text: str, reps: list) -> str:
    for r in reps or []:
        src, dst = (r.get("from") or "").strip(), r.get("to") or ""
        if src:
            text = re.sub(r"(?<!\w)" + re.escape(src) + r"(?!\w)", dst, text, flags=re.IGNORECASE)
    return text


def postprocess(segments: list, settings: dict, notes: list) -> list:
    out, prev = [], None
    dropped = 0
    for s in segments:
        if settings.get("hallucination_guard", True):
            if _is_hallucination(s["text"]) or (prev and s["text"].strip() == prev):
                dropped += 1
                continue
        prev = s["text"].strip()
        s["text"] = _apply_replacements(s["text"], settings.get("replacements"))
        for w in s.get("words") or []:
            w["w"] = _apply_replacements(w["w"], settings.get("replacements"))
        out.append(s)
    if dropped:
        notes.append(f"Hallucination guard removed {dropped} segment(s).")
    for i, s in enumerate(out):
        s["id"] = i
    return out


def _transcribe_ct2(samples, pack, language, settings, progress, cancel, notes, force_cpu=False):
    model, dev = _load_ct2(pack, settings, notes, force_cpu=force_cpu)
    vocab = [v.strip() for v in settings.get("custom_vocabulary") or [] if v.strip()]
    guard = settings.get("hallucination_guard", True)
    wts = bool(settings.get("word_timestamps", True))
    kwargs = dict(
        language=language, beam_size=int(settings.get("beam_size") or 5),
        vad_filter=bool(settings.get("vad_filter", True)), word_timestamps=wts,
        condition_on_previous_text=not guard,
        initial_prompt=(", ".join(vocab) if vocab else None),
        hotwords=(" ".join(vocab) if vocab else None),
    )
    if guard and wts:
        kwargs["hallucination_silence_threshold"] = 2.0
    if language is None and settings.get("code_switching", True) and _is_multilingual(pack):
        kwargs["multilingual"] = True
    duration = max(len(samples) / SR, 0.01)
    try:
        seg_iter, info = model.transcribe(samples, **kwargs)
        segs = []
        for s in seg_iter:
            if cancel and cancel.is_set():
                raise Cancelled()
            words = [{"w": w.word, "s": round(w.start, 3), "e": round(w.end, 3), "p": round(w.probability, 3)}
                     for w in (s.words or [])]
            conf = (float(np.mean([w["p"] for w in words])) if words else float(np.exp(s.avg_logprob)))
            segs.append({"start": round(s.start, 3), "end": round(s.end, 3), "text": s.text.strip(),
                         "words": words, "conf": round(conf, 3), "speaker": None})
            if progress:
                progress(min(s.end / duration, 0.99))
        return segs, info.language, dev
    except Cancelled:
        raise
    except Exception as e:
        msg = str(e).lower()
        if dev == "cuda" and ("out of memory" in msg or "cuda" in msg or "cublas" in msg or "cudnn" in msg):
            notes.append("GPU ran out of memory or failed; finished on CPU.")
            _cache.clear()
            return _transcribe_ct2(samples, pack, language, settings, progress, cancel, notes, force_cpu=True)
        raise


def _transcribe_hf(samples, pack, language, settings, progress, cancel, notes):
    try:
        import torch  # noqa: F401
        from transformers import pipeline
    except ImportError as e:
        raise RuntimeError(f"The Hugging Face engine needs PyTorch and transformers, which are missing: {e}")
    with _hf_cache.lock:
        if _hf_cache.key != pack["id"]:
            _hf_cache.clear()
            _hf_cache.model = pipeline("automatic-speech-recognition", model=_model_dir(pack),
                                       device="cpu", trust_remote_code=bool(pack.get("trust_remote_code")))
            _hf_cache.key = pack["id"]
        pipe = _hf_cache.model
    gen = {}
    if language and getattr(pipe.model.config, "model_type", "") == "whisper":
        gen = {"generate_kwargs": {"language": language, "task": "transcribe"}}
    if progress:
        progress(0.1)
    res = pipe({"raw": samples, "sampling_rate": SR}, chunk_length_s=30, batch_size=4,
               return_timestamps="word", **gen)
    if cancel and cancel.is_set():
        raise Cancelled()
    words = [{"w": " " + c["text"].strip(), "s": round(float(c["timestamp"][0] or 0), 3),
              "e": round(float(c["timestamp"][1] or c["timestamp"][0] or 0), 3), "p": 1.0}
             for c in res.get("chunks") or [] if c["text"].strip()]
    segs = group_words(words) if words else [{"start": 0, "end": len(samples) / SR, "text": res.get("text", "").strip(),
                                               "words": [], "conf": 1.0, "speaker": None}]
    return segs, language, "cpu"


def group_words(words: list, max_len=12.0, gap=0.8) -> list:
    segs, cur = [], []
    for w in words:
        if cur and (w["s"] - cur[-1]["e"] > gap or w["e"] - cur[0]["s"] > max_len
                    or cur[-1]["w"].strip().endswith((".", "?", "!", "।", "॥"))):
            segs.append(cur)
            cur = []
        cur.append(w)
    if cur:
        segs.append(cur)
    return [{"start": c[0]["s"], "end": c[-1]["e"], "text": "".join(x["w"] for x in c).strip(), "words": c,
             "conf": round(float(np.mean([x["p"] for x in c])), 3), "speaker": None} for c in segs]


def transcribe(samples: np.ndarray, settings: dict, language=None, engine="auto", progress=None, cancel=None):
    """Returns (segments, language, engine_name, device, notes)."""
    notes = []
    lang = None if language in (None, "", "auto") else language
    if lang is None and (engine in (None, "", "auto")):
        det, prob = detect_language(samples, settings, notes)
        if det:
            notes.append(f"Detected language: {LANG_NAMES.get(det, det)} ({prob:.0%}).")
            if prob >= 0.5:
                lang = det
    pack = choose_pack(lang, engine or "auto", notes, settings)
    # IndicWhisper / single-language packs: force their language
    langs = [x for x in (pack.get("languages") or []) if x != "*"]
    use_lang = lang if (lang or not langs) else langs[0]
    if lang is None and not _is_multilingual(pack) and langs:
        use_lang = langs[0]
    # keep language=None for code-switching when the user asked for auto
    if language in (None, "", "auto") and _is_multilingual(pack) and settings.get("code_switching", True):
        use_lang = None
    if pack["type"] == "asr-ct2":
        segs, out_lang, dev = _transcribe_ct2(samples, pack, use_lang, settings, progress, cancel, notes)
    else:
        segs, out_lang, dev = _transcribe_hf(samples, pack, use_lang, settings, progress, cancel, notes)
    segs = postprocess(segs, settings, notes)
    return segs, (out_lang or lang or use_lang), pack["name"], dev, notes


def unload_all():
    _cache.clear()
    _hf_cache.clear()
