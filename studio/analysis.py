"""Single-topic analysis (link / keyword / screenshots) and daily topic generation."""
from __future__ import annotations

import json
from typing import Callable

from . import milestones, llm, sources, store
from .loop import refine

REPORT_EXAMPLE = {
    "verdict": "改编后拍",
    "score": 7.6,
    "one_liner": "一句话理由",
    "confidence": "中",
    "hook_breakdown": [{"point": "前3秒直接给出结果画面", "evidence": "标题/封面/评论第3条"}],
    "data": {"summary": "互动率判断", "evidence": "like_rate=0.072（B站接口）"},
    "audience_needs": [{"need": "观众想知道的具体问题", "evidence": "评论区 Top20 中 6 条提到"}],
    "saturation": {"level": "中", "evidence": "近7天同题材搜索结果 N 条"},
    "feasibility": {"score": 8, "needs_cast": ["me", "baby"], "cost_cny": 0, "cameras": ["pov", "tripod"],
                    "baby_fit": "4个月宝宝可以做到/做不到的部分", "notes": ""},
    "angles": [{"title": "我家版本标题", "pitch": "怎么拍", "why_different": "和原视频的区别"}],
    "risks": ["搬运/隐私/平台规范风险"],
    "falsified_if": ["在什么情况下这个结论不成立"],
    "need_more_evidence": [{"section": "saturation", "search_query": "需要补查的搜索词"}],
}

ANALYST_SYSTEM = f"""你是生活区短视频选题分析师，服务一个三口之家账号（我 + 爱人 + 4个月宝宝），只能在家/小区附近实拍。
根据给定的一手数据（接口数据、评论、页面、截图、同类搜索结果）写分析报告。
铁律：
- 每条判断都要写 evidence（来自哪个数据/哪条评论/哪个搜索结果）。没有证据就写"证据不足"并降低 confidence，不准编造数字。
- 可复刻性必须对照演员档案：宝宝只做捕捉式拍摄，不能要求宝宝"表演"；4个月宝宝不会坐/爬/吃辅食。
- verdict 只能是 "拍" / "改编后拍" / "不拍"。
- 若某部分证据不足，在 need_more_evidence 中给出补查用的搜索词（最多 3 个）。
- 参考历史校准记录：如果过去的预测系统性偏高/偏低，要相应修正 score。
只输出 json，格式示例：
{json.dumps(REPORT_EXAMPLE, ensure_ascii=False)}"""


def analyze_topic(text: str, screenshots: list[str] | None = None,
                  on_round: Callable | None = None, progress: Callable[[str], None] | None = None) -> dict:
    say = progress or (lambda m: None)
    say("获取数据…")
    bundle = sources.resolve_source(text, screenshots)
    cast = store.get_cast()
    calibration = store.recall("calibration", limit=10)
    extra_evidence: list[dict] = []
    searches_done = 0

    def payload(feedback, prev):
        return {"source": {k: v for k, v in bundle.items() if k != "screenshots"},
                "extra_evidence": extra_evidence, "cast": cast, "calibration_history": calibration,
                "critic_feedback": feedback, "previous_report": prev}

    def generate(feedback, prev):
        nonlocal searches_done
        # Evidence top-up: honour search requests from the previous draft / critic (budget 3)
        wanted = [x.get("search_query") for x in (prev or {}).get("need_more_evidence", []) if x.get("search_query")]
        wanted += [x.get("search_query") for x in feedback if x.get("search_query")]
        done_q = {x["query"] for x in extra_evidence}
        for q in dict.fromkeys(wanted):  # dedupe, keep order
            if searches_done >= 3:
                break
            if not q or q in done_q:
                continue
            say(f"补查证据：{q}")
            try:
                extra_evidence.append({"query": q, "results": sources.ds_search(q, count=8)})
            except Exception as e:
                extra_evidence.append({"query": q, "error": str(e)})
            searches_done += 1
        say("生成分析报告…")
        return llm.chat_json("analyze_topic", ANALYST_SYSTEM, payload(feedback, prev),
                             images=bundle["screenshots"] or None, thinking=True)

    result = refine("analysis", generate, {"source_summary": bundle.get("topic"), "gaps": bundle["gaps"],
                                            "cast": cast}, on_round=on_round)
    out = result.to_dict()
    out["source"] = {k: v for k, v in bundle.items() if k != "screenshots"}
    out["extra_evidence"] = extra_evidence
    return out


TOPIC_COUNT = 5

TOPICS_SYSTEM = f"""你是生活区账号主编。为这个三口之家（我 + 爱人 + 宝宝，见 cast）挑出 **正好 {TOPIC_COUNT} 个** 能在家拍的选题。
两类来源都要有：
1. 热点改编（source="trending"）：从 trending 里选。**优先爆款系数（viral_ratio = 播放/粉丝）高、small_creator=true 的视频**——
   那说明是选题本身带量，小号可以借；viral_level="主要靠粉丝" 的大 UP 视频不要作为主要依据。low_sample=true（粉丝不足 1000）的系数是噪声，不要据此判断；
   和育儿/家庭/日常无关的（游戏、电竞、时政）只借结构，不借内容。inspired_by 必须写出 viral_ratio。
2. 月龄日历（source="milestone"）：从 milestone_calendar 的 now/next/events/seasonal 里选。不依赖热点、一定拍得出来、天然成系列。
   next 里的里程碑是“下个月可能出现”，可以做成“提前准备、出现时就能拍到”的选题。
建议 2-3 个热点改编 + 2-3 个月龄日历。每个选题必须：给出我家版本的切入角度、可拍性（谁出镜、宝宝如何捕捉、成本、机位）、预计时长。
里程碑只写“记录/尝试”，不写“训练达标”；遵守 milestone_calendar 里的 safety。参考历史复盘 retrospectives。
只输出 json：{{"topics":[{{"title":"","source":"trending|milestone","angle":"","why_now":"",
"inspired_by":[{{"title":"","url":"","viral_ratio":null}}],"cast":["me","baby"],
"feasibility":"","cameras":["pov","tripod"],"cost_cny":0,"duration_s":60,"series_potential":""}}]}}"""


def daily_topics(on_round: Callable | None = None) -> dict:
    try:
        tr = sources.trending_candidates(40)
    except Exception as e:
        tr = {"items": [], "errors": [str(e)]}
    trending = tr["items"]
    cast = store.get_cast()
    cal = milestones.calendar(cast)
    retro = store.recall("retrospective", limit=10)
    # compact view for the model: titles + numbers, no cover urls
    brief = [{k: it.get(k) for k in ("title", "url", "category", "owner", "list", "followers", "viral_ratio",
                                      "viral_level", "small_creator", "low_sample", "views_per_hour", "duration_s")}
             | {"view": it["stats"]["view"]} for it in trending]

    def generate(feedback, prev):
        out = llm.chat_json("daily_topics", TOPICS_SYSTEM,
                            {"trending": brief, "milestone_calendar": cal, "cast": cast, "retrospectives": retro,
                             "critic_feedback": feedback, "previous": prev}, thinking=True)
        out["topics"] = [t for t in out.get("topics", []) if isinstance(t, dict)][:TOPIC_COUNT]
        return out

    out = refine("topics", generate, {"cast": cast, "required_count": TOPIC_COUNT,
                                      "milestone_calendar": cal}, on_round=on_round).to_dict()
    out["trending"] = trending
    out["trending_errors"] = tr.get("errors", [])
    out["milestone_calendar"] = cal
    return out
