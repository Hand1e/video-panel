"""End-to-end, demo mode: synthetic footage -> analyze -> options -> cut loop -> final render."""
import json
import subprocess
from pathlib import Path

import pytest

from studio import editing, footage, media, store


def _ffmpeg_ok():
    try:
        media.ffmpeg()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _ffmpeg_ok(), reason="ffmpeg not installed")


def _make_clip(path: Path, dur: float, pattern: str, clap_at: float, freq: int):
    # test pattern video + tone bursts ("speech") + a sharp click ("clap") at clap_at
    audio = (f"sine=f={freq}:d={dur}:sample_rate=16000,volume='if(lt(mod(t,3),1.6),0.6,0.0)':eval=frame[s];"
             f"aevalsrc='if(between(t,{clap_at},{clap_at + 0.03}),0.95*random(0),0)':d={dur}:s=16000[c];"
             f"[s][c]amix=inputs=2:normalize=0[a]")
    subprocess.run([media.ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    f"{pattern}=size=640x360:rate=30:duration={dur}", "-filter_complex", audio, "-map", "0:v",
                    "-map", "[a]", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", str(path)], check=True)


def test_footage_only_pipeline(tmp_path):
    pid = store.new_project("测试直剪", "footage_only")
    clips = [tmp_path / "a_tripod.mp4", tmp_path / "b_pov.mp4"]
    _make_clip(clips[0], 8, "testsrc2", 2.2, 440)
    _make_clip(clips[1], 7, "testsrc", 2.0, 660)

    f = footage.analyze_all(pid, [str(c) for c in clips])
    assert len(f["clips"]) == 2 and not f["errors"]
    c1 = f["clips"][0]
    assert c1["info"]["duration"] > 7 and c1["frames"] and c1["speech_ranges"]
    assert any(abs(t - 2.2) < 0.2 for t in c1["claps"]), c1["claps"]

    opts = editing.edit_options(pid, "抖音 15 秒")["options"]
    assert {o["id"] for o in opts} == {"A", "B", "C"}

    out = editing.cut(pid, opts[1])
    assert out["rounds"] and out["best"]["segments"]
    final = Path(out["final"]["video"])
    assert final.exists() and final.stat().st_size > 10_000
    info = media.probe(final)
    assert info["width"] == 1080 and info["height"] == 1920  # option B is 9:16
    assert abs(info["duration"] - out["best"]["duration_s"]) < 1.0
    srt = Path(out["final"]["srt"]).read_text(encoding="utf-8")
    assert "-->" in srt
    assert json.loads((store.project_dir(pid) / "cut.json").read_text(encoding="utf-8"))["final"]
