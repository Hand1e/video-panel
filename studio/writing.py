"""Script -> storyboard shots -> shot list (shooting order + slates + safety)."""
from __future__ import annotations

import json
from typing import Callable

from . import llm, store
from .loop import refine
from .storyboard import ADULT_POSES, BABY_POSES, SIZES

SCRIPT_EXAMPLE = {
    "title": "视频标题",
    "duration_s": 60,
    "platform_format": "9:16",
    "logline": "一句话讲清这条视频",
    "beats": [
        {"id": "B1", "section": "hook", "summary": "结果前置：宝宝第一次笑出声的瞬间", "duration_s": 3,
         "key_lines": ["金句（口语化，不写逐字稿）"], "cast": ["me", "baby"],
         "baby_capture": {"hope": "希望宝宝笑", "lure": "举高高/叫名字/摇铃", "fallback": "拍不到就用睡颜+字幕"}},
    ],
    "title_options": ["标题1", "标题2", "标题3"],
    "cover_idea": "封面构图",
}

SCRIPT_SYSTEM = f"""你是生活区短视频编剧，服务三口之家（我 + 爱人 + 4个月宝宝），在家实拍。
写结构化脚本：钩子(0-3秒) → 冲突/问题 → 过程 → 反转/干货 → 互动结尾。
- 台词只写要点 + 关键金句（口语化），不写逐字稿。
- 宝宝相关段落必须写 baby_capture（希望发生什么、怎么引导、拍不到的备选），绝不要求宝宝"表演"。
- 每段标注出镜人员；爱人只在其可用时段出现。
- 考虑宝宝安全与家庭隐私。
根据 critic_feedback 修改上一版（previous），逐条解决问题。
只输出 json，格式示例：
{json.dumps(SCRIPT_EXAMPLE, ensure_ascii=False)}"""


def write_script(brief: dict, on_round: Callable | None = None) -> dict:
    cast = store.get_cast()

    def generate(feedback, prev):
        return llm.chat_json("script", SCRIPT_SYSTEM, {"brief": brief, "cast": cast,
                                                       "critic_feedback": feedback, "previous": prev})

    return refine("script", generate, {"brief": brief, "cast": cast},
                  upstream_stages=("analysis", "topics"), on_round=on_round).to_dict()


SHOT_EXAMPLE = {
    "shots": [
        {"shot_id": "S01", "beat_id": "B1", "camera": "tripod", "size": "medium", "location": "客厅",
         "figures": [{"who": "me", "pose": "hold_baby", "x": 0.5}],
         "props": ["摇铃"], "action": "举起宝宝，看向镜头", "line": "她今天第一次笑出声了！",
         "duration_s": 3, "transition": "cut", "capture": True,
         "notes": "持续开机 3 分钟，等宝宝笑", "needs_operator": False},
    ]
}

STORYBOARD_SYSTEM = f"""你是分镜导演。把脚本拆成镜头，输出给简笔画渲染器的参数。
可用 camera: pov(第一人称，画面里是"我"的手和我看到的东西), tripod(第三人称固定机位), handheld(仅爱人掌镜时可用)。
可用 size: {', '.join(SIZES)}。
成人 pose 只能从中选: {', '.join(ADULT_POSES)}。
宝宝 pose 只能从中选: {', '.join(BABY_POSES)}（4个月宝宝不会坐/爬/走）。
figures 中 x 为画面横向位置 0-1。camera=pov 时 figures 不要包含 "me"（我是镜头本身），用 pov_hands 描述手的动作。
要求：景别有变化；同一动作尽量 pov 和 tripod 各拍一条方便剪辑交替；宝宝镜头 capture=true（长录捕捉）；
needs_operator=true 表示必须爱人掌镜，并给出无人掌镜的备选（notes 中写）。
根据 critic_feedback 修改上一版（previous）。只输出 json，格式示例：
{json.dumps(SHOT_EXAMPLE, ensure_ascii=False)}"""


def make_storyboard(script: dict, on_round: Callable | None = None) -> dict:
    cast = store.get_cast()

    def generate(feedback, prev):
        out = llm.chat_json("storyboard", STORYBOARD_SYSTEM, {"script": script, "cast": cast,
                                                              "critic_feedback": feedback, "previous": prev})
        return sanitize_shots(out)

    return refine("storyboard", generate, {"script": script, "cast": cast},
                  upstream_stages=("script",), on_round=on_round).to_dict()


def sanitize_shots(out: dict) -> dict:
    """Clamp model output to what the renderer supports (never trust free-form pose names)."""
    shots = out.get("shots", []) if isinstance(out, dict) else []
    for i, s in enumerate(shots, 1):
        s.setdefault("shot_id", f"S{i:02d}")
        if s.get("camera") not in ("pov", "tripod", "handheld"):
            s["camera"] = "tripod"
        if s.get("size") not in SIZES:
            s["size"] = "medium"
        figs = []
        for f in s.get("figures", []) or []:
            who = f.get("who", "me")
            if s["camera"] == "pov" and who == "me":
                continue
            valid = BABY_POSES if who == "baby" else ADULT_POSES
            if f.get("pose") not in valid:
                f["pose"] = valid[0]
            try:
                f["x"] = min(max(float(f.get("x", 0.5)), 0.05), 0.95)
            except (TypeError, ValueError):
                f["x"] = 0.5
            figs.append(f)
        s["figures"] = figs
    return {"shots": shots}


# ---------------- shot list (deterministic scheduling) ----------------

CAMERA_ORDER = {"tripod": 0, "handheld": 1, "pov": 2}


def make_shotlist(shots: list[dict]) -> dict:
    """Group for minimal setup changes: location -> camera; baby capture shots go into the
    'baby awake & happy' block first, adult-only shots into the nap block."""
    cast = store.get_cast()
    baby = next((m for m in cast["members"] if m["id"] == "baby"), {})
    blocks: dict[str, list] = {"宝宝清醒时段（优先）": [], "宝宝午睡时段（只拍大人）": [], "需要爱人掌镜": []}
    for s in shots:
        whos = {f.get("who") for f in s.get("figures", [])}
        if s.get("needs_operator") or s.get("camera") == "handheld":
            blocks["需要爱人掌镜"].append(s)
        elif "baby" in whos or s.get("capture"):
            blocks["宝宝清醒时段（优先）"].append(s)
        else:
            blocks["宝宝午睡时段（只拍大人）"].append(s)

    out_blocks = []
    for name, items in blocks.items():
        items.sort(key=lambda s: (s.get("location", ""), CAMERA_ORDER.get(s.get("camera"), 9)))
        steps, last_setup = [], None
        for s in items:
            setup = (s.get("location", ""), s.get("camera"))
            if setup != last_setup:
                steps.append({"type": "setup", "text": f"📍 {setup[0] or '现场'} · 架设 {_cam_cn(setup[1])}"})
                last_setup = setup
            steps.append({"type": "shot", "shot_id": s["shot_id"], "camera": s.get("camera"),
                          "slate": f"开拍先拍手一下，然后念：「{s['shot_id']}，第 N 条」",
                          "action": s.get("action", ""), "line": s.get("line", ""),
                          "capture": bool(s.get("capture")),
                          "tip": ("长录捕捉：至少开机 2-3 分钟，不要停机等宝宝" if s.get("capture")
                                  else "至少拍 2 条；同一动作 POV/三脚架各一条"),
                          "notes": s.get("notes", "")})
        if items:
            out_blocks.append({"block": name, "steps": steps})

    return {
        "blocks": out_blocks,
        "baby_schedule_hint": baby.get("best_mood_slots"),
        "safety": baby.get("safety", []),
        "privacy_checklist": ["门牌号/楼栋号", "快递单/外卖单", "小区名/窗外地标", "屏幕上的个人信息"],
        "gear_checklist": ["三脚架", "第一人称支架（头戴/胸前）", "两台设备电量 > 80%", "存储空间", "收音（领夹麦）"],
    }


def _cam_cn(c: str | None) -> str:
    return {"pov": "第一人称支架", "tripod": "三脚架（第三人称）", "handheld": "手持（爱人掌镜）"}.get(c or "", c or "")
