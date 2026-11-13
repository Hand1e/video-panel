"""Deterministic demo outputs used when DEEPSEEK_API_KEY is not set. Clearly labelled `_mock`.

They are built from the real inputs (real B站 numbers, real footage timings) so the downstream code
paths are exercised for real; only the "judgement" text is canned.
"""
from __future__ import annotations

from .rubrics import RUBRICS

TAG = "【演示数据】"


def respond(task: str, p: dict, n_images: int = 0) -> dict:
    if task.startswith("critic:"):
        out = _critic(task.split(":", 1)[1], p)
    else:
        out = {
            "analyze_topic": _analysis, "daily_topics": _topics, "script": _script, "storyboard": _storyboard,
            "footage_tag": _footage_tag, "edit_options": _edit_options, "timeline": _timeline,
        }[task](p)
    out["_mock"] = True
    return out


def _critic(stage: str, p: dict) -> dict:
    it = int(p.get("iteration", 1))
    dims = list(RUBRICS[stage]["dimensions"])
    scores = {d: round(min(9.0, 5.6 + (i % 3) * 0.5 + 0.9 * (it - 1)), 1) for i, d in enumerate(dims)}
    weak = sorted(scores, key=scores.get)[:2]
    issues = [] if min(scores.values()) >= 7 else [
        {"dim": d, "problem": f"{TAG}{RUBRICS[stage]['dimensions'][d][:18]}… 不够到位",
         "fix": f"{TAG}针对 {d} 补充具体内容", "stage_owner": stage, "evidence": f"第{it}版"} for d in weak]
    if stage == "analysis" and it == 1:
        issues.append({"dim": "evidence", "problem": f"{TAG}同类饱和度没有证据", "fix": "补查近7天同题材",
                       "stage_owner": "analysis", "search_query": "4个月宝宝 日常 vlog"})
    return {"scores": scores, "issues": issues, "pass": min(scores.values()) >= 7, "summary": f"{TAG}第{it}轮审稿"}


def _analysis(p: dict) -> dict:
    src = p.get("source", {})
    v = src.get("video") or {}
    d = v.get("derived", {})
    title = v.get("title") or src.get("topic") or "该选题"
    ev = f"like_rate={d.get('like_rate')}，favorite_rate={d.get('favorite_rate')}（B站接口）" if d else "证据不足"
    comments = src.get("comments") or []
    top = comments[0]["text"][:30] if comments else None
    rev = len(p.get("critic_feedback") or [])
    return {
        "verdict": "改编后拍", "score": 7.2, "one_liner": f"{TAG}《{title[:20]}》的情绪点可迁移到新手爸妈+4个月宝宝场景",
        "confidence": "中" if d else "低",
        "hook_breakdown": [{"point": f"{TAG}标题直接抛出反差", "evidence": f"标题：{title[:30]}"}],
        "data": {"summary": f"{TAG}互动率参考", "evidence": ev},
        "audience_needs": [{"need": f"{TAG}观众关心真实感", "evidence": f"高赞评论：{top}" if top else "无评论数据"}],
        "saturation": {"level": "未知" if not p.get("extra_evidence") else "中",
                       "evidence": f"补查 {len(p.get('extra_evidence') or [])} 次" if p.get("extra_evidence") else "证据不足"},
        "feasibility": {"score": 8, "needs_cast": ["me", "baby"], "cost_cny": 0, "cameras": ["pov", "tripod"],
                        "baby_fit": "4个月宝宝可以：笑、抓握、趴着抬头；不能：坐、爬、吃辅食", "notes": TAG},
        "angles": [{"title": f"{TAG}新手爸爸版：{title[:12]}", "pitch": "POV 视角记录一次哄睡全过程",
                    "why_different": "从'结果'改成'过程+翻车'"},
                   {"title": f"{TAG}宝宝视角版", "pitch": "低机位三脚架 + 字幕给宝宝配内心戏",
                    "why_different": "第一人称换成宝宝"}],
        "risks": [f"{TAG}宝宝正脸是否公开；注意不要露出门牌"],
        "falsified_if": [f"{TAG}如果宝宝这周作息不稳定，捕捉镜头可能拍不到"],
        "need_more_evidence": [] if rev else [{"section": "saturation", "search_query": "4个月宝宝 日常 vlog"}],
    }


def _topics(p: dict) -> dict:
    tr = sorted([t for t in p.get("trending", []) if "title" in t], key=lambda t: -(t.get("viral_ratio") or 0))[:3]
    tr = tr or [{"title": "（无热门数据）", "url": "", "viral_ratio": None}]
    cal = p.get("milestone_calendar") or {}
    seeds = ((cal.get("now") or {}).get("ideas") or [])[:1] + ((cal.get("next") or {}).get("ideas") or [])[:1]
    seeds = (seeds + ["宝宝的第一个冬天"])[:2]
    angles = ["新手爸妈夜班交接实录", "爸爸一个人带娃的 24 小时", "宝宝视角看爸爸做饭"]
    topics = [{"title": f"{TAG}{angles[i % 3]}", "source": "trending", "angle": f"借鉴「{t['title'][:16]}」的结构",
               "why_now": f"爆款系数 {t.get('viral_ratio')}", "inspired_by": [
                   {"title": t["title"], "url": t.get("url", ""), "viral_ratio": t.get("viral_ratio")}],
               "cast": ["me", "baby"], "feasibility": "在家可拍，宝宝捕捉式", "cameras": ["pov", "tripod"],
               "cost_cny": 0, "duration_s": 60, "series_potential": "爸爸带娃系列"} for i, t in enumerate(tr)]
    topics += [{"title": f"{TAG}{x}", "source": "milestone", "angle": "月龄记录，长录捕捉",
                "why_now": f"宝宝 {cal.get('age_months')} 个月", "inspired_by": [], "cast": ["me", "baby"],
                "feasibility": "在家可拍；拍不到就改成'等待的过程'", "cameras": ["tripod", "pov"], "cost_cny": 0,
                "duration_s": 45, "series_potential": "月龄里程碑系列"} for x in seeds]
    while len(topics) < 5:
        topics.append({**topics[-1], "title": f"{TAG}备选选题 {len(topics) + 1}"})
    return {"topics": topics[:5]}


def _script(p: dict) -> dict:
    b = p.get("brief", {})
    title = b.get("title") or "4个月宝宝第一次笑出声"
    return {
        "title": f"{TAG}{title}", "duration_s": 60, "platform_format": "9:16",
        "logline": "新手爸爸想逗笑宝宝，试了 5 种方法，最后被一个意外动作逗笑",
        "beats": [
            {"id": "B1", "section": "hook", "summary": "结果前置：宝宝咯咯笑的 2 秒", "duration_s": 3,
             "key_lines": ["她笑了！！"], "cast": ["me", "baby"],
             "baby_capture": {"hope": "笑出声", "lure": "后面拍到的最佳笑声", "fallback": "用最开心的表情+字幕"}},
            {"id": "B2", "section": "conflict", "summary": "爸爸挑战：今天一定要把她逗笑", "duration_s": 8,
             "key_lines": ["听说4个月能笑出声了，今天必须拿下"], "cast": ["me"]},
            {"id": "B3", "section": "process", "summary": "依次尝试：鬼脸/摇铃/举高高/吹泡泡（快剪）", "duration_s": 30,
             "key_lines": ["这个不行…", "再来！"], "cast": ["me", "baby"],
             "baby_capture": {"hope": "各种反应", "lure": "每种方法 30 秒", "fallback": "宝宝面无表情本身就是笑点"}},
            {"id": "B4", "section": "twist", "summary": "爸爸打了个喷嚏，宝宝笑了", "duration_s": 12,
             "key_lines": ["？？？原来你喜欢这个"], "cast": ["me", "baby", "partner"],
             "baby_capture": {"hope": "意外笑点", "lure": "任何意外声音", "fallback": "爱人在旁边笑也可以"}},
            {"id": "B5", "section": "outro", "summary": "你家宝宝第一次笑是因为什么？", "duration_s": 7,
             "key_lines": ["评论区告诉我"], "cast": ["me"]},
        ],
        "title_options": [f"{TAG}试了5种方法，4个月女儿只对这个笑", f"{TAG}新手爸爸逗笑挑战"],
        "cover_idea": "宝宝大笑特写 + 爸爸懵的表情分屏",
    }


def _storyboard(p: dict) -> dict:
    return {"shots": [
        {"shot_id": "S01", "beat_id": "B1", "camera": "tripod", "size": "close", "location": "客厅",
         "figures": [{"who": "me", "pose": "hold_baby", "x": 0.5}], "action": "举着宝宝，宝宝大笑",
         "line": "她笑了！！", "duration_s": 3, "transition": "cut", "capture": True, "notes": f"{TAG}复用 S06 的笑"},
        {"shot_id": "S02", "beat_id": "B2", "camera": "tripod", "size": "medium", "location": "客厅",
         "figures": [{"who": "me", "pose": "talk", "x": 0.5}], "action": "对镜头宣布挑战",
         "line": "今天必须把她逗笑", "duration_s": 5, "transition": "jump_cut", "capture": False},
        {"shot_id": "S03", "beat_id": "B3", "camera": "pov", "size": "close", "location": "客厅地垫",
         "figures": [{"who": "baby", "pose": "baby_lie_back", "x": 0.5}], "pov_hands": "摇铃",
         "action": "低头看宝宝，摇摇铃", "line": "这个呢？", "duration_s": 6, "transition": "cut", "capture": True},
        {"shot_id": "S04", "beat_id": "B3", "camera": "tripod", "size": "wide", "location": "客厅地垫",
         "figures": [{"who": "me", "pose": "kneel_play", "x": 0.35}, {"who": "baby", "pose": "baby_lie_back", "x": 0.65}],
         "action": "跪在地垫边做鬼脸", "line": "", "duration_s": 6, "transition": "cut", "capture": True},
        {"shot_id": "S05", "beat_id": "B3", "camera": "tripod", "size": "medium", "location": "客厅",
         "figures": [{"who": "baby", "pose": "baby_tummy", "x": 0.5}], "action": "宝宝趴着抬头看泡泡",
         "line": "", "duration_s": 5, "transition": "cut", "capture": True, "notes": "趴卧全程大人在旁"},
        {"shot_id": "S06", "beat_id": "B4", "camera": "handheld", "size": "medium", "location": "客厅",
         "figures": [{"who": "me", "pose": "hold_baby", "x": 0.4}, {"who": "partner", "pose": "point", "x": 0.75}],
         "action": "爸爸打喷嚏，宝宝笑，妈妈指着大笑", "line": "原来你喜欢这个", "duration_s": 8, "transition": "cut",
         "capture": True, "needs_operator": True, "notes": "无人掌镜备选：三脚架全景"},
        {"shot_id": "S07", "beat_id": "B5", "camera": "tripod", "size": "close", "location": "沙发",
         "figures": [{"who": "me", "pose": "sit", "x": 0.5}], "action": "对镜头提问", "line": "评论区告诉我",
         "duration_s": 5, "transition": "fade", "capture": False},
    ]}


def _footage_tag(p: dict) -> dict:
    frames = p.get("frames") or []
    dur = float(p.get("duration") or 0)
    ranked = sorted(frames, key=lambda f: -(f.get("change") or 0))
    moments = [{"start": round(max(f["t"] - 1.0, 0), 2), "end": round(min(f["t"] + 1.5, dur), 2),
                "label": f"{TAG}画面变化较大的瞬间", "score": 7, "why": f"t={f['t']} change={f.get('change')}"}
               for f in ranked[:2]]
    blurry = [f for f in frames if (f.get("blur") or 999) < 15]
    return {"camera": p.get("heuristic_camera", "tripod"), "camera_reason": f"{TAG}按晃动指标判断",
            "people": ["me"], "location": "家中", "summary": f"{TAG}{p.get('file')}，{dur:.0f} 秒",
            "moments": moments, "bad_ranges": [{"start": f["t"] - 0.5, "end": f["t"] + 0.5, "why": "模糊"}
                                               for f in blurry[:3]],
            "privacy_flags": [], "best_use": "过程段"}


def _edit_options(p: dict) -> dict:
    total = sum(c["duration"] for c in p.get("footage", []))
    return {"options": [
        {"id": "A", "name": f"{TAG}温馨 vlog", "duration_s": min(150, max(20, total * 0.5)), "aspect": "16:9",
         "style": "时间顺序 + 字幕", "structure": ["钩子", "过程", "结尾互动"],
         "techniques": ["hook_first", "jump_cut", "camera_alternate"], "why": "素材是连续生活片段"},
        {"id": "B", "name": f"{TAG}卡点短视频", "duration_s": min(30, max(8, total * 0.3)), "aspect": "9:16",
         "style": "精彩瞬间 + 音乐卡点", "structure": ["最强瞬间", "快剪", "定格"],
         "techniques": ["hook_first", "beat_sync", "punch_in", "speed_ramp"], "why": "适合抖音/小红书"},
        {"id": "C", "name": f"{TAG}口播剪辑", "duration_s": min(90, max(15, total * 0.4)), "aspect": "9:16",
         "style": "以说话为主线去停顿", "structure": ["观点", "例子", "互动"],
         "techniques": ["jump_cut", "punch_in", "mic_swap"], "why": "有较多对白"},
    ]}


def _timeline(p: dict) -> dict:
    opt = p.get("option", {})
    target = float(opt.get("duration_s", 30))
    fb = len(p.get("critic_feedback") or [])
    segs, total = [], 0.0
    clips = p.get("footage", [])
    # hook first: best moment of any clip
    moments = sorted([(m.get("score", 0), c["clip_id"], m) for c in clips for m in (c.get("moments") or [])],
                     key=lambda x: -x[0])
    if moments:
        _, cid, m = moments[0]
        segs.append({"clip": cid, "in": m["start"], "out": m["end"], "purpose": "钩子", "zoom": 1.15,
                     "techniques": ["hook_first", "punch_in"], "caption": f"{TAG}先看结果", "emphasis": ["结果"]})
        total += m["end"] - m["start"]
    for c in clips:
        ranges = c.get("speech_ranges") or [{"start": 0.5, "end": min(c["duration"] - 0.2, 4.0), "text": ""}]
        for r in ranges:
            if total >= target:
                break
            ln = min(r["end"] - r["start"], 6.0 - fb)
            segs.append({"clip": c["clip_id"], "in": r["start"], "out": r["start"] + max(ln, 0.8),
                         "purpose": "过程", "techniques": ["jump_cut"], "caption": f"{TAG}{c['clip_id']} 片段"})
            total += max(ln, 0.8)
    return {"segments": segs, "title_options": [f"{TAG}标题A", f"{TAG}标题B"],
            "cover": {"clip": segs[0]["clip"] if segs else "C01", "t": segs[0]["in"] if segs else 1.0,
                      "text": "封面字"}, "bgm_mood": "轻快", "notes": f"{TAG}按方案 {opt.get('id')} 生成"}
