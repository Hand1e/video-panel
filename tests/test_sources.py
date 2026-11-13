from studio import sources


def test_detect_platforms():
    assert sources.detect("https://www.bilibili.com/video/BV1xx411c7mD?p=1")[0] == "bilibili"
    assert sources.detect("看看 https://v.douyin.com/abc/")[0] == "douyin"
    assert sources.detect("https://www.xiaohongshu.com/explore/66aa")[0] == "xiaohongshu"
    assert sources.detect("https://youtu.be/dQw4w9WgXcQ")[0] == "youtube"
    assert sources.detect("4个月宝宝 第一次笑")[0] == "keyword"


def test_bili_video_parsing(monkeypatch):
    fake = {"aid": 1, "title": "宝宝第一次笑", "pubdate": 0, "duration": 61, "owner": {"name": "u"},
            "stat": {"view": 1000, "like": 100, "favorite": 50, "coin": 10, "share": 5, "reply": 20, "danmaku": 3}}
    monkeypatch.setattr(sources, "_get", lambda url, **kw: fake)
    v = sources.bili_video("BV1xx411c7mD")
    assert v["derived"]["like_rate"] == 0.1 and v["derived"]["favorite_rate"] == 0.05
    assert v["stats"]["view"] == 1000 and v["aid"] == 1
