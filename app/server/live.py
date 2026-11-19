"""Live microphone transcription over a WebSocket.

The browser sends 16 kHz mono Int16 PCM frames. The server cuts the stream into
utterances with Silero VAD (bundled with faster-whisper), sends quick partial
results while someone is speaking and a final, word-timed result per utterance.
On stop, the recording and transcript are saved as a normal project.
"""
import asyncio
import json
import time

import numpy as np
from fastapi import WebSocket, WebSocketDisconnect

from . import audio, engines, store
from .audio import SR
from .config import TMP_DIR, load_settings


def _speech_regions(x: np.ndarray):
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    return get_speech_timestamps(x, VadOptions(min_silence_duration_ms=500, speech_pad_ms=150))


async def handle(ws: WebSocket):
    await ws.accept()
    loop = asyncio.get_running_loop()
    settings = load_settings()
    lang, engine = None, "auto"
    pack_id = None
    buf = np.zeros(0, np.float32)       # current, not yet finalised audio
    whole = []                          # every frame, for saving the recording
    offset = 0.0                        # seconds of audio already finalised
    segments = []
    last_partial = 0.0
    name = "Live recording " + time.strftime("%Y-%m-%d %H:%M")

    def run(samples, final):
        nonlocal lang, pack_id
        s = dict(settings)
        if not final:
            s.update(beam_size=1, word_timestamps=False)
        segs, out_lang, eng, _dev, notes = engines.transcribe(samples, s, language=lang or "auto",
                                                              engine=pack_id or engine)
        if lang is None and out_lang:
            lang = out_lang
        if pack_id is None:
            p = engines.choose_pack(lang, engine, [], settings)
            pack_id = p["id"]
        return segs

    async def finalise(upto: int):
        nonlocal buf, offset
        chunk, buf = buf[:upto], buf[upto:]
        start = offset
        offset += len(chunk) / SR
        if len(chunk) < SR * 0.3:
            return
        segs = await loop.run_in_executor(None, run, chunk, True)
        for sg in segs:
            sg["start"] = round(sg["start"] + start, 3)
            sg["end"] = round(sg["end"] + start, 3)
            for w in sg.get("words") or []:
                w["s"] = round(w["s"] + start, 3)
                w["e"] = round(w["e"] + start, 3)
            sg["id"] = len(segments)
            segments.append(sg)
            await ws.send_text(json.dumps({"type": "final", "segment": sg}, ensure_ascii=False))

    task = None
    since_check = 0

    async def process():
        try:
            await _process()
        except Exception as e:  # noqa: BLE001
            await ws.send_text(json.dumps({"type": "error", "message": str(e)}))

    async def _process():
        nonlocal buf, offset, last_partial
        dur = len(buf) / SR
        if dur < 1.0:
            return
        regions = await loop.run_in_executor(None, _speech_regions, buf.copy())
        if regions:
            tail_silence = dur - regions[-1]["end"] / SR
            if tail_silence > 0.6 or dur > 20:
                await finalise(regions[-1]["end"] + int(0.15 * SR) if dur <= 20 else int(dur * SR))
            elif time.time() - last_partial > 1.5:
                last_partial = time.time()
                segs = await loop.run_in_executor(None, run, buf.copy(), False)
                text = " ".join(s["text"] for s in segs)
                await ws.send_text(json.dumps({"type": "partial", "text": text}, ensure_ascii=False))
        elif dur > 8:
            # long silence: drop it from the working buffer
            drop = len(buf) - SR
            offset += drop / SR
            buf = buf[drop:]

    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("text"):
                data = json.loads(msg["text"])
                if data.get("type") == "start":
                    lang = None if data.get("language") in (None, "", "auto") else data["language"]
                    engine = data.get("engine") or "auto"
                    if data.get("name"):
                        name = data["name"]
                    if not engines.asr_packs():
                        await ws.send_text(json.dumps({"type": "error", "message": "No speech model installed. Install a pack first."}))
                    else:
                        await ws.send_text(json.dumps({"type": "ready"}))
                elif data.get("type") == "stop":
                    if task is not None:
                        await task
                    if len(buf):
                        await finalise(len(buf))
                    pid = None
                    if whole:
                        rec = np.concatenate(whole)
                        wav = TMP_DIR / f"live-{int(time.time())}.wav"
                        audio.write_wav(rec, wav)
                        p = store.create(name, wav, status="done", segments=segments, language=lang,
                                         engine="Live", duration=round(len(rec) / SR, 2), tags=["live"])
                        pid = p["id"]
                        try:
                            audio.make_playback(store.path(pid, p["media"]), store.path(pid, "playback.m4a"))
                            (store.path(pid, "peaks.json")).write_text(json.dumps(audio.peaks(rec)))
                        except Exception:
                            pass
                    await ws.send_text(json.dumps({"type": "saved", "project_id": pid}))
                    break
                continue
            raw = msg.get("bytes")
            if not raw:
                continue
            frame = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
            whole.append(frame)
            buf = np.concatenate([buf, frame])
            since_check += len(frame)
            # analyse at most twice a second, in the background, so receiving never stalls
            if (task is None or task.done()) and since_check >= SR // 2:
                since_check = 0
                task = asyncio.create_task(process())
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        try:
            await ws.send_text(json.dumps({"type": "error", "message": str(e)}))
        except Exception:
            pass


