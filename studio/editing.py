"""Edit planning, timeline validation, subtitles (ASS), render + review loop."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from . import llm, media, store
from .loop import refine

# Every technique here is actually executable by the renderer (or by timeline ordering).
TECHNIQUES = {
    "hook_first": "把最强瞬间（宝宝笑/结果画面/金句）提到 0-3 秒，之后再从头讲",
    "jump_cut": "只用 speech_ranges 里的说话区间，去掉长停顿和语气词",
    "camera_alternate": "同一时刻的 POV 与三脚架素材交替：动作/手部细节用 POV，说话/表情用三脚架（依赖 sync_groups）",
    "l_cut": "画面切到下一个镜头，声音仍延续上一段（segment 设置 audio_src/audio_in 为上一段音频）",
    "j_cut": "下一段的声音先进来，画面后切（当前段 audio_src/audio_in 指向下一段音频）",
    "punch_in": "强调句或宝宝表情时 zoom=1.12~1.25 推近，制造节奏",
    "speed_ramp": "无对白的过程段 speed=1.5~2.0 加速；精彩瞬间 speed=0.6~0.8 慢放（慢放段建议 mute 或配乐）",
    "beat_sync": "有 BGM 时剪辑点贴合节拍（程序会自动把切点吸附到最近的拍点）",
    "mic_swap": "POV 画面配三脚架/领夹麦的音轨（audio_src 指向同步的另一机位）",
}

OPTIONS_EXAMPLE = {"options": [
    {"id": "A", "name": "温馨 vlog", "duration_s": 150, "aspect": "16:9", "style": "按时间顺序 + 字幕旁白",
     "structure": ["钩子：宝宝笑", "起床", "洗澡", "结尾互动"], "techniques": ["hook_first", "camera_alternate"],
     "why": "素材里有完整的一天流程"}]}

OPTIONS_SYSTEM = f"""你是剪辑导演。根据素材分析结果（每段素材的机位、人物、精彩瞬间、转写摘要）提出 2-3 个剪辑方案。
可用技巧（只能从中选）：{json.dumps(TECHNIQUES, ensure_ascii=False)}
方案要有明显区别（如：温馨vlog 2-3分钟 / 卡点短视频 15-30秒 / 口播剪辑）。aspect 选 16:9（B站/YouTube）或 9:16（抖音/小红书/快手）。
如果用户给了意图说明，优先满足。只输出 json，格式示例：
{json.dumps(OPTIONS_EXAMPLE, ensure_ascii=False)}"""

TIMELINE_EXAMPLE = {
    "segments": [
        {"clip": "C02", "in": 12.0, "out": 15.5, "purpose": "钩子：宝宝笑", "techniques": ["hook_first", "punch_in"],
         "zoom": 1.15, "speed": 1.0, "caption": "她第一次笑出声！", "emphasis": ["第一次"]},
        {"clip": "C01", "in": 3.2, "out": 9.8, "purpose": "交代背景", "techniques": ["jump_cut"],
         "audio_src_clip": None, "audio_in": None},
    ],
    "title_options": ["标题1", "标题2"],
    "cover": {"clip": "C02", "t": 14.0, "text": "封面大字"},
    "bgm_mood": "温暖轻快钢琴",
    "notes": "剪辑思路",
}

TIMELINE_SYSTEM = f"""你是剪辑师。按选定方案输出时间线。
- 只能使用给定素材的 clip_id 和素材时长范围内的时间；说话段落优先使用 speech_ranges 的边界（避免剪断句子）。
- 避开 bad_ranges；尽量使用 moments。
- 技巧只能从这里选：{json.dumps(TECHNIQUES, ensure_ascii=False)}
- l_cut/j_cut/mic_swap 用 audio_src_clip + audio_in 表达（音频来自哪段素材的哪一秒）。
- caption 写这一段要上屏的关键字幕（没有对白时写旁白字幕），emphasis 为要高亮的关键词。
- 总时长贴合方案 duration_s。根据 critic_feedback 修改上一版 previous。
只输出 json，格式示例：
{json.dumps(TIMELINE_EXAMPLE, ensure_ascii=False)}"""


def _footage_digest(footage: dict) -> list[dict]:
    out = []
    for c in footage["clips"]:
        t = c["tags"]
        out.append({"clip_id": c["clip_id"], "file": c["file"], "duration": c["info"]["duration"],
                    "orientation": c["info"].get("orientation"), "camera": t.get("camera", c["heuristic_camera"]),
                    "people": t.get("people"), "location": t.get("location"), "summary": t.get("summary"),
                    "moments": t.get("moments"), "bad_ranges": t.get("bad_ranges"), "slate": c.get("slate"),
                    "privacy_flags": t.get("privacy_flags"),
                    "speech_ranges": [{"start": r["start"], "end": r["end"], "text": r["text"][:60]}
                                      for r in c["speech_ranges"][:80]]})
    return out


def edit_options(pid: str, intent: str = "") -> dict:
    footage = store.load(pid, "footage")
    if not footage or not footage.get("clips"):
        raise ValueError("请先上传并分析素材")
    out = llm.chat_json("edit_options", OPTIONS_SYSTEM,
                        {"intent": intent, "footage": _footage_digest(footage),
                         "sync_groups": footage.get("sync_groups"), "script": store.load(pid, "script")},
                        thinking=True)
    store.save(pid, "edit_options", out)
    return out


# ---------------- timeline validation ----------------

def validate_timeline(tl: dict, footage: dict, beats: list[float] | None = None) -> dict:
    clips = {c["clip_id"]: c for c in footage["clips"]}
    segs, dropped = [], []
    for s in tl.get("segments", []):
        c = clips.get(s.get("clip"))
        if not c:
            dropped.append({"segment": s, "why": "未知 clip"})
            continue
        dur = c["info"]["duration"]
        try:
            a, b = float(s.get("in", 0)), float(s.get("out", 0))
        except (TypeError, ValueError):
            dropped.append({"segment": s, "why": "时间非数字"})
            continue
        a, b = max(0.0, min(a, dur)), max(0.0, min(b, dur))
        a, b = _snap_to_speech(a, b, c["speech_ranges"])
        if b - a < 0.4:
            dropped.append({"segment": s, "why": "片段过短/越界"})
            continue
        s.update({"in": round(a, 2), "out": round(b, 2)})
        s["zoom"] = min(max(float(s.get("zoom") or 1.0), 1.0), 1.4)
        s["speed"] = min(max(float(s.get("speed") or 1.0), 0.5), 2.0)
        ac = s.get("audio_src_clip")
        if ac and ac not in clips:
            s["audio_src_clip"] = None
        segs.append(s)
    if beats:
        segs = _snap_to_beats(segs, beats)
    tl["segments"] = segs
    tl["dropped"] = dropped
    tl["duration_s"] = round(sum((s["out"] - s["in"]) / s["speed"] for s in segs), 2)
    return tl


def _snap_to_speech(a: float, b: float, ranges: list[dict], tol: float = 0.35) -> tuple[float, float]:
    """If a cut lands inside a speech range within `tol` of its edge, move it to the edge."""
    for r in ranges:
        if r["start"] < a < r["end"] and a - r["start"] <= tol:
            a = r["start"]
        if r["start"] < b < r["end"] and r["end"] - b <= tol:
            b = r["end"]
    return a, b


def _snap_to_beats(segs: list[dict], beats: list[float], tol: float = 0.25) -> list[dict]:
    t = 0.0
    for s in segs:
        length = (s["out"] - s["in"]) / s["speed"]
        end = t + length
        nb = min(beats, key=lambda x: abs(x - end)) if beats else end
        if abs(nb - end) <= tol and (nb - t) > 0.4:
            s["out"] = round(s["in"] + (nb - t) * s["speed"], 2)
            end = nb
        t = end
    return segs


# ---------------- subtitles ----------------

def _ass_time(t: float) -> str:
    h, r = divmod(max(t, 0), 3600)
    m, s = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def build_subtitles(tl: dict, footage: dict, width: int, height: int, out_dir: Path) -> tuple[Path, Path]:
    clips = {c["clip_id"]: c for c in footage["clips"]}
    events: list[tuple[float, float, str, list[str]]] = []
    t = 0.0
    for s in tl["segments"]:
        c = clips[s["clip"]]
        length = (s["out"] - s["in"]) / s["speed"]
        used = False
        if not c.get("transcript_mock"):
            for r in c["speech_ranges"]:
                a, b = max(r["start"], s["in"]), min(r["end"], s["out"])
                if b - a > 0.2:
                    events.append((t + (a - s["in"]) / s["speed"], t + (b - s["in"]) / s["speed"],
                                   r["text"], s.get("emphasis") or []))
                    used = True
        if not used and s.get("caption"):
            events.append((t, t + length, s["caption"], s.get("emphasis") or []))
        t += length

    fs = int(height * (0.045 if width > height else 0.035))
    ass = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        f"Style: Default,Microsoft YaHei,{fs},&H00FFFFFF,&H000000FF,&H00222222,&H64000000,-1,0,0,0,100,100,0,0,1,"
        f"{max(fs // 12, 2)},1,2,40,40,{int(height * 0.08)},1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    srt = []
    for i, (a, b, text, emph) in enumerate(events, 1):
        txt = text.replace("\n", " ")
        for w in emph:
            if w and w in txt:
                txt = txt.replace(w, "{\\c&H00D7FF&}" + w + "{\\c&HFFFFFF&}")
        ass.append(f"Dialogue: 0,{_ass_time(a)},{_ass_time(b)},Default,,0,0,0,,{txt}")
        srt.append(f"{i}\n{_srt_time(a)} --> {_srt_time(b)}\n{text}\n")
    out_dir.mkdir(parents=True, exist_ok=True)
    pa, ps = out_dir / "subtitles.ass", out_dir / "subtitles.srt"
    pa.write_text("\n".join(ass) + "\n", encoding="utf-8")
    ps.write_text("\n".join(srt), encoding="utf-8")
    return pa, ps


def _srt_time(t: float) -> str:
    ms = int(round(max(t, 0) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ---------------- render + review loop ----------------

def _dims(aspect: str, preview: bool) -> tuple[int, int]:
    if aspect == "9:16":
        return (540, 960) if preview else (1080, 1920)
    return (854, 480) if preview else (1920, 1080)


def _render(pid: str, tl: dict, footage: dict, aspect: str, tag: str, preview: bool,
            bgm: str | None, progress) -> dict:
    pdir = store.project_dir(pid)
    clips = {c["clip_id"]: c for c in footage["clips"]}
    w, h = _dims(aspect, preview)
    segs = []
    for s in tl["segments"]:
        c = clips[s["clip"]]
        seg = {"src": c["path"], "in": s["in"], "out": s["out"], "zoom": s["zoom"], "speed": s["speed"],
               "has_audio": c["info"]["has_audio"], "mute": s.get("mute", False)}
        ac = s.get("audio_src_clip")
        if ac and clips[ac]["info"]["has_audio"]:
            seg["audio_src"] = clips[ac]["path"]
            seg["audio_in"] = float(s.get("audio_in") if s.get("audio_in") is not None else s["in"])
        segs.append(seg)
    out_dir = pdir / "output"
    ass, srt = build_subtitles(tl, footage, w, h, out_dir)
    video = media.render_segments(segs, out_dir / f"{tag}.mp4", width=w, height=h, workdir=pdir / "work" / tag,
                                  preset="ultrafast" if preview else "medium", crf=28 if preview else 20,
                                  subtitles=str(ass), bgm=bgm, progress=progress)
    # review frames: middle of each segment in output time
    times, t = [], 0.0
    for s in tl["segments"]:
        length = (s["out"] - s["in"]) / s["speed"]
        times.append(round(t + length / 2, 2))
        t += length
    times = [0.3, 1.5, 2.8] + times
    frames = media.sample_frames(video, pdir / "work" / tag / "review_frames", sorted(set(times))[:40], width=480)
    return {"video": str(video), "ass": str(ass), "srt": str(srt), "frames": frames, "width": w, "height": h}


def cut(pid: str, option: dict, bgm: str | None = None, on_round: Callable | None = None,
        progress: Callable[[str], None] | None = None) -> dict:
    say = progress or (lambda m: None)
    footage = store.load(pid, "footage")
    digest = _footage_digest(footage)
    aspect = option.get("aspect", "16:9")
    beat_times = media.beats(media.pcm(bgm))["beats"] if bgm else None
    renders: dict[int, dict] = {}
    it = {"n": 0}

    def generate(feedback, prev):
        it["n"] += 1
        say(f"第{it['n']}轮：生成时间线…")
        raw = llm.chat_json("timeline", TIMELINE_SYSTEM,
                            {"option": option, "footage": digest, "sync_groups": footage.get("sync_groups"),
                             "has_bgm": bool(bgm), "critic_feedback": feedback, "previous": prev}, thinking=True)
        tl = validate_timeline(raw, footage, beat_times)
        if not tl["segments"]:
            raise ValueError("时间线为空：模型没有给出有效片段")
        say(f"第{it['n']}轮：渲染预览（{len(tl['segments'])} 段，{tl['duration_s']}s）…")
        r = _render(pid, tl, footage, aspect, f"preview_r{it['n']}", True, bgm, say)
        renders[it["n"]] = r
        tl["_preview"] = {"video": r["video"], "frame_times": [f["t"] for f in r["frames"]]}
        tl["_subtitles"] = Path(r["srt"]).read_text(encoding="utf-8")[:6000]
        return tl

    def critic_images(tl):
        return [f["path"] for f in renders[it["n"]]["frames"]]

    privacy = [{"clip": c["clip_id"], **p} for c in footage["clips"] for p in c["tags"].get("privacy_flags", [])]
    res = refine("cut", generate, {"option": option, "privacy_flags_in_footage": privacy},
                 upstream_stages=("script", "storyboard", "footage"), critic_images=critic_images,
                 on_round=on_round)
    out = res.to_dict()
    best = out["best"]
    say("渲染最终成片（高清）…")
    final = _render(pid, best, footage, aspect, "final", False, bgm, say)
    cover = best.get("cover") or {}
    clips = {c["clip_id"]: c for c in footage["clips"]}
    covers = []
    if cover.get("clip") in clips:
        covers = media.sample_frames(clips[cover["clip"]]["path"], store.project_dir(pid) / "output" / "covers",
                                     [float(cover.get("t", 1.0))], width=1280)
    out["final"] = {"video": final["video"], "srt": final["srt"], "ass": final["ass"],
                    "covers": [c["path"] for c in covers]}
    store.save(pid, "timeline", best)
    store.save(pid, "cut", out)
    return out
