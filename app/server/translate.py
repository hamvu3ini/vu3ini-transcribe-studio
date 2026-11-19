"""Translation with AI4Bharat IndicTrans2 (Hugging Face checkpoints, run on CPU with transformers).

Pre/post-processing follows IndicTrans2's own recipe (IndicTransToolkit is not on PyPI):
Indic normalisation, script unification to Devanagari for the model input, language tags
"src_lang tgt_lang", and transliteration back to the target script afterwards.
"""
import threading
from pathlib import Path

from . import packs

FLORES = {"as": "asm_Beng", "bn": "ben_Beng", "hi": "hin_Deva", "en": "eng_Latn", "mr": "mar_Deva",
          "ne": "npi_Deva", "gu": "guj_Gujr", "pa": "pan_Guru", "or": "ory_Orya", "ta": "tam_Taml",
          "te": "tel_Telu", "kn": "kan_Knda", "ml": "mal_Mlym", "ur": "urd_Arab", "sa": "san_Deva"}
ISO = {v: k for k, v in FLORES.items()}
# languages whose script is unified to Devanagari for the model
UNIFY = {"asm_Beng", "ben_Beng", "guj_Gujr", "pan_Guru", "ory_Orya", "tam_Taml", "tel_Telu", "kan_Knda", "mal_Mlym"}
XLIT = {"asm_Beng": "as", "ben_Beng": "bn", "guj_Gujr": "gu", "pan_Guru": "pa", "ory_Orya": "or",
        "tam_Taml": "ta", "tel_Telu": "te", "kan_Knda": "kn", "mal_Mlym": "ml"}

_lock = threading.Lock()
_loaded = {}


def to_flores(code: str) -> str:
    return FLORES.get(code, code)


def _direction(src: str, tgt: str) -> str:
    if src == "eng_Latn":
        return "en-indic"
    if tgt == "eng_Latn":
        return "indic-en"
    return "indic-indic"


def pack_for(src: str, tgt: str) -> dict | None:
    d = _direction(src, tgt)
    for p in packs.by_type("translation"):
        if p.get("direction") == d:
            return p
    return None


def available_directions() -> list:
    return sorted({p.get("direction") for p in packs.by_type("translation")})


def _pre(text: str, src: str) -> str:
    if src == "eng_Latn":
        return " ".join(text.split())
    from indicnlp.normalize.indic_normalize import IndicNormalizerFactory
    from indicnlp.transliterate.unicode_transliterate import UnicodeIndicTransliterator
    iso = XLIT.get(src) or ISO.get(src, "hi")
    try:
        text = IndicNormalizerFactory().get_normalizer(iso).normalize(text)
    except Exception:
        pass
    if src in UNIFY:
        text = UnicodeIndicTransliterator.transliterate(text, iso, "hi")
    return " ".join(text.split())


def _post(text: str, tgt: str) -> str:
    if tgt in UNIFY:
        from indicnlp.transliterate.unicode_transliterate import UnicodeIndicTransliterator
        text = UnicodeIndicTransliterator.transliterate(text, "hi", XLIT[tgt])
    return text.strip()


def _load(p: dict):
    with _lock:
        if p["id"] not in _loaded:
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
            d = str(Path(p["path"]) / p.get("model_dir", "model"))
            tok = AutoTokenizer.from_pretrained(d, trust_remote_code=True)
            model = AutoModelForSeq2SeqLM.from_pretrained(d, trust_remote_code=True)
            model.eval()
            _loaded.clear()
            _loaded[p["id"]] = (tok, model)
        return _loaded[p["id"]]


def translate(texts: list, src: str, tgt: str, progress=None, cancel=None, batch=8) -> list:
    src, tgt = to_flores(src), to_flores(tgt)
    if src == tgt:
        return list(texts)
    p = pack_for(src, tgt)
    if not p:
        raise RuntimeError(f"No IndicTrans2 pack installed for {_direction(src, tgt)} translation. "
                           "Install it from Model packs.")
    import torch
    tok, model = _load(p)
    out = []
    for i in range(0, len(texts), batch):
        if cancel and cancel.is_set():
            raise RuntimeError("Cancelled")
        chunk = [f"{src} {tgt} {_pre(t, src)}" for t in texts[i:i + batch]]
        enc = tok(chunk, truncation=True, padding="longest", return_tensors="pt", return_attention_mask=True)
        with torch.inference_mode():
            gen = model.generate(**enc, use_cache=True, min_length=0, max_length=256, num_beams=4, num_return_sequences=1)
        if hasattr(tok, "as_target_tokenizer"):
            with tok.as_target_tokenizer():
                dec = tok.batch_decode(gen.detach().cpu().tolist(), skip_special_tokens=True, clean_up_tokenization_spaces=True)
        else:
            dec = tok.batch_decode(gen, skip_special_tokens=True, clean_up_tokenization_spaces=True)
        out += [_post(d, tgt) for d in dec]
        if progress:
            progress(min(1.0, (i + batch) / max(len(texts), 1)))
    return out
