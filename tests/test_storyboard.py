import xml.etree.ElementTree as ET

from studio import mocks, storyboard, writing


def _shots():
    return mocks._storyboard({})["shots"]


def test_every_pose_size_camera_renders_valid_svg():
    for aspect in ("16:9", "9:16"):
        for size in storyboard.SIZES:
            for cam in ("pov", "tripod", "handheld"):
                for pose in storyboard.ADULT_POSES:
                    figs = [{"who": "me", "pose": pose, "x": 0.4}, {"who": "baby", "pose": "baby_lie_back", "x": 0.7}]
                    svg = storyboard.render_shot({"shot_id": "S01", "camera": cam, "size": size, "figures": figs,
                                                  "action": "测试<&>", "line": "台词"}, aspect)
                    ET.fromstring(svg)  # well-formed (escaping works)


def test_portrait_header_wraps():
    svg = storyboard.render_shot(_shots()[0], "9:16")
    root = ET.fromstring(svg)
    bold = [t for t in root.iter("{http://www.w3.org/2000/svg}text") if t.get("font-weight") == "bold"]
    assert len(bold) == 2


def test_sanitize_drops_me_from_pov_and_clamps():
    out = writing.sanitize_shots({"shots": [{"shot_id": "S1", "camera": "pov", "size": "huge",
                                             "figures": [{"who": "me", "pose": "stand", "x": 3},
                                                         {"who": "baby", "pose": "nope", "x": -1}]}]})
    s = out["shots"][0]
    assert all(f["who"] != "me" for f in s["figures"])
    assert s["size"] in storyboard.SIZES
    assert all(0 <= f["x"] <= 1 for f in s["figures"])


def test_shotlist_groups_and_slates():
    sl = writing.make_shotlist(_shots())
    names = [b["block"] for b in sl["blocks"]]
    assert names[0].startswith("宝宝清醒")
    shots = [s for b in sl["blocks"] for s in b["steps"] if s["type"] == "shot"]
    assert len(shots) == len(_shots())
    assert all(s["shot_id"] in s["slate"] for s in shots)
    hand = next(b for b in sl["blocks"] if "爱人" in b["block"])
    assert any(s.get("shot_id") == "S06" for s in hand["steps"])
