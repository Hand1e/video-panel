"""Runtime configuration. All secrets come from env vars or a local .env file (never committed)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-flash")

TENCENT_SECRET_ID = os.environ.get("TENCENTCLOUD_SECRET_ID", "")
TENCENT_SECRET_KEY = os.environ.get("TENCENTCLOUD_SECRET_KEY", "")
TENCENT_ASR_ENGINE = os.environ.get("TENCENT_ASR_ENGINE", "16k_zh_en_2.0")

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")

DATA_DIR = Path(os.environ.get("STUDIO_DATA_DIR", ROOT / "data"))
PROJECTS_DIR = DATA_DIR / "projects"
MEMORY_FILE = DATA_DIR / "memory.jsonl"
CAST_FILE = DATA_DIR / "cast.json"

FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
FFPROBE = os.environ.get("FFPROBE", "ffprobe")

# Loop control
LOOP_MAX_ITER = int(os.environ.get("LOOP_MAX_ITER", "3"))
LOOP_PASS_SCORE = float(os.environ.get("LOOP_PASS_SCORE", "7.0"))
LOOP_MIN_GAIN = float(os.environ.get("LOOP_MIN_GAIN", "0.3"))


def mock_llm() -> bool:
    """Demo mode: no DeepSeek key -> deterministic sample outputs, clearly labelled in UI."""
    return not DEEPSEEK_API_KEY or os.environ.get("STUDIO_MOCK") == "1"


def mock_asr() -> bool:
    return not (TENCENT_SECRET_ID and TENCENT_SECRET_KEY) or os.environ.get("STUDIO_MOCK") == "1"


for d in (DATA_DIR, PROJECTS_DIR):
    d.mkdir(parents=True, exist_ok=True)
