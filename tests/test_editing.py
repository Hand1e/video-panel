import numpy as np

from studio import asr, editing, media


def _footage():
    return {"clips": [{"clip_id": "C01", "info": {"duration": 10.0},
                       "speech_ranges": [{"start": 2.0, "end": 4.0, "text": "你好"}], "tags": {}}]}


def test_validate_timeline_clamps_and_snaps():
    tl = {"segments": [
        {"clip": "C01", "in": 2.2, "out": 3.8, "zoom": 3, "speed": 9},  # snaps to 2.0-4.0, clamps
        {"clip": "C99", "in": 0, "out": 1},                              # unknown clip
        {"clip": "C01", "in": 9.9, "out": 50},                           # too short after clamp
        {"clip": "C01", "in": "x", "out": 1},                            # not a number
    ]}
    out = editing.validate_timeline(tl, _footage())
    assert len(out["segments"]) == 1 and len(out["dropped"]) == 3
    s = out["segments"][0]
    assert (s["in"], s["out"]) == (2.0, 4.0)
    assert s["zoom"] == 1.4 and s["speed"] == 2.0
    assert out["duration_s"] == 1.0


def test_beat_snap():
    tl = {"segments": [{"clip": "C01", "in": 5.0, "out": 6.9}]}
    out = editing.validate_timeline(tl, _footage(), beats=[1.0, 2.0, 3.0])
    assert out["segments"][0]["out"] == 7.0


def test_speech_ranges_merges_and_drops_fillers():
    a = {"sentences": [{"start": 0.0, "end": 1.0, "text": "嗯"}, {"start": 1.2, "end": 2.0, "text": "今天"},
                       {"start": 2.2, "end": 3.0, "text": "带娃"}, {"start": 5.0, "end": 6.0, "text": "出门"}]}
    r = asr.speech_ranges(a)
    assert len(r) == 2 and r[0]["start"] == 1.12 and r[0]["end"] == 3.12 and "嗯" not in r[0]["text"]


def test_sync_offset_finds_shift():
    rng = np.random.default_rng(0)
    base = np.abs(rng.normal(0.01, 0.003, 1200))
    for t in (100, 340, 610, 900):
        base[t:t + 3] += 1.0
    shift = 40  # frames of 50ms -> 2.0s ; B starts 2s later than A
    a, b = base, base[shift:]
    off, conf = media.sync_offset(a, b)
    assert abs(abs(off) - 2.0) < 0.06 and conf > 0.3
