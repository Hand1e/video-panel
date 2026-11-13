import datetime as dt

from studio import analysis, milestones, sources


def test_age_months_and_calendar():
    assert milestones.age_months("2026-07", dt.date(2026, 11, 13)) == 4
    assert milestones.age_months("bad", fallback=4) == 4
    cast = {"members": [{"id": "baby", "birth_month": "2026-07"}]}
    cal = milestones.calendar(cast, dt.date(2026, 11, 13))
    assert cal["age_months"] == 4
    assert "咯咯笑" in cal["now"]["milestones"]
    assert cal["next"] is milestones.MILESTONES[5]
    assert cal["seasonal"]  # November has entries
    assert milestones.calendar({"members": []})["age_months"] is None


def test_viral_metrics_levels():
    assert sources.viral_metrics(1000, None)["viral_ratio"] is None
    assert sources.viral_metrics(300_000, 50_000)["viral_level"] == "破圈爆款"
    assert sources.viral_metrics(60_000, 50_000)["viral_level"] == "选题带量"
    assert sources.viral_metrics(20_000, 50_000)["viral_level"] == "正常"
    m = sources.viral_metrics(100_000, 5_000_000)
    assert m["viral_level"] == "主要靠粉丝" and m["small_creator"] is False
    assert sources.viral_metrics(1_000_000, 300)["low_sample"] is True


def _raw(bvid, view, mid, tname="日常"):
    return {"bvid": bvid, "title": f"t{bvid}", "tname": tname, "owner": {"name": "u", "mid": mid},
            "duration": 60, "pubdate": 0, "stat": {"view": view}}


def test_trending_candidates_dedup_and_sort(monkeypatch):
    sources._FOLLOWERS.clear()

    def fake_get(url, **p):
        if "ranking" in url:
            return {"list": [_raw("A", 1000, 1), _raw("B", 10_000, 2)]}
        if "popular" in url:
            return {"list": [_raw("B", 1000, 2), _raw("D", 900_000, 4), _raw("C", 1000, 3, "游戏")]}
        if "relation" in url:
            return {"follower": {1: 10_000, 2: 1000, 4: 200}[p["vmid"]]}
        raise AssertionError(url)

    monkeypatch.setattr(sources, "_get", fake_get)
    tr = sources.trending_candidates(10)
    assert [it["bvid"] for it in tr["items"]] == ["B", "A", "D"]  # deduped, 游戏 filtered, by ratio, low-sample last
    assert tr["items"][0]["viral_ratio"] == 10 and tr["items"][0]["small_creator"]
    assert tr["errors"] == []


def test_daily_topics_returns_five_with_both_sources(monkeypatch):
    items = [{"bvid": f"X{i}", "title": f"热门{i}", "url": f"https://b/{i}", "category": "日常", "owner": "u",
              "list": "生活区排行", "stats": {"view": 1000 * (i + 1)},
              **sources.viral_metrics(1000 * (i + 1), 1000)} for i in range(6)]
    monkeypatch.setattr(sources, "trending_candidates", lambda n=40: {"items": items, "errors": []})
    out = analysis.daily_topics()
    topics = out["best"]["topics"]
    assert len(topics) == analysis.TOPIC_COUNT == 5
    assert {t["source"] for t in topics} == {"trending", "milestone"}
    assert out["milestone_calendar"]["age_months"] is not None
    assert len(out["trending"]) == 6
