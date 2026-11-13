"""Speech-to-text. Tencent Cloud 录音文件识别 (CreateRecTask) with word timestamps + speaker
diarization; deterministic mock (speech regions from the audio envelope) when no credentials.

Normalized output:
{"engine": str, "mock": bool, "sentences": [{"start","end","text","speaker","words":[{"w","start","end"}]}]}
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
from pathlib import Path

from . import config, media

CHUNK_S = 900  # 15 min of 16k mono mp3 @32kbps ~= 3.6 MB  (< 5 MB base64 body limit)


def _cache_key(path: Path) -> str:
    st = path.stat()
    return hashlib.sha1(f"{path.resolve()}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()[:16]


def transcribe(path: str | Path, cache_dir: str | Path, duration: float | None = None) -> dict:
    path = Path(path)
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / f"asr_{_cache_key(path)}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    duration = duration or media.probe(path)["duration"]
    res = _mock(path) if config.mock_asr() else _tencent(path, cache_dir, duration)
    cache.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    return res


def _mock(path: Path) -> dict:
    try:
        env = media.envelope(media.pcm(path))
    except Exception:
        return {"engine": "mock", "mock": True, "sentences": []}
    total = env.size * media.ENV_HOP
    quiet = media.silences(env, min_len=0.5)
    speech, cur = [], 0.0
    for s, e in quiet + [(total, total)]:
        if s - cur > 0.6:
            speech.append((cur, s))
        cur = e
    sents = []
    for i, (s, e) in enumerate(speech[:200], 1):
        n = max(int((e - s) * 4), 2)
        step = (e - s) / n
        sents.append({"start": round(s, 2), "end": round(e, 2), "speaker": 0,
                      "text": f"（演示转写·第{i}段）",
                      "words": [{"w": "嗯" if k == 0 and i % 3 == 0 else "字", "start": round(s + k * step, 2),
                                 "end": round(s + (k + 1) * step, 2)} for k in range(n)]})
    return {"engine": "mock", "mock": True, "sentences": sents}


def _tencent(path: Path, work: Path, duration: float) -> dict:
    from tencentcloud.asr.v20190614 import asr_client, models
    from tencentcloud.common import credential

    client = asr_client.AsrClient(credential.Credential(config.TENCENT_SECRET_ID, config.TENCENT_SECRET_KEY), "")
    sentences: list[dict] = []
    start = 0.0
    while start < duration - 0.05:
        dur = min(CHUNK_S, duration - start)
        mp3 = media.extract_audio(path, work / f"asr_chunk_{int(start)}.mp3", fmt="mp3", start=start, dur=dur)
        data = mp3.read_bytes()
        req = models.CreateRecTaskRequest()
        req.from_json_string(json.dumps({
            "EngineModelType": config.TENCENT_ASR_ENGINE, "ChannelNum": 1, "ResTextFormat": 3,
            "SpeakerDiarization": 1, "SourceType": 1, "Data": base64.b64encode(data).decode(),
            "DataLen": len(data), "SentenceMaxLength": 16,
        }))
        task_id = client.CreateRecTask(req).Data.TaskId
        detail = _poll(client, models, task_id)
        for d in detail:
            s0 = start + (d.get("StartMs") or 0) / 1000
            words = [{"w": w.get("Word", ""), "start": round(s0 + (w.get("OffsetStartMs") or 0) / 1000, 3),
                      "end": round(s0 + (w.get("OffsetEndMs") or 0) / 1000, 3)} for w in d.get("Words") or []]
            sentences.append({"start": round(s0, 3), "end": round(start + (d.get("EndMs") or 0) / 1000, 3),
                              "text": d.get("FinalSentence") or "", "speaker": d.get("SpeakerId", 0),
                              "words": words, "emotion": d.get("EmotionType")})
        mp3.unlink(missing_ok=True)
        start += dur
    return {"engine": f"tencent:{config.TENCENT_ASR_ENGINE}", "mock": False, "sentences": sentences}


def _poll(client, models, task_id: int, timeout: float = 1800) -> list[dict]:
    t0 = time.time()
    while time.time() - t0 < timeout:
        req = models.DescribeTaskStatusRequest()
        req.from_json_string(json.dumps({"TaskId": task_id}))
        data = json.loads(client.DescribeTaskStatus(req).to_json_string())["Data"]
        if data["Status"] == 2:
            return data.get("ResultDetail") or []
        if data["Status"] == 3:
            raise RuntimeError(f"Tencent ASR failed: {data.get('ErrorMsg')}")
        time.sleep(3)
    raise TimeoutError("Tencent ASR timeout")


FILLERS = ("嗯", "啊", "呃", "额", "那个", "就是说", "然后然后")


def speech_ranges(asr: dict, max_gap: float = 0.5, drop_fillers: bool = True) -> list[dict]:
    """Jump-cut candidates: contiguous speech ranges with long pauses and filler words removed."""
    words = []
    for s in asr.get("sentences", []):
        ws = s.get("words") or [{"w": s["text"], "start": s["start"], "end": s["end"]}]
        for w in ws:
            if drop_fillers and w["w"].strip("，。！？,.!? ") in FILLERS:
                continue
            words.append({**w, "speaker": s.get("speaker", 0)})
    out: list[dict] = []
    for w in words:
        if out and w["start"] - out[-1]["end"] <= max_gap:
            out[-1]["end"] = w["end"]
            out[-1]["text"] += w["w"]
        else:
            out.append({"start": w["start"], "end": w["end"], "text": w["w"], "speaker": w["speaker"]})
    return [r | {"start": round(max(r["start"] - 0.08, 0), 2), "end": round(r["end"] + 0.12, 2)}
            for r in out if r["end"] - r["start"] >= 0.35]
