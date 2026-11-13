"""ffmpeg-based media utilities. Pure functions; no LLM here."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np

from . import config

ENV_HOP = 0.05  # seconds per envelope sample


def _bin(name: str, default: str) -> str:
    if shutil.which(default):
        return default
    links = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links" / f"{name}.exe"
    if links.exists():
        return str(links)
    pkgs = links.parent.parent / "Packages"
    if pkgs.is_dir():
        for hit in sorted(pkgs.glob(f"*FFmpeg*/**/bin/{name}.exe")):
            return str(hit)
    raise FileNotFoundError(f"{name} not found; install ffmpeg or set {name.upper()} env var")


def ffmpeg() -> str:
    return _bin("ffmpeg", config.FFMPEG)


def ffprobe() -> str:
    return _bin("ffprobe", config.FFPROBE)


def run(args: list[str], cwd: str | Path | None = None, timeout: float = 3600) -> subprocess.CompletedProcess:
    # stdin=DEVNULL (+ -nostdin): ffmpeg otherwise reads the inherited console for interactive keys and can
    # block indefinitely when several run in parallel threads.
    args = list(args)
    if Path(args[0]).stem.lower() == "ffmpeg" and "-nostdin" not in args:
        args.insert(1, "-nostdin")
    try:
        p = subprocess.run(args, capture_output=True, cwd=cwd, stdin=subprocess.DEVNULL, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{Path(args[0]).name} timed out after {timeout:.0f}s")
    if p.returncode != 0:
        raise RuntimeError(f"{Path(args[0]).name} failed: {p.stderr.decode('utf-8', 'replace')[-1500:]}")
    return p


def probe(path: str | Path) -> dict:
    p = run([ffprobe(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    j = json.loads(p.stdout)
    v = next((s for s in j["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in j["streams"] if s["codec_type"] == "audio"), None)
    fmt = j.get("format", {})
    out = {"path": str(path), "duration": float(fmt.get("duration") or 0), "has_audio": a is not None,
           "creation_time": (fmt.get("tags") or {}).get("creation_time")}
    if v:
        w, h = int(v.get("width", 0)), int(v.get("height", 0))
        rot = 0
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                rot = int(sd["rotation"])
        rot = int((v.get("tags") or {}).get("rotate", rot))
        if abs(rot) in (90, 270):
            w, h = h, w
        num, _, den = (v.get("avg_frame_rate") or "30/1").partition("/")
        fps = float(num) / float(den or 1) if float(den or 1) else 30.0
        out.update(width=w, height=h, fps=round(fps, 2), orientation="portrait" if h > w else "landscape")
    return out


def extract_audio(src: str | Path, dst: str | Path, sr: int = 16000, fmt: str = "wav",
                  start: float | None = None, dur: float | None = None, bitrate: str = "32k") -> Path:
    args = [ffmpeg(), "-y", "-v", "error"]
    if start is not None:
        args += ["-ss", f"{start:.3f}"]
    args += ["-i", str(src)]
    if dur is not None:
        args += ["-t", f"{dur:.3f}"]
    args += ["-vn", "-ac", "1", "-ar", str(sr)]
    args += (["-c:a", "libmp3lame", "-b:a", bitrate] if fmt == "mp3" else ["-c:a", "pcm_s16le"])
    run(args + [str(dst)])
    return Path(dst)


def pcm(src: str | Path, sr: int = 16000) -> np.ndarray:
    p = run([ffmpeg(), "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"])
    return np.frombuffer(p.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def envelope(samples: np.ndarray, sr: int = 16000, hop: float = ENV_HOP) -> np.ndarray:
    n = int(sr * hop)
    if len(samples) < n:
        return np.zeros(1, dtype=np.float32)
    frames = samples[: len(samples) // n * n].reshape(-1, n)
    return np.sqrt((frames ** 2).mean(axis=1) + 1e-12)


def to_db(env: np.ndarray) -> np.ndarray:
    return 20 * np.log10(env + 1e-9)


def silences(env: np.ndarray, min_len: float = 0.6, rel_db: float = -32.0) -> list[tuple[float, float]]:
    """Silence = below (95th-percentile loudness + rel_db) for at least min_len seconds."""
    if env.size < 2:
        return []
    db = to_db(env)
    thr = np.percentile(db, 95) + rel_db
    quiet = db < thr
    out, start = [], None
    for i, q in enumerate(quiet):
        if q and start is None:
            start = i
        elif not q and start is not None:
            if (i - start) * ENV_HOP >= min_len:
                out.append((round(start * ENV_HOP, 2), round(i * ENV_HOP, 2)))
            start = None
    if start is not None and (len(quiet) - start) * ENV_HOP >= min_len:
        out.append((round(start * ENV_HOP, 2), round(len(quiet) * ENV_HOP, 2)))
    return out


def claps(env: np.ndarray, k: float = 6.0) -> list[float]:
    """Hand-clap slates: a sharp attack (quiet -> loud within one hop) that decays again within ~150 ms.
    The decay test is what separates a clap from someone starting to talk / music starting."""
    if env.size < 4:
        return []
    db = np.maximum(to_db(env), -70.0)  # realistic noise floor; digital silence would dominate the stats
    jump = np.diff(db)
    thr = max(np.percentile(jump, 99.0), k * (np.std(jump) + 1e-6) * 0.5, 18.0)
    out: list[float] = []
    for i in np.where(jump > thr)[0]:
        peak = db[i + 1]
        tail = db[i + 2:i + 5]
        if tail.size and peak - tail.min() < 10:  # sustained -> not a clap
            continue
        t = round(float(i + 1) * ENV_HOP, 2)
        if not out or t - out[-1] > 1.0:
            out.append(t)
    return out


def sync_offset(env_a: np.ndarray, env_b: np.ndarray, max_shift_s: float = 120.0) -> tuple[float, float]:
    """Offset (s) such that time t in A == t - offset in B; plus a confidence 0-1 (normalized peak)."""
    def onset(e):
        d = np.maximum(np.diff(to_db(e), prepend=to_db(e)[:1]), 0)
        return (d - d.mean()) / (d.std() + 1e-9)

    a, b = onset(env_a), onset(env_b)
    n = 1 << int(np.ceil(np.log2(len(a) + len(b))))
    corr = np.fft.irfft(np.fft.rfft(a, n) * np.conj(np.fft.rfft(b, n)), n)
    max_shift = int(max_shift_s / ENV_HOP)
    lags = np.concatenate([np.arange(0, max_shift + 1), np.arange(-max_shift, 0)])
    vals = np.concatenate([corr[: max_shift + 1], corr[-max_shift:]])
    i = int(np.argmax(vals))
    conf = float(vals[i] / (np.sqrt((a ** 2).sum() * (b ** 2).sum()) + 1e-9))
    return round(lags[i] * ENV_HOP, 2), round(max(min(conf * 4, 1.0), 0.0), 2)


def beats(samples: np.ndarray, sr: int = 16000) -> dict:
    """Very small beat tracker: onset envelope + autocorrelation tempo + phase alignment."""
    hop = 0.01
    env = envelope(samples, sr, hop)
    d = np.maximum(np.diff(to_db(env), prepend=0), 0)
    d = d - d.mean()
    ac = np.correlate(d, d, mode="full")[len(d) - 1:]
    lo, hi = int(60 / 180 / hop), int(60 / 70 / hop)
    if hi >= len(ac):
        return {"bpm": None, "beats": []}
    period = lo + int(np.argmax(ac[lo:hi]))
    phases = [d[p::period].sum() for p in range(period)]
    phase = int(np.argmax(phases))
    times = [round((phase + k * period) * hop, 3) for k in range((len(d) - phase) // period)]
    return {"bpm": round(60 / (period * hop), 1), "beats": times}


def sample_frames(src: str | Path, out_dir: str | Path, times: list[float], width: int = 512) -> list[dict]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    res = []
    for t in times:
        dst = out_dir / f"f_{t:08.2f}.jpg"
        if not dst.exists():
            try:
                run([ffmpeg(), "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(src), "-frames:v", "1",
                     "-vf", f"scale={width}:-2", "-q:v", "4", str(dst)], timeout=120)
            except RuntimeError:
                continue
        if dst.exists():
            res.append({"t": round(t, 2), "path": str(dst)})
    return res


def frame_metrics(frames: list[dict]) -> list[dict]:
    """Blur (Laplacian variance), brightness, inter-frame change (shake/motion proxy)."""
    import cv2

    prev = None
    for f in frames:
        img = cv2.imdecode(np.fromfile(f["path"], dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        small = cv2.resize(img, (160, 90))
        f["blur"] = round(float(cv2.Laplacian(img, cv2.CV_64F).var()), 1)
        f["brightness"] = round(float(img.mean()), 1)
        f["change"] = round(float(np.abs(small.astype(np.int16) - prev).mean()), 1) if prev is not None else 0.0
        prev = small.astype(np.int16)
    return frames


def scene_cuts(src: str | Path, threshold: float = 0.35) -> list[float]:
    p = subprocess.run([ffmpeg(), "-nostdin", "-v", "info", "-i", str(src), "-vf",
                        f"scale=320:-2,select='gt(scene,{threshold})',showinfo", "-an", "-f", "null", "-"],
                       capture_output=True, stdin=subprocess.DEVNULL, timeout=3600)
    return [round(float(x), 2) for x in re.findall(rb"pts_time:([0-9.]+)", p.stderr)]


# ---------------- rendering ----------------

def render_segments(segments: list[dict], out: str | Path, *, width: int, height: int, fps: int = 30,
                    workdir: str | Path, preset: str = "veryfast", crf: int = 22,
                    subtitles: str | None = None, bgm: str | None = None, bgm_volume: float = 0.12,
                    progress=None) -> Path:
    """Each segment: {src, in, out, zoom?, speed?, audio_src?, audio_in?, mute?}.
    `audio_src/audio_in` let a segment show one camera while playing another source's audio
    (J/L cuts, or using the better mic of the tripod camera under POV footage)."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    parts = []
    for i, s in enumerate(segments):
        dur = max(float(s["out"]) - float(s["in"]), 0.1)
        speed = float(s.get("speed", 1.0) or 1.0)
        zoom = float(s.get("zoom", 1.0) or 1.0)
        vf = [f"scale={width}:{height}:force_original_aspect_ratio=increase", f"crop={width}:{height}"]
        if zoom > 1.01:
            vf += [f"crop=iw/{zoom:.3f}:ih/{zoom:.3f}", f"scale={width}:{height}"]
        if abs(speed - 1) > 0.01:
            vf.append(f"setpts=PTS/{speed:.3f}")
        vf += [f"fps={fps}", "format=yuv420p", "setsar=1"]
        out_dur = dur / speed
        args = [ffmpeg(), "-y", "-v", "error", "-ss", f"{float(s['in']):.3f}", "-t", f"{dur:.3f}", "-i", s["src"]]
        a_src = s.get("audio_src")
        has_audio = bool(s.get("has_audio", True)) and not s.get("mute")
        if a_src:
            args += ["-ss", f"{float(s.get('audio_in', s['in'])):.3f}", "-t", f"{out_dur:.3f}", "-i", a_src]
            amap = "1:a:0"
        elif has_audio:
            amap = "0:a:0"
        else:
            args += ["-f", "lavfi", "-t", f"{out_dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
            amap = "1:a:0"
        af = []
        if abs(speed - 1) > 0.01 and not a_src and has_audio:
            af.append(f"atempo={min(max(speed, 0.5), 2.0):.3f}")
        af += ["aresample=48000", "aformat=channel_layouts=stereo"]
        dst = workdir / f"seg_{i:03d}.mp4"
        args += ["-map", "0:v:0", "-map", amap, "-vf", ",".join(vf), "-af", ",".join(af),
                 "-t", f"{out_dur:.3f}", "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
                 "-c:a", "aac", "-b:a", "160k", str(dst)]
        run(args)
        parts.append(dst)
        if progress:
            progress(f"渲染片段 {i + 1}/{len(segments)}")

    lst = workdir / "concat.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
    joined = workdir / "joined.mp4"
    run([ffmpeg(), "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst.name, "-c", "copy", joined.name],
        cwd=workdir)

    out = Path(out)
    vf_final, inputs, filt = [], ["-i", joined.name], []
    if subtitles:
        sub = Path(subtitles)
        shutil.copy(sub, workdir / sub.name)  # relative path avoids Windows drive-letter escaping in filter
        vf_final.append(f"subtitles={sub.name}")
    if bgm:
        inputs += ["-stream_loop", "-1", "-i", str(bgm)]
        filt = ["-filter_complex",
                f"[1:a]volume={bgm_volume}[b];[0:a][b]amix=inputs=2:duration=first:dropout_transition=0[a]",
                "-map", "0:v", "-map", "[a]"]
    args = [ffmpeg(), "-y", "-v", "error", *inputs, *filt]
    if vf_final:
        args += ["-vf", ",".join(vf_final), "-c:v", "libx264", "-preset", preset, "-crf", str(crf)]
    else:
        args += ["-c:v", "copy"]
    args += ["-c:a", "aac", "-b:a", "160k", "-shortest", str(out.resolve())]
    run(args, cwd=workdir)
    return out
