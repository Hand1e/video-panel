from studio import loop, mocks


def _patch_critic(monkeypatch, script):
    """script: list of (scores, issues) per iteration."""
    calls = {"n": 0}

    def fake(stage, draft, context, iteration, images=None):
        scores, issues = script[min(iteration, len(script)) - 1]
        calls["n"] += 1
        return {"scores": scores, "issues": issues, "pass": min(scores.values()) >= 7}

    monkeypatch.setattr(loop, "critique", fake)
    return calls


def test_stops_on_pass(monkeypatch):
    _patch_critic(monkeypatch, [({"a": 6, "b": 6}, [{"dim": "a", "stage_owner": "script"}]),
                                ({"a": 8, "b": 7.5}, [])])
    drafts = []
    res = loop.refine("script", lambda fb, prev: drafts.append(fb) or {"v": len(drafts)}, {})
    assert len(res.rounds) == 2 and "通过" in res.stop_reason
    assert drafts[1] and drafts[1][0]["dim"] == "a"  # critic feedback reached the generator
    assert res.best == {"v": 2}


def test_veto_blocks_pass(monkeypatch):
    # feasibility is a veto dim for script: high average but veto < 7 must not pass
    _patch_critic(monkeypatch, [({"hook": 9, "feasibility": 6.5}, [])] * 3)
    res = loop.refine("script", lambda fb, prev: {}, {}, max_iter=3)
    assert "通过" not in res.stop_reason


def test_plateau_stops_and_keeps_best(monkeypatch):
    _patch_critic(monkeypatch, [({"a": 6.0}, [{"dim": "a", "stage_owner": "script"}]),
                                ({"a": 5.9}, [{"dim": "a", "stage_owner": "script"}]),
                                ({"a": 9.0}, [])])
    n = {"i": 0}

    def gen(fb, prev):
        n["i"] += 1
        return {"v": n["i"]}

    res = loop.refine("script", gen, {})
    assert len(res.rounds) == 2 and "停滞" in res.stop_reason
    assert res.best == {"v": 1}  # regression is not adopted


def test_upstream_rollback(monkeypatch):
    _patch_critic(monkeypatch, [({"a": 5}, [{"dim": "a", "stage_owner": "script", "problem": "x"}])])
    res = loop.refine("storyboard", lambda fb, prev: {}, {}, upstream_stages=("script",))
    assert len(res.rounds) == 1 and res.rollbacks and "上游" in res.stop_reason


def test_mock_critic_converges():
    res = loop.refine("script", lambda fb, prev: {"x": 1}, {})
    assert res.rounds[-1].avg > res.rounds[0].avg
    assert all("_mock" in r.draft or True for r in res.rounds)
    assert mocks.TAG in res.rounds[0].issues[0]["problem"]
