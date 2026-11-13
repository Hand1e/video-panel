"""Baby month-age topic calendar: evergreen, always-shootable topics that form a natural series.

Milestone ages are typical ranges, not targets — every baby differs. Topics are phrased as
"record / try", never "train to achieve", and carry the safety notes the script stage must honour.
"""
from __future__ import annotations

import datetime as dt

# month -> typical milestones and topic seeds (0-12 months)
MILESTONES: dict[int, dict] = {
    3: {"milestones": ["趴着抬头更稳", "笑出声", "手放进嘴里", "追视移动的东西"],
        "ideas": ["第一次笑出声的瞬间", "趴着抬头挑战（大人全程在旁）", "宝宝发现自己的手"],
        "safety": ["趴卧必须清醒且大人在旁"]},
    4: {"milestones": ["咯咯笑", "主动抓握玩具", "可能开始翻身", "对声音转头"],
        "ideas": ["试了 N 种方法逗笑宝宝", "第一次抓住玩具", "翻身前的努力（记录，不催）", "宝宝听到爸爸/妈妈声音的反应对比"],
        "safety": ["翻身期不要把宝宝单独留在床/沙发上"]},
    5: {"milestones": ["翻身", "抓自己的脚", "开始认生", "咿咿呀呀"],
        "ideas": ["翻身成功纪念", "宝宝第一次抓到脚", "陌生人 vs 爸妈抱的反应", "和宝宝'聊天'实录"],
        "safety": ["翻身后注意口鼻不被遮挡"]},
    6: {"milestones": ["半岁", "按医生建议开始添加辅食", "扶着能坐一会儿", "可能冒出第一颗牙"],
        "ideas": ["半岁纪念：6 个月变化对比", "第一口辅食的表情（遵医嘱）", "新手爸妈辅食翻车实录", "第一颗牙"],
        "safety": ["辅食时间与种类遵医嘱", "坐姿时身后要有保护"]},
    7: {"milestones": ["独坐更稳", "两手换着拿东西", "听到名字有反应"],
        "ideas": ["叫名字测试", "宝宝第一次自己坐着玩", "玩具换手小游戏"],
        "safety": ["独坐周围放软垫"]},
    8: {"milestones": ["开始爬（个体差异大）", "认生明显", "爱玩躲猫猫"],
        "ideas": ["躲猫猫反应合集", "第一次往前爬", "家里'防爬'改造"],
        "safety": ["插座、桌角、小物件做好防护"]},
    9: {"milestones": ["扶着站", "拇指食指捏东西", "模仿动作"],
        "ideas": ["第一次扶站", "宝宝模仿爸爸做鬼脸", "捏小泡芙挑战（遵医嘱）"],
        "safety": ["扶站时防磕碰"]},
    10: {"milestones": ["扶着走", "挥手再见", "理解简单指令"],
         "ideas": ["第一次挥手再见", "扶着走去找妈妈", "宝宝听懂的第一个词"],
         "safety": ["家具边角防护"]},
    11: {"milestones": ["短暂独站", "有意识叫爸爸/妈妈（个体差异大）"],
         "ideas": ["先叫爸爸还是妈妈", "独站几秒挑战", "周岁倒计时"],
         "safety": ["独站时大人在伸手可及处"]},
    12: {"milestones": ["周岁", "可能迈出第一步", "抓周"],
         "ideas": ["周岁纪念：一年对比", "抓周", "第一步"],
         "safety": ["抓周物品避免小件"]},
}

# life events that are not developmental milestones
EVENTS = {
    3: ["百天纪念照"], 4: ["第一次出远门/回老家"], 6: ["半岁纪念"], 12: ["周岁"],
}

# calendar-month occasions (any age)
SEASONAL = {
    1: ["宝宝第一个春节（视年份）", "冬季保暖"], 2: ["春节走亲戚", "元宵"], 3: ["春天第一次踏青"],
    5: ["母亲节：爸爸带娃的一天"], 6: ["父亲节", "夏天防蚊防晒"], 7: ["夏天洗澡/游泳（宝宝专用）"],
    9: ["中秋"], 10: ["国庆出行"], 11: ["入冬：宝宝的第一个冬天", "换季穿衣"], 12: ["圣诞/跨年家庭小仪式"],
}


def age_months(birth_month: str | None, today: dt.date | None = None, fallback: int | None = None) -> int | None:
    """birth_month 'YYYY-MM' -> whole months of age today."""
    today = today or dt.date.today()
    try:
        y, m = (int(x) for x in str(birth_month).split("-")[:2])
    except (TypeError, ValueError):
        return fallback
    return max((today.year - y) * 12 + (today.month - m), 0)


def calendar(cast: dict, today: dt.date | None = None) -> dict:
    """Topic seeds for the current month of age + a heads-up for next month (prepare to capture it)."""
    today = today or dt.date.today()
    baby = next((m for m in cast.get("members", []) if m.get("id") == "baby"), None)
    if not baby:
        return {"age_months": None, "now": None, "next": None, "events": [], "seasonal": SEASONAL.get(today.month, [])}
    age = age_months(baby.get("birth_month"), today, baby.get("age_months"))
    clamp = lambda a: min(max(a, min(MILESTONES)), max(MILESTONES))
    now = MILESTONES.get(clamp(age)) if age is not None else None
    nxt = MILESTONES.get(clamp(age + 1)) if age is not None and age < max(MILESTONES) else None
    return {
        "age_months": age,
        "now": now,
        "next": nxt,
        "events": EVENTS.get(age, []) if age is not None else [],
        "seasonal": SEASONAL.get(today.month, []),
        "note": "里程碑是常见范围，每个宝宝不同：选题写成'记录/尝试'，不要写成'训练达标'。",
    }
