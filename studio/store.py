"""File-based project store: data/projects/<id>/<artifact>.json + media/. Plus cast profile & memory."""
from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from . import config

DEFAULT_CAST = {
    "updated": "2026-11-13",
    "members": [
        {"id": "me", "name": "我", "role": "主角 + 摄影", "on_camera": True, "lines": "主讲"},
        {"id": "partner", "name": "爱人", "role": "配角，可兼任摄影", "on_camera": True,
         "show_face": True, "lines": "少量", "available": ["周末", "工作日晚饭后"], "can_operate_camera": True},
        {"id": "baby", "name": "宝宝", "role": "不可控主角（只做捕捉式拍摄）", "on_camera": True,
         "birth_month": "2026-07", "age_months": 4, "blur_face": False,
         "abilities": ["抬头", "追视", "笑出声", "抓握", "可能开始翻身"],
         "awake_windows": "每次清醒约 1.5-2 小时，以实际作息为准",
         "best_mood_slots": ["上午喂奶后 30 分钟"],
         "safety": ["不用闪光灯/强补光直射", "抱娃时第一人称支架必须固定牢", "洗澡/趴卧镜头须大人全程手扶"]},
    ],
    "cameras": [
        {"id": "pov", "type": "first_person", "rig": "头戴/胸前支架"},
        {"id": "tripod", "type": "third_person", "rig": "三脚架固定机位"},
        {"id": "handheld", "type": "third_person", "rig": "手持（仅爱人掌镜时）", "requires": "partner"},
    ],
    "budget_per_video_cny": 200,
    "home_locations": ["客厅", "卧室", "厨房", "阳台", "小区楼下（注意隐私）"],
}


def _slug(s: str) -> str:
    s = re.sub(r"[^\w一-鿿-]+", "-", s).strip("-")
    return s[:24] or "project"


def new_project(title: str, mode: str) -> str:
    pid = f"{time.strftime('%Y%m%d-%H%M%S')}-{_slug(title)}-{uuid.uuid4().hex[:4]}"
    d = project_dir(pid)
    (d / "media").mkdir(parents=True, exist_ok=True)
    save(pid, "meta", {"id": pid, "title": title, "mode": mode, "created": time.time(), "stage": "new"})
    return pid


def project_dir(pid: str) -> Path:
    if not re.fullmatch(r"[\w一-鿿-]+", pid):
        raise ValueError("bad project id")
    return config.PROJECTS_DIR / pid


def save(pid: str, name: str, data: Any) -> Path:
    p = project_dir(pid) / f"{name}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def load(pid: str, name: str, default: Any = None) -> Any:
    p = project_dir(pid) / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def update_meta(pid: str, **kw: Any) -> dict:
    m = load(pid, "meta", {})
    m.update(kw)
    save(pid, "meta", m)
    return m


def list_projects() -> list[dict]:
    out = []
    for d in sorted(config.PROJECTS_DIR.iterdir(), reverse=True):
        m = d / "meta.json"
        if m.exists():
            out.append(json.loads(m.read_text(encoding="utf-8")))
    return out


def get_cast() -> dict:
    if config.CAST_FILE.exists():
        return json.loads(config.CAST_FILE.read_text(encoding="utf-8"))
    return DEFAULT_CAST


def set_cast(cast: dict) -> None:
    config.CAST_FILE.write_text(json.dumps(cast, ensure_ascii=False, indent=1), encoding="utf-8")


# ---- cross-project memory (retrospectives + prediction calibration) ----

def remember(kind: str, data: dict) -> None:
    with config.MEMORY_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"t": time.time(), "kind": kind, **data}, ensure_ascii=False) + "\n")


def recall(kind: str | None = None, limit: int = 20) -> list[dict]:
    if not config.MEMORY_FILE.exists():
        return []
    rows = [json.loads(l) for l in config.MEMORY_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
    if kind:
        rows = [r for r in rows if r.get("kind") == kind]
    return rows[-limit:]
