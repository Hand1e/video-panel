"""DeepSeek client (OpenAI-compatible). Falls back to deterministic mock outputs when no key is set.

Every call is tagged with a `task` name; in mock mode the task selects a canned generator from
`studio.mocks`, so the whole pipeline (including the critique loop) can be exercised offline.
"""
from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import config


class LLMError(RuntimeError):
    pass


@dataclass
class CallLog:
    calls: list[dict] = field(default_factory=list)

    def add(self, **kw: Any) -> None:
        self.calls.append(kw)

    def totals(self) -> dict:
        return {
            "calls": len(self.calls),
            "prompt_tokens": sum(c.get("prompt_tokens", 0) for c in self.calls),
            "completion_tokens": sum(c.get("completion_tokens", 0) for c in self.calls),
        }


LOG = CallLog()
_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI

        _client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL, timeout=180)
    return _client


def image_part(path: str | Path, detail: str = "low") -> dict:
    data = Path(path).read_bytes()
    ext = Path(path).suffix.lower().lstrip(".") or "jpeg"
    mime = "jpeg" if ext in ("jpg", "jpeg") else ext
    b64 = base64.b64encode(data).decode()
    return {"type": "image_url", "image_url": {"url": f"data:image/{mime};base64,{b64}", "detail": detail}}


def chat_json(
    task: str,
    system: str,
    user: str | dict,
    *,
    images: list[str | Path] | None = None,
    thinking: bool = True,
    effort: str = "high",
    max_tokens: int = 16000,
    retries: int = 2,
) -> dict:
    """Call the model and return parsed JSON. `system` must mention JSON + give an example shape."""
    user_text = user if isinstance(user, str) else json.dumps(user, ensure_ascii=False, indent=1)

    if config.mock_llm():
        from . import mocks

        out = mocks.respond(task, user if isinstance(user, dict) else {"text": user_text}, n_images=len(images or []))
        LOG.add(task=task, mock=True)
        return out

    content: Any = user_text
    if images:
        content = [{"type": "text", "text": user_text}] + [image_part(p) for p in images]

    messages = [{"role": "system", "content": system}, {"role": "user", "content": content}]
    extra = {"thinking": {"type": "enabled" if thinking else "disabled"}}
    kwargs: dict[str, Any] = dict(
        model=config.DEEPSEEK_MODEL,
        messages=messages,
        response_format={"type": "json_object"},
        max_tokens=max_tokens,
        extra_body=extra,
    )
    if thinking:
        kwargs["reasoning_effort"] = effort

    last_err: Exception | None = None
    for attempt in range(retries + 1):
        t0 = time.time()
        try:
            resp = _get_client().chat.completions.create(**kwargs)
            text = (resp.choices[0].message.content or "").strip()
            u = resp.usage
            LOG.add(
                task=task,
                mock=False,
                seconds=round(time.time() - t0, 1),
                prompt_tokens=getattr(u, "prompt_tokens", 0),
                completion_tokens=getattr(u, "completion_tokens", 0),
            )
            if not text:  # documented: JSON mode may return blanks; retry
                raise LLMError("blank JSON content")
            return json.loads(text)
        except (json.JSONDecodeError, LLMError) as e:
            last_err = e
        except Exception as e:  # network / API errors
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise LLMError(f"{task}: {last_err}")
