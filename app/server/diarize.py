"""Speaker diarization with sherpa-onnx (pyannote segmentation + speaker embedding ONNX models)."""
import numpy as np

from . import packs


def available() -> dict | None:
    lst = packs.by_type("diarization")
    return lst[0] if lst else None


def diarize(samples: np.ndarray, num_speakers: int = 0, progress=None, cancel=None) -> list:
    import sherpa_onnx as so
    from pathlib import Path

    p = available()
    if not p:
        raise RuntimeError("Speaker diarization needs the diarization pack. Install it from Model packs.")
    base = Path(p["path"])
    cfg = so.OfflineSpeakerDiarizationConfig(
        segmentation=so.OfflineSpeakerSegmentationModelConfig(
            pyannote=so.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(base / p.get("segmentation", "segmentation.onnx"))),
            num_threads=2),
        embedding=so.SpeakerEmbeddingExtractorConfig(model=str(base / p.get("embedding", "embedding.onnx")), num_threads=2),
        clustering=so.FastClusteringConfig(num_clusters=int(num_speakers) if num_speakers else -1,
                                           threshold=float(p.get("threshold", 0.5))),
        min_duration_on=0.3, min_duration_off=0.5,
    )
    if not cfg.validate():
        raise RuntimeError("The diarization pack's model files are invalid or missing.")
    sd = so.OfflineSpeakerDiarization(cfg)

    def cb(done, total):
        if progress and total:
            progress(done / total)
        return 1 if (cancel and cancel.is_set()) else 0

    res = sd.process(samples.astype(np.float32), callback=cb).sort_by_start_time()
    return [{"start": float(r.start), "end": float(r.end), "speaker": int(r.speaker)} for r in res]


def _speaker_at(turns, s, e):
    best, best_ov = None, 0.0
    for t in turns:
        ov = min(e, t["end"]) - max(s, t["start"])
        if ov > best_ov:
            best, best_ov = t["speaker"], ov
    if best is None and turns:
        mid = (s + e) / 2
        best = min(turns, key=lambda t: min(abs(mid - t["start"]), abs(mid - t["end"])))["speaker"]
    return best


def assign(segments: list, turns: list) -> tuple[list, dict]:
    """Label words with speakers and split segments where the speaker changes."""
    out = []
    for seg in segments:
        words = seg.get("words") or []
        if not words:
            sp = _speaker_at(turns, seg["start"], seg["end"])
            out.append({**seg, "speaker": f"S{sp + 1}" if sp is not None else None})
            continue
        cur, cur_sp = [], None
        for w in words:
            sp = _speaker_at(turns, w["s"], max(w["e"], w["s"] + 0.01))
            if cur and sp != cur_sp:
                out.append(_mk(seg, cur, cur_sp))
                cur = []
            cur.append(w)
            cur_sp = sp
        if cur:
            out.append(_mk(seg, cur, cur_sp))
    for i, s in enumerate(out):
        s["id"] = i
    names = {}
    for s in out:
        if s["speaker"] and s["speaker"] not in names:
            names[s["speaker"]] = f"Speaker {len(names) + 1}"
    return out, names


def _mk(seg, words, sp):
    return {"start": words[0]["s"], "end": words[-1]["e"], "text": "".join(w["w"] for w in words).strip(),
            "words": words, "conf": round(float(np.mean([w["p"] for w in words])), 3),
            "speaker": f"S{sp + 1}" if sp is not None else None}
