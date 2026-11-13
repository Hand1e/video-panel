"""Data sources: Bilibili public APIs, DeepSeek Search/Fetch, YouTube Data API, screenshots."""
from __future__ import annotations

import re
import time
from typing import Any

import requests

from . import config

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36",
      "Referer": "https://www.bilibili.com/"}
LIFE_KEYWORDS = ("生活", "日常", "亲子", "育儿", "家庭", "美食", "家居", "vlog", "Vlog", "情感", "手工", "萌宠", "搞笑")

PLATFORM_PATTERNS = [
    ("bilibili", re.compile(r"(BV[0-9A-Za-z]{10})")),
    ("bilibili_short", re.compile(r"b23\.tv/\w+")),
    ("youtube", re.compile(r"(?:youtube\.com/(?:watch\?v=|shorts/)|youtu\.be/)([\w-]{11})")),
    ("douyin", re.compile(r"douyin\.com|iesdouyin\.com")),
    ("xiaohongshu", re.compile(r"xiaohongshu\.com|xhslink\.com")),
    ("kuaishou", re.compile(r"kuaishou\.com|gifshow\.com")),
]


def detect(text: str) -> tuple[str, str | None]:
    for name, pat in PLATFORM_PATTERNS:
        m = pat.search(text)
        if m:
            return name, (m.group(1) if m.groups() else m.group(0))
    return ("keyword", None) if not re.match(r"https?://", text.strip()) else ("web", None)


def _get(url: str, **params: Any) -> dict:
    r = requests.get(url, params=params, headers=UA, timeout=20)
    r.raise_for_status()
    j = r.json()
    if j.get("code", 0) != 0:
        raise RuntimeError(f"bilibili api {j.get('code')}: {j.get('message')}")
    return j["data"]


# ---------------- Bilibili ----------------

def bili_resolve_short(url: str) -> str | None:
    if not url.startswith("http"):
        url = "https://" + url
    r = requests.get(url, headers=UA, timeout=15, allow_redirects=True)
    m = re.search(r"(BV[0-9A-Za-z]{10})", r.url)
    return m.group(1) if m else None


def bili_video(bvid: str) -> dict:
    d = _get("https://api.bilibili.com/x/web-interface/view", bvid=bvid)
    s = d["stat"]
    view = max(s.get("view", 0), 1)
    age_h = max((time.time() - d.get("pubdate", time.time())) / 3600, 0.1)
    return {
        "platform": "bilibili",
        "url": f"https://www.bilibili.com/video/{bvid}",
        "bvid": bvid,
        "aid": d["aid"],
        "title": d["title"],
        "desc": d.get("desc", ""),
        "owner": d.get("owner", {}).get("name"),
        "category": d.get("tname_v2") or d.get("tname"),
        "duration_s": d.get("duration"),
        "pubdate": d.get("pubdate"),
        "cover": d.get("pic"),
        "stats": {k: s.get(k, 0) for k in ("view", "like", "coin", "favorite", "share", "reply", "danmaku")},
        "derived": {
            "hours_since_publish": round(age_h, 1),
            "views_per_hour": round(view / age_h, 1),
            "like_rate": round(s.get("like", 0) / view, 4),
            "favorite_rate": round(s.get("favorite", 0) / view, 4),
            "coin_rate": round(s.get("coin", 0) / view, 4),
            "share_rate": round(s.get("share", 0) / view, 4),
            "reply_rate": round(s.get("reply", 0) / view, 4),
        },
        "owner_mid": d.get("owner", {}).get("mid"),
        "source": "B站公开接口 x/web-interface/view",
    }


def bili_comments(aid: int, n: int = 30) -> list[dict]:
    out: list[dict] = []
    for pn in (1, 2):
        try:
            d = _get("https://api.bilibili.com/x/v2/reply", type=1, oid=aid, sort=1, ps=20, pn=pn)
        except Exception:
            break
        for x in d.get("replies") or []:
            out.append({"like": x.get("like", 0), "text": x["content"]["message"][:200],
                        "replies": x.get("rcount", 0)})
        if len(out) >= n:
            break
    return out[:n]


def _bili_item(v: dict, source: str) -> dict:
    s = v["stat"]
    cat = " ".join(str(v.get(k, "")) for k in ("tname", "tnamev2", "pid_name_v2")).strip()
    return {
        "platform": "bilibili", "bvid": v["bvid"], "title": v["title"], "category": cat,
        "owner": v["owner"]["name"], "owner_mid": v["owner"].get("mid"), "duration_s": v.get("duration"),
        "pubdate": v.get("pubdate"), "cover": v.get("pic"), "url": f"https://www.bilibili.com/video/{v['bvid']}",
        "stats": {"view": s.get("view", 0), "like": s.get("like", 0), "favorite": s.get("favorite", 0),
                  "reply": s.get("reply", 0)},
        "rcmd_reason": (v.get("rcmd_reason") or {}).get("content", "") if isinstance(v.get("rcmd_reason"), dict) else "",
        "list": source,
    }


def bili_popular(n: int = 50, life_only: bool = True) -> list[dict]:
    """全站热门 (filtered to life-ish categories by keyword)."""
    items: list[dict] = []
    for pn in range(1, 4):
        d = _get("https://api.bilibili.com/x/web-interface/popular", ps=20, pn=pn)
        for v in d.get("list", []):
            it = _bili_item(v, "全站热门")
            if life_only and not any(k in it["category"] for k in LIFE_KEYWORDS):
                continue
            items.append(it)
        if len(items) >= n:
            break
    return items[:n]


BILI_LIFE_RID = 160  # 生活分区（含 日常 / 亲子 / 搞笑 / 美食圈 等子区）


def bili_life_ranking(n: int = 60) -> list[dict]:
    """生活分区排行榜 (3-day window) — more on-topic than the global popular list."""
    d = _get("https://api.bilibili.com/x/web-interface/ranking/v2", rid=BILI_LIFE_RID, type="all")
    return [_bili_item(v, "生活区排行") for v in d.get("list", [])[:n]]


_FOLLOWERS: dict[int, int | None] = {}


def bili_followers(mid: int | None) -> int | None:
    if not mid:
        return None
    if mid not in _FOLLOWERS:
        try:
            _FOLLOWERS[mid] = int(_get("https://api.bilibili.com/x/relation/stat", vmid=mid).get("follower", 0))
        except Exception:
            _FOLLOWERS[mid] = None
    return _FOLLOWERS[mid]


MIN_FOLLOWERS = 1000


def viral_metrics(views: int, followers: int | None) -> dict:
    """爆款系数 = 播放 / 粉丝数. >1 means the topic travelled beyond the creator's own audience —
    that is the signal a small new account can actually borrow (big creators' views are mostly their fans)."""
    if not followers:
        return {"followers": followers, "viral_ratio": None, "viral_level": "未知"}
    r = views / followers
    if followers < MIN_FOLLOWERS:  # tiny accounts: ratio is noise (flukes, reposts, new alts)
        return {"followers": followers, "viral_ratio": round(r, 2), "viral_level": "粉丝过少·仅供参考",
                "small_creator": True, "low_sample": True}
    level = ("破圈爆款" if r >= 3 else "选题带量" if r >= 1 else "正常" if r >= 0.2 else "主要靠粉丝")
    return {"followers": followers, "viral_ratio": round(r, 2), "viral_level": level,
            "small_creator": followers < 100_000}


def trending_candidates(n: int = 40) -> dict:
    """Life-area ranking + filtered global popular, de-duplicated, enriched with 爆款系数, ranked so that
    topic-driven hits (high ratio, small creators) come first."""
    from concurrent.futures import ThreadPoolExecutor

    items, errors, seen = [], [], set()
    for fn in (bili_life_ranking, bili_popular):
        try:
            for it in fn():
                if it["bvid"] not in seen:
                    seen.add(it["bvid"])
                    items.append(it)
        except Exception as e:
            errors.append(f"{fn.__name__}: {e}")
    items = items[: max(n, 1) * 2]
    with ThreadPoolExecutor(max_workers=4) as ex:  # gentle: B站 returns 412 when hammered
        followers = list(ex.map(lambda it: bili_followers(it.get("owner_mid")), items))
    now = time.time()
    for it, f in zip(items, followers):
        it.update(viral_metrics(it["stats"]["view"], f))
        if it.get("pubdate"):
            it["views_per_hour"] = round(it["stats"]["view"] / max((now - it["pubdate"]) / 3600, 0.5), 1)
    # capped so one 3000x fluke does not drown out steady 5-20x topic-driven hits; low-sample last
    items.sort(key=lambda it: (bool(it.get("low_sample")), -min(it.get("viral_ratio") or 0, 50)))
    return {"items": items[:n], "errors": errors,
            "note": "按爆款系数（播放/粉丝）排序；高系数 = 选题本身带量，最值得小号借鉴"}


# ---------------- DeepSeek Search / Fetch ----------------

def ds_search(query: str, count: int = 10, need_content: bool = False) -> list[dict]:
    if config.mock_llm():
        return []
    r = requests.post(f"{config.DEEPSEEK_BASE_URL}/v1/tools/search",
                      headers={"Authorization": f"Bearer {config.DEEPSEEK_API_KEY}"},
                      json={"query": query[:128], "count": count, "need_content": need_content}, timeout=60)
    r.raise_for_status()
    return [{k: x.get(k) for k in ("title", "url", "summary", "site_name", "date", "rerank_score")}
            for x in r.json().get("results", [])]


def ds_fetch(url: str) -> dict | None:
    if config.mock_llm():
        return None
    r = requests.post(f"{config.DEEPSEEK_BASE_URL}/v1/tools/fetch",
                      headers={"Authorization": f"Bearer {config.DEEPSEEK_API_KEY}"},
                      json={"url": url}, timeout=60)
    if r.status_code != 200:
        return None
    j = r.json()
    return {"title": j.get("title"), "content": (j.get("content") or "")[:12000]}


def competitor_search(topic: str, days: int = 7) -> list[dict]:
    """Same-topic saturation check across platforms via DeepSeek Search."""
    after = time.strftime("%Y-%m-%d", time.localtime(time.time() - days * 86400))
    sites = "site:bilibili.com OR site:xiaohongshu.com OR site:douyin.com OR site:kuaishou.com"
    try:
        return ds_search(f"{topic} {sites} after:{after}", count=20)
    except Exception as e:
        return [{"error": str(e)}]


# ---------------- YouTube ----------------

def youtube_video(vid: str) -> dict | None:
    if not config.YOUTUBE_API_KEY:
        return None
    r = requests.get("https://www.googleapis.com/youtube/v3/videos",
                     params={"id": vid, "part": "snippet,statistics,contentDetails", "key": config.YOUTUBE_API_KEY},
                     timeout=20)
    r.raise_for_status()
    items = r.json().get("items", [])
    if not items:
        return None
    it = items[0]
    st = {k: int(v) for k, v in it["statistics"].items() if v.isdigit()}
    view = max(st.get("viewCount", 0), 1)
    return {"platform": "youtube", "url": f"https://youtu.be/{vid}", "title": it["snippet"]["title"],
            "desc": it["snippet"].get("description", "")[:1000], "owner": it["snippet"].get("channelTitle"),
            "stats": st, "derived": {"like_rate": round(st.get("likeCount", 0) / view, 4)},
            "source": "YouTube Data API"}


# ---------------- unified resolver ----------------

def resolve_source(text: str, screenshots: list[str] | None = None) -> dict:
    """Return a SourceBundle: what we could fetch + an honest list of gaps."""
    text = text.strip()
    platform, ident = detect(text)
    bundle: dict = {"input": text, "platform": platform, "video": None, "comments": [], "page": None,
                    "screenshots": screenshots or [], "competitors": [], "gaps": []}
    try:
        if platform == "bilibili_short":
            ident = bili_resolve_short(ident)
            platform = bundle["platform"] = "bilibili"
        if platform == "bilibili" and ident:
            v = bili_video(ident)
            v["derived"].update(viral_metrics(v["stats"]["view"], bili_followers(v.get("owner_mid"))))
            bundle["video"] = v
            bundle["comments"] = bili_comments(v["aid"])
        elif platform == "youtube" and ident:
            bundle["video"] = youtube_video(ident)
            if not bundle["video"]:
                bundle["gaps"].append("未配置 YOUTUBE_API_KEY，无法获取 YouTube 数据")
        elif platform in ("douyin", "xiaohongshu", "kuaishou", "web"):
            bundle["page"] = ds_fetch(text)
            if not bundle["page"] or len(bundle["page"].get("content", "")) < 200:
                bundle["gaps"].append(f"{platform} 页面抓取失败或需要登录；请上传视频页/数据栏/评论区截图")
    except Exception as e:
        bundle["gaps"].append(f"数据获取失败: {e}")

    topic = (bundle["video"] or {}).get("title") or (bundle["page"] or {}).get("title") or text
    bundle["topic"] = topic
    bundle["competitors"] = competitor_search(topic) if not config.mock_llm() else []
    if config.mock_llm():
        bundle["gaps"].append("演示模式：未配置 DEEPSEEK_API_KEY，同类视频搜索未执行")
    if platform != "bilibili" and not screenshots and not bundle["video"] and not bundle["page"]:
        bundle["gaps"].append("没有可用的一手数据")
    return bundle
