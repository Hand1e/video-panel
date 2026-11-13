"""Fixed scoring rubrics. Scores are 0-10. `veto` dims must individually reach the pass score."""
from __future__ import annotations

import json

RUBRICS: dict[str, dict] = {
    "analysis": {
        "role": "严格的选题分析审稿人。你只相信有证据的结论。",
        "dimensions": {
            "evidence": "每条判断是否标注了数据/评论/搜索结果出处；无出处的结论直接扣分",
            "insight": "爆点拆解是否具体（指出前3秒、情绪点、结构），而不是泛泛而谈",
            "audience_need": "是否从评论区提炼出真实的观众需求/痛点",
            "feasibility": "可复刻性判断是否结合了演员档案（宝宝月龄、作息、爱人意愿）、成本、机位",
            "differentiation": "给出的'我家版本'角度是否真的和原视频不同且可执行",
            "falsifiable": "是否写明了结论在什么条件下不成立；置信度是否诚实",
        },
        "veto": ["evidence"],
    },
    "topics": {
        "role": "生活区账号主编，只做一个家庭能独立拍出来的内容。",
        "dimensions": {
            "heat": "与当下热点/长期需求的关联度",
            "feasibility": "按演员档案可拍性（宝宝作息、安全、场地、成本 < ¥200）",
            "differentiation": "切入角度是否独特",
            "series": "是否能延展成系列（如宝宝月龄里程碑）",
        },
        "veto": ["feasibility"],
    },
    "script": {
        "role": "短视频总编，专挑脚本毛病。",
        "dimensions": {
            "hook": "前3秒是否有强钩子（结果前置/冲突/反常识）",
            "structure": "钩子-冲突-过程-反转/干货-互动结尾 是否完整、节奏是否紧",
            "authenticity": "台词是否口语化、像真人说话，宝宝部分是否是'捕捉式'而非要求表演",
            "feasibility": "每个镜头一个家庭能否拍出来；宝宝镜头是否有备选方案",
            "safety_privacy": "宝宝安全、家庭隐私（门牌/快递单/小区名）是否考虑",
        },
        "veto": ["feasibility", "safety_privacy"],
    },
    "storyboard": {
        "role": "分镜导演与摄影指导。",
        "dimensions": {
            "coverage": "是否覆盖脚本每个段落，第一/第三人称机位分配是否合理",
            "shot_variety": "景别与机位是否有变化，避免连续同景别",
            "shootability": "单人（或爱人协助）是否能完成架机/换机位；拍摄顺序是否省事",
            "clarity": "每格说明是否清楚到能直接照着拍",
        },
        "veto": ["shootability"],
    },
    "cut": {
        "role": "平台审片编辑，按生活区爆款标准审片。",
        "dimensions": {
            "hook": "前3秒是否抓人",
            "pacing": "是否拖沓、是否有无意义停顿",
            "story": "主线是否清楚、结尾是否有情绪落点或互动引导",
            "camera_mix": "第一/第三人称切换是否服务叙事，切点是否自然",
            "subtitles": "字幕是否完整、关键词是否突出、是否有明显错字",
            "privacy": "是否露出门牌/快递单/小区名/宝宝敏感画面",
        },
        "veto": ["privacy"],
    },
}

STAGE_ORDER = ["analysis", "topics", "script", "storyboard", "shotlist", "footage", "cut"]


def critic_system_prompt(stage: str) -> str:
    r = RUBRICS[stage]
    dims = "\n".join(f"- {k}: {v}" for k, v in r["dimensions"].items())
    example = {
        "scores": {k: 6.5 for k in r["dimensions"]},
        "issues": [
            {"dim": next(iter(r["dimensions"])), "problem": "具体问题", "fix": "具体改法",
             "stage_owner": stage, "evidence": "定位（镜头号/时间戳/段落）"}
        ],
        "pass": False,
        "summary": "一句话总评",
    }
    return f"""你是{r['role']}
你在审阅工作台 `{stage}` 阶段的产出。按以下维度逐项 0-10 打分，严格、不客气，7 分代表"可以发布"。
{dims}

规则：
1. 每条 issue 必须给出可执行的 fix，并指明 stage_owner（问题根源属于哪个阶段：{', '.join(STAGE_ORDER)}）。
   若问题根源在上游（例如剪辑问题其实是脚本没有钩子），stage_owner 填上游阶段。
2. 只有所有维度 ≥ 7 才能 pass=true。
3. 不要因为是第几轮就放水；如果修改没有解决上轮问题，照样扣分。
只输出 json，格式示例：
{json.dumps(example, ensure_ascii=False)}"""
