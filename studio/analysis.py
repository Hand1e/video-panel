"""Single-topic analysis (link / keyword / screenshots) and daily topic generation."""
from __future__ import annotations

import json
from typing import Callable

from . import llm, sources, store
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


TOPICS_SYSTEM = """你是生活区账号主编。从今日热门列表中，为这个三口之家（我 + 爱人 + 4个月宝宝）挑出 3 个能在家拍的选题。
每个选题必须：引用来源热门视频（title/url）、给出我家版本的切入角度、可拍性说明（谁出镜、宝宝如何捕捉、成本、机位）、预计时长。
同时参考月龄里程碑（4个月：抬头、笑出声、抓握、翻身前后）和历史复盘。
只输出 json：{"topics":[{"title":"","angle":"","inspired_by":[{"title":"","url":""}],"cast":["me","baby"],
"feasibility":"","cameras":["pov","tripod"],"cost_cny":0,"duration_s":60,"series_potential":""}]}"""


def daily_topics(on_round: Callable | None = None) -> dict:
    try:
        trending = sources.bili_popular(40)
    except Exception as e:
        trending = [{"error": str(e)}]
    cast = store.get_cast()
    retro = store.recall("retrospective", limit=10)

    def generate(feedback, prev):
        return llm.chat_json("daily_topics", TOPICS_SYSTEM,
                             {"trending": trending, "cast": cast, "retrospectives": retro,
                              "critic_feedback": feedback, "previous": prev}, thinking=True)

    out = refine("topics", generate, {"cast": cast}, on_round=on_round).to_dict()
    out["trending"] = trending
    return out
