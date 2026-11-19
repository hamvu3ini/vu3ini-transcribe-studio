"""Audio/video helpers built on the bundled FFmpeg."""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

from .config import find_tool

SR = 16000
_NOWIN = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW


def _run(args, **kw):
    return subprocess.run(args, capture_output=True, creationflags=_NOWIN, **kw)


def probe(path: Path) -> dict:
    r = _run([find_tool("ffprobe"), "-v", "error", "-show_entries", "format=duration:stream=codec_type",
              "-of", "json", str(path)])
    info = {"duration": 0.0, "has_video": False, "has_audio": False}
    try:
        j = json.loads(r.stdout or b"{}")
        info["duration"] = float(j.get("format", {}).get("duration") or 0)
        kinds = {s.get("codec_type") for s in j.get("streams", [])}
        info["has_video"] = "video" in kinds
        info["has_audio"] = "audio" in kinds
    except Exception:
        pass
    return info


def filter_chain(denoise=False, normalize=True, trim_silence=False) -> str:
    f = []
    if denoise:
        f += ["highpass=f=80", "afftdn=nf=-25"]
    if trim_silence:
        f.append("silenceremove=start_periods=1:start_threshold=-45dB:stop_periods=-1:stop_duration=1.2:stop_threshold=-45dB")
    if normalize:
        f.append("dynaudnorm=f=250:g=15")
    return ",".join(f)


def decode(path: Path, denoise=False, normalize=True, trim_silence=False) -> np.ndarray:
    """Decode any audio/video file to mono 16 kHz float32."""
    args = [find_tool("ffmpeg"), "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(path), "-vn"]
    chain = filter_chain(denoise, normalize, trim_silence)
    if chain:
        args += ["-af", chain]
    args += ["-f", "s16le", "-ac", "1", "-ar", str(SR), "-"]
    r = _run(args)
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError("FFmpeg could not read this file: " + r.stderr.decode(errors="replace")[-400:])
    return np.frombuffer(r.stdout, np.int16).astype(np.float32) / 32768.0


def make_playback(src: Path, dst: Path) -> Path:
    """Create a browser-friendly AAC copy used by the editor's player."""
    r = _run([find_tool("ffmpeg"), "-nostdin", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
              "-vn", "-ac", "1", "-ar", "44100", "-c:a", "aac", "-b:a", "96k", str(dst)])
    if r.returncode != 0:
        raise RuntimeError("FFmpeg could not create the playback copy: " + r.stderr.decode(errors="replace")[-300:])
    return dst


def write_wav(samples: np.ndarray, dst: Path):
    import soundfile as sf
    sf.write(str(dst), samples, SR, subtype="PCM_16")


def peaks(samples: np.ndarray, buckets: int = 4000) -> list:
    """Min/max pairs for drawing the waveform."""
    if samples.size == 0:
        return []
    n = max(1, samples.size // buckets)
    usable = samples[: (samples.size // n) * n].reshape(-1, n)
    mx = usable.max(axis=1)
    mn = usable.min(axis=1)
    out = np.empty(mx.size * 2, np.float32)
    out[0::2] = mn
    out[1::2] = mx
    return [round(float(x), 3) for x in out]


def video_size(path: Path) -> tuple[int, int]:
    r = _run([find_tool("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
              "-of", "json", str(path)])
    try:
        st = json.loads(r.stdout)["streams"][0]
        return int(st["width"]), int(st["height"])
    except Exception:
        return 1280, 720


def burn_subtitles(video: Path, cues: list, dst: Path, workdir: Path) -> Path:
    """Overlay pre-rendered subtitle images (PNG with transparency) onto a video.

    cues: [(start, end, png_path)]. The images are rendered by the browser, whose text shaping
    handles Assamese, Bengali and Devanagari conjuncts correctly. They are joined into one
    transparent overlay stream with FFmpeg's concat demuxer, so any number of cues is one input.
    """
    from PIL import Image
    workdir.mkdir(parents=True, exist_ok=True)
    cues = sorted(cues, key=lambda c: c[0])
    if cues:
        w, h = Image.open(cues[0][2]).size
    else:
        w, h = 16, 16
    blank = workdir / "blank.png"
    Image.new("RGBA", (w, h), (0, 0, 0, 0)).save(blank)
    lines, t = ["ffconcat version 1.0"], 0.0
    for s, e, png in cues:
        s, e = max(s, t), max(e, s)
        if s - t > 0.001:
            lines += [f"file '{blank.name}'", f"duration {s - t:.3f}"]
        if e - s > 0.001:
            lines += [f"file '{Path(png).name}'", f"duration {e - s:.3f}"]
        t = e
    lines += [f"file '{blank.name}'", "duration 1.0", f"file '{blank.name}'"]
    (workdir / "cues.ffconcat").write_text("\n".join(lines) + "\n", encoding="utf-8")
    err = b""
    for venc in (["-c:v", "libopenh264", "-b:v", "5M"], ["-c:v", "libx264", "-crf", "20"], ["-c:v", "mpeg4", "-q:v", "3"]):
        r = _run([find_tool("ffmpeg"), "-nostdin", "-y", "-hide_banner", "-loglevel", "error", "-i", str(video),
                  "-f", "concat", "-safe", "0", "-i", "cues.ffconcat",
                  "-filter_complex", "[1:v]format=rgba[s];[0:v][s]overlay=x=(W-w)/2:y=H-h:format=auto:eof_action=pass[v]",
                  "-map", "[v]", "-map", "0:a?", *venc, "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                  str(dst)], cwd=str(workdir))
        if r.returncode == 0:
            return dst
        err = r.stderr
    raise RuntimeError("FFmpeg could not burn subtitles: " + err.decode(errors="replace")[-400:])
