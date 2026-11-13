"""Footage understanding: one analyst per clip (run in parallel), then multi-cam grouping/sync."""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np

from . import asr, llm, media, store

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".mts", ".3gp", ".webm"}
SLATE_RE = re.compile(r"[sS]\s*0*(\d{1,3})[^\d]{0,4}第?\s*(\d{1,2})\s*条")

TAG_EXAMPLE = {
    "camera": "pov",
    "camera_reason": "画面下方有双手、晃动明显",
    "people": ["me", "baby"],
    "location": "客厅",
    "summary": "一句话描述这段素材",
    "moments": [{"start": 12.0, "end": 15.5, "label": "宝宝笑出声", "score": 9, "why": "第14秒帧宝宝张嘴笑"}],
    "bad_ranges": [{"start": 0, "end": 2.5, "why": "开机晃动/黑屏"}],
    "privacy_flags": [{"t": 33.0, "what": "快递单可见"}],
    "best_use": "适合放在开头钩子",
}

TAG_SYSTEM = f"""你是素材分析员。你会收到一段家庭实拍素材的：带时间戳的关键帧（图片顺序与 frames 列表一致）、
语音转写、程序算出的画质指标（blur 越小越糊、change 越大越晃/动作越大）、静音段、可能的笑声/哭声情绪标记。
任务：判断机位（pov=第一人称：画面里有自己的手/明显晃动/低视角；tripod=固定第三人称；handheld=他人手持），
出镜人员（me/partner/baby），找出精彩瞬间（宝宝笑、看镜头、有趣动作、对话金句），标出废片区间与隐私风险
（门牌、快递单、小区名、屏幕信息）。时间必须来自给定的帧时间戳或转写时间，不要编造。
只输出 json，格式示例：
{json.dumps(TAG_EXAMPLE, ensure_ascii=False)}"""


def list_videos(folder: str | Path) -> list[Path]:
    folder = Path(folder)
    return sorted(p for p in folder.rglob("*") if p.suffix.lower() in VIDEO_EXT and p.is_file())


def _frame_times(duration: float, max_frames: int = 24) -> list[float]:
    step = max(2.0, duration / max_frames)
    return [round(t, 2) for t in np.arange(min(0.5, duration / 2), max(duration - 0.2, 0.6), step)][:max_frames]


def analyze_clip(pid: str, clip_path: str, idx: int) -> dict:
    pdir = store.project_dir(pid)
    cid = f"C{idx:02d}"
    work = pdir / "work" / cid
    work.mkdir(parents=True, exist_ok=True)
    info = media.probe(clip_path)
    dur = info["duration"]

    env = np.zeros(1)
    if info["has_audio"]:
        env = media.envelope(media.pcm(clip_path))
        np.save(work / "env.npy", env)
    quiet = media.silences(env) if info["has_audio"] else []
    clap_t = media.claps(env) if info["has_audio"] else []
    tr = asr.transcribe(clip_path, pdir / "work" / "asr", dur) if info["has_audio"] else {"sentences": []}

    slate = None
    for s in tr.get("sentences", [])[:5]:
        m = SLATE_RE.search(s["text"].replace(" ", ""))
        if m and s["start"] < 20:
            slate = {"shot_id": f"S{int(m.group(1)):02d}", "take": int(m.group(2)), "t": s["end"]}
            break

    frames = media.frame_metrics(media.sample_frames(clip_path, work / "frames", _frame_times(dur)))
    shake = float(np.mean([f.get("change", 0) for f in frames[1:]] or [0]))
    heur_cam = "pov" if shake > 14 else "tripod"
    emotions = [{"t": s["start"], "emotion": s.get("emotion")} for s in tr.get("sentences", []) if s.get("emotion")]

    payload = {
        "clip_id": cid, "file": Path(clip_path).name, "duration": dur,
        "orientation": info.get("orientation"), "creation_time": info.get("creation_time"),
        "frames": [{"t": f["t"], "blur": f.get("blur"), "brightness": f.get("brightness"),
                    "change": f.get("change")} for f in frames],
        "transcript": [{"start": s["start"], "end": s["end"], "text": s["text"], "speaker": s.get("speaker")}
                       for s in tr.get("sentences", [])][:120],
        "transcript_is_mock": tr.get("mock", False),
        "silences": quiet[:60], "claps": clap_t[:10], "emotions": emotions[:30],
        "heuristic_camera": heur_cam, "mean_change": round(shake, 1), "slate": slate,
    }
    tags = llm.chat_json("footage_tag", TAG_SYSTEM, payload, images=[f["path"] for f in frames],
                         thinking=False, max_tokens=6000)
    for k in ("moments", "bad_ranges", "privacy_flags"):
        tags[k] = [x for x in tags.get(k, []) if isinstance(x, dict)]
        for x in tags[k]:
            for tk in ("start", "end", "t"):
                if tk in x:
                    x[tk] = round(min(max(float(x[tk]), 0.0), dur), 2)

    return {
        "clip_id": cid, "path": str(Path(clip_path).resolve()), "file": Path(clip_path).name,
        "info": info, "slate": slate, "claps": clap_t, "silences": quiet,
        "speech_ranges": asr.speech_ranges(tr), "transcript_engine": tr.get("engine"),
        "transcript_mock": tr.get("mock", False),
        "frames": [{"t": f["t"], "path": f["path"], "blur": f.get("blur"), "change": f.get("change")} for f in frames],
        "heuristic_camera": heur_cam, "tags": tags,
    }


def analyze_all(pid: str, clip_paths: list[str], progress: Callable[[str], None] | None = None,
                workers: int = 4) -> dict:
    say = progress or (lambda m: None)
    clips: list[dict] = []
    errors: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(analyze_clip, pid, p, i): p for i, p in enumerate(clip_paths, 1)}
        for n, fut in enumerate(as_completed(futs), 1):
            try:
                clips.append(fut.result())
                say(f"素材分析 {n}/{len(futs)}：{Path(futs[fut]).name}")
            except Exception as e:
                errors.append({"file": futs[fut], "error": str(e)})
                say(f"素材分析失败：{Path(futs[fut]).name}：{e}")
    clips.sort(key=lambda c: c["clip_id"])
    groups = sync_groups(pid, clips)
    result = {"clips": clips, "sync_groups": groups, "errors": errors}
    store.save(pid, "footage", result)
    return result


def _ctime(c: dict) -> float | None:
    t = c["info"].get("creation_time")
    if not t:
        return None
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def sync_groups(pid: str, clips: list[dict]) -> list[dict]:
    """Pair POV and third-person clips that overlap in wall-clock time; refine by audio correlation."""
    pdir = store.project_dir(pid)
    povs = [c for c in clips if c["tags"].get("camera", c["heuristic_camera"]) == "pov"]
    others = [c for c in clips if c not in povs]
    groups = []
    for a in others:
        for b in povs:
            ta, tb = _ctime(a), _ctime(b)
            if ta and tb:
                overlap = min(ta + a["info"]["duration"], tb + b["info"]["duration"]) - max(ta, tb)
                if overlap < 3:
                    continue
            ea, eb = pdir / "work" / a["clip_id"] / "env.npy", pdir / "work" / b["clip_id"] / "env.npy"
            if not (ea.exists() and eb.exists()):
                continue
            off, conf = media.sync_offset(np.load(ea), np.load(eb))
            if conf >= 0.25 or (ta and tb):
                groups.append({"a": a["clip_id"], "b": b["clip_id"], "offset_s": off, "confidence": conf,
                               "meaning": f"{a['clip_id']} 的 t 秒 = {b['clip_id']} 的 t-{off} 秒",
                               "method": "audio-xcorr" + ("+creation_time" if ta and tb else "")})
    return groups
