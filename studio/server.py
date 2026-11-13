"""HTTP API + static workbench UI.  Run:  python -m studio  (http://127.0.0.1:8765)"""
from __future__ import annotations

import shutil
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import analysis, config, editing, footage, llm, store, writing
from .storyboard import render_board

app = FastAPI(title="Family Video Studio")
WEB = config.ROOT / "web"
JOBS: dict[str, dict] = {}


# ---------------- jobs ----------------

def _start(kind: str, pid: str | None, fn: Callable[[Callable, Callable], Any]) -> dict:
    jid = uuid.uuid4().hex[:10]
    job = {"id": jid, "kind": kind, "project": pid, "status": "running", "log": [], "rounds": [],
           "result": None, "error": None, "started": time.time()}
    JOBS[jid] = job

    def say(msg: str) -> None:
        job["log"].append({"t": round(time.time() - job["started"], 1), "msg": msg})

    def on_round(r) -> None:
        job["rounds"].append({"iteration": r.iteration, "avg": r.avg, "min": r.min, "scores": r.scores,
                              "issues": r.issues, "passed": r.passed})
        say(f"第{r.iteration}轮审稿：平均 {r.avg} / 最低 {r.min}{' ✅' if r.passed else ''}")

    def runner():
        try:
            job["result"] = fn(say, on_round)
            job["status"] = "done"
            say("完成")
        except Exception as e:
            job["status"], job["error"] = "error", f"{e}"
            job["trace"] = traceback.format_exc()[-3000:]
            say(f"出错：{e}")

    threading.Thread(target=runner, daemon=True).start()
    return {"job": jid}


@app.get("/api/jobs/{jid}")
def get_job(jid: str):
    if jid not in JOBS:
        raise HTTPException(404)
    return JOBS[jid]


# ---------------- status / cast ----------------

@app.get("/api/status")
def status():
    from . import media

    def has(fn):
        try:
            fn()
            return True
        except Exception:
            return False

    return {"mock_llm": config.mock_llm(), "mock_asr": config.mock_asr(), "model": config.DEEPSEEK_MODEL,
            "ffmpeg": has(media.ffmpeg), "loop": {"max_iter": config.LOOP_MAX_ITER,
                                                  "pass_score": config.LOOP_PASS_SCORE},
            "llm_usage": llm.LOG.totals()}


@app.get("/api/cast")
def get_cast():
    return store.get_cast()


@app.put("/api/cast")
def put_cast(cast: dict):
    store.set_cast(cast)
    return {"ok": True}


# ---------------- projects ----------------

@app.get("/api/projects")
def projects():
    return store.list_projects()


ARTIFACTS = ["meta", "analysis", "topics", "script", "storyboard", "shotlist", "footage", "edit_options",
             "timeline", "cut", "retro"]


@app.get("/api/projects/{pid}")
def project(pid: str):
    if not store.project_dir(pid).exists():
        raise HTTPException(404)
    return {a: store.load(pid, a) for a in ARTIFACTS}


class NewProject(BaseModel):
    title: str
    mode: str = "full"  # full | footage_only


@app.post("/api/projects")
def create_project(body: NewProject):
    return {"id": store.new_project(body.title, body.mode)}


# ---------------- topic research ----------------

@app.post("/api/analyze")
async def analyze(text: str = Form(...), screenshots: list[UploadFile] = File(default=[])):
    pid = store.new_project(text[:30], "analysis")
    shots_dir = store.project_dir(pid) / "media" / "screenshots"
    paths = []
    for i, f in enumerate(screenshots or []):
        if not f.filename:
            continue
        shots_dir.mkdir(parents=True, exist_ok=True)
        dst = shots_dir / f"{i:02d}{Path(f.filename).suffix.lower() or '.png'}"
        dst.write_bytes(await f.read())
        paths.append(str(dst))

    def fn(say, on_round):
        out = analysis.analyze_topic(text, paths, on_round=on_round, progress=say)
        store.save(pid, "analysis", out)
        store.update_meta(pid, stage="analysis", title=(out["source"].get("topic") or text)[:40])
        best = out["best"] or {}
        store.remember("prediction", {"project": pid, "score": best.get("score"), "verdict": best.get("verdict")})
        return {"project": pid, **out}

    return _start("analyze", pid, fn) | {"project": pid}


@app.post("/api/topics/daily")
def topics_daily():
    pid = store.new_project("今日选题", "topics")

    def fn(say, on_round):
        say("拉取 B站热门（生活相关分区）…")
        out = analysis.daily_topics(on_round=on_round)
        store.save(pid, "topics", out)
        return {"project": pid, **out}

    return _start("topics", pid, fn) | {"project": pid}


# ---------------- writing ----------------

class Brief(BaseModel):
    brief: dict | None = None


@app.post("/api/projects/{pid}/script")
def script(pid: str, body: Brief):
    brief = body.brief
    if not brief:
        a = store.load(pid, "analysis")
        if a and a.get("best"):
            best = a["best"]
            brief = {"title": (best.get("angles") or [{}])[0].get("title"), "analysis": best}
        else:
            brief = {"title": store.load(pid, "meta", {}).get("title")}

    def fn(say, on_round):
        say("编剧写脚本…")
        out = writing.write_script(brief, on_round=on_round)
        store.save(pid, "script", out)
        store.update_meta(pid, stage="script")
        return out

    return _start("script", pid, fn)


@app.post("/api/projects/{pid}/storyboard")
def storyboard(pid: str):
    sc = store.load(pid, "script")
    if not sc:
        raise HTTPException(400, "请先生成脚本")

    def fn(say, on_round):
        say("分镜导演拆镜头…")
        out = writing.make_storyboard(sc["best"], on_round=on_round)
        store.save(pid, "storyboard", out)
        shots = out["best"]["shots"]
        store.save(pid, "shotlist", writing.make_shotlist(shots))
        store.update_meta(pid, stage="storyboard")
        return out

    return _start("storyboard", pid, fn)


@app.get("/api/projects/{pid}/storyboard/svg")
def storyboard_svg(pid: str, aspect: str | None = None):
    sb = store.load(pid, "storyboard")
    if not sb:
        raise HTTPException(404)
    sc = store.load(pid, "script") or {}
    aspect = aspect or (sc.get("best") or {}).get("platform_format") or "16:9"
    return render_board(sb["best"]["shots"], "9:16" if aspect == "9:16" else "16:9")


class ShotsBody(BaseModel):
    shots: list[dict]
    aspect: str = "16:9"


@app.post("/api/storyboard/render")
def storyboard_render(body: ShotsBody):
    return render_board(writing.sanitize_shots({"shots": body.shots})["shots"], body.aspect)


# ---------------- footage + edit ----------------

@app.post("/api/projects/{pid}/footage/upload")
async def footage_upload(pid: str, files: list[UploadFile] = File(...)):
    d = store.project_dir(pid) / "media" / "footage"
    d.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in files:
        dst = d / Path(f.filename or f"clip_{uuid.uuid4().hex[:6]}.mp4").name
        with dst.open("wb") as out:
            shutil.copyfileobj(f.file, out, 1 << 20)
        saved.append(str(dst))
    m = store.load(pid, "meta", {})
    store.update_meta(pid, footage=sorted(set(m.get("footage", []) + saved)))
    return {"saved": saved}


class FolderBody(BaseModel):
    folder: str


@app.post("/api/projects/{pid}/footage/folder")
def footage_folder(pid: str, body: FolderBody):
    """Reference footage in place (no copying GBs of video)."""
    p = Path(body.folder)
    if not p.is_dir():
        raise HTTPException(400, "目录不存在")
    vids = [str(v) for v in footage.list_videos(p)]
    if not vids:
        raise HTTPException(400, "目录里没有视频文件")
    m = store.load(pid, "meta", {})
    store.update_meta(pid, footage=sorted(set(m.get("footage", []) + vids)))
    return {"found": vids}


@app.post("/api/projects/{pid}/footage/analyze")
def footage_analyze(pid: str):
    clips = store.load(pid, "meta", {}).get("footage") or []
    if not clips:
        raise HTTPException(400, "还没有素材")

    def fn(say, on_round):
        say(f"并行分析 {len(clips)} 段素材…")
        out = footage.analyze_all(pid, clips, progress=say)
        store.update_meta(pid, stage="footage")
        return {"clips": len(out["clips"]), "sync_groups": out["sync_groups"], "errors": out["errors"]}

    return _start("footage", pid, fn)


class IntentBody(BaseModel):
    intent: str = ""


@app.post("/api/projects/{pid}/edit/options")
def edit_options(pid: str, body: IntentBody):
    def fn(say, on_round):
        say("剪辑导演提出方案…")
        return editing.edit_options(pid, body.intent)

    return _start("edit_options", pid, fn)


class CutBody(BaseModel):
    option_id: str | None = None
    option: dict | None = None
    bgm: str | None = None


@app.post("/api/projects/{pid}/edit/cut")
def edit_cut(pid: str, body: CutBody):
    opts = (store.load(pid, "edit_options") or {}).get("options", [])
    option = body.option or next((o for o in opts if o.get("id") == body.option_id), opts[0] if opts else None)
    if not option:
        raise HTTPException(400, "没有剪辑方案")
    if body.bgm and not Path(body.bgm).exists():
        raise HTTPException(400, "BGM 文件不存在")

    def fn(say, on_round):
        out = editing.cut(pid, option, bgm=body.bgm, on_round=on_round, progress=say)
        store.update_meta(pid, stage="cut")
        return out

    return _start("cut", pid, fn)


@app.post("/api/projects/{pid}/footage-direct")
def footage_direct(pid: str, body: IntentBody):
    """One-click: analyze footage -> propose options -> pick recommended -> cut + review loop."""
    clips = store.load(pid, "meta", {}).get("footage") or []
    if not clips:
        raise HTTPException(400, "还没有素材")

    def fn(say, on_round):
        say(f"① 素材理解：并行分析 {len(clips)} 段…")
        footage.analyze_all(pid, clips, progress=say)
        say("② 提出剪辑方案…")
        opts = editing.edit_options(pid, body.intent)["options"]
        say(f"③ 采用推荐方案：{opts[0].get('name')}（可在界面改选其他方案重剪）")
        out = editing.cut(pid, opts[0], on_round=on_round, progress=say)
        store.update_meta(pid, stage="cut")
        return out

    return _start("footage_direct", pid, fn)


# ---------------- retrospective / calibration ----------------

class Retro(BaseModel):
    platform: str = "bilibili"
    views: int | None = None
    likes: int | None = None
    favorites: int | None = None
    completion_rate: float | None = None
    notes: str = ""


@app.post("/api/projects/{pid}/retro")
def retro(pid: str, body: Retro):
    a = (store.load(pid, "analysis") or {}).get("best") or {}
    data = body.model_dump()
    store.save(pid, "retro", data)
    like_rate = (body.likes or 0) / body.views if body.views else None
    store.remember("calibration", {"project": pid, "predicted_score": a.get("score"),
                                   "predicted_verdict": a.get("verdict"), "actual": data,
                                   "actual_like_rate": like_rate})
    store.remember("retrospective", {"project": pid, "title": store.load(pid, "meta", {}).get("title"),
                                     "notes": body.notes, "actual": data})
    return {"ok": True}


# ---------------- files + UI ----------------

@app.get("/files/{pid}/{path:path}")
def files(pid: str, path: str):
    base = store.project_dir(pid).resolve()
    p = (base / path).resolve()
    if base not in p.parents or not p.is_file():
        raise HTTPException(404)
    return FileResponse(p)


@app.get("/", response_class=HTMLResponse)
def index():
    return (WEB / "index.html").read_text(encoding="utf-8")


app.mount("/static", StaticFiles(directory=WEB), name="static")
