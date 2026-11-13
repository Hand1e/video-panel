"""Generate -> critique -> revise engine with explicit stop rules.

Stop when ANY of:
  * critic passes AND every rubric dimension >= pass score (and no veto dimension fails)
  * max iterations reached
  * score gain vs previous round < min_gain (plateau)
The best-scoring draft (not necessarily the last) is returned, with the full history for the UI.
Issues carry a `stage_owner`; issues owned by an *earlier* stage are surfaced as rollback requests
instead of being "fixed" locally.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from . import config, llm
from .rubrics import RUBRICS, critic_system_prompt


@dataclass
class Round:
    iteration: int
    draft: Any
    scores: dict[str, float]
    issues: list[dict]
    passed: bool

    @property
    def avg(self) -> float:
        return round(sum(self.scores.values()) / max(len(self.scores), 1), 2)

    @property
    def min(self) -> float:
        return min(self.scores.values()) if self.scores else 0.0


@dataclass
class LoopResult:
    stage: str
    best: Any
    rounds: list[Round] = field(default_factory=list)
    stop_reason: str = ""
    rollbacks: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        best_round = max(self.rounds, key=lambda r: r.avg) if self.rounds else None
        return {
            "stage": self.stage,
            "best": self.best,
            "best_iteration": best_round.iteration if best_round else None,
            "stop_reason": self.stop_reason,
            "rollbacks": self.rollbacks,
            "rounds": [
                {"iteration": r.iteration, "avg": r.avg, "min": r.min, "scores": r.scores,
                 "issues": r.issues, "passed": r.passed}
                for r in self.rounds
            ],
        }


def critique(stage: str, draft: Any, context: dict, iteration: int, images: list | None = None) -> dict:
    rubric = RUBRICS[stage]
    out = llm.chat_json(
        f"critic:{stage}",
        critic_system_prompt(stage),
        {"stage": stage, "iteration": iteration, "context": context, "draft": draft},
        images=images,
        thinking=True,
    )
    scores = {d: float(out.get("scores", {}).get(d, 0)) for d in rubric["dimensions"]}
    issues = out.get("issues", []) or []
    for it in issues:
        it.setdefault("stage_owner", stage)
    return {"scores": scores, "issues": issues, "pass": bool(out.get("pass", False))}


def refine(
    stage: str,
    generate: Callable[[list[dict], Any], Any],
    context: dict,
    *,
    upstream_stages: tuple[str, ...] = (),
    critic_images: Callable[[Any], list] | None = None,
    max_iter: int | None = None,
    on_round: Callable[[Round], None] | None = None,
) -> LoopResult:
    """`generate(feedback_issues, previous_draft) -> draft`."""
    rubric = RUBRICS[stage]
    max_iter = max_iter or config.LOOP_MAX_ITER
    vetoes = set(rubric.get("veto", []))
    res = LoopResult(stage=stage, best=None)
    feedback: list[dict] = []
    prev: Any = None

    for i in range(1, max_iter + 1):
        draft = generate(feedback, prev)
        c = critique(stage, draft, context, i, images=critic_images(draft) if critic_images else None)
        rnd = Round(i, draft, c["scores"], c["issues"], c["pass"])
        res.rounds.append(rnd)
        if on_round:
            on_round(rnd)

        rollbacks = [x for x in rnd.issues if x.get("stage_owner") in upstream_stages]
        local = [x for x in rnd.issues if x.get("stage_owner") not in upstream_stages]

        veto_failed = any(rnd.scores.get(v, 10) < config.LOOP_PASS_SCORE for v in vetoes)
        if rnd.passed and rnd.min >= config.LOOP_PASS_SCORE and not veto_failed:
            res.stop_reason = f"第{i}轮通过（最低分 {rnd.min} ≥ {config.LOOP_PASS_SCORE}）"
            break
        if rollbacks and not local:
            res.rollbacks = rollbacks
            res.stop_reason = f"第{i}轮：问题出在上游阶段 {sorted({x['stage_owner'] for x in rollbacks})}，建议回退"
            break
        if len(res.rounds) >= 2 and rnd.avg - res.rounds[-2].avg < config.LOOP_MIN_GAIN:
            res.stop_reason = f"第{i}轮分数停滞（提升 {rnd.avg - res.rounds[-2].avg:+.2f} < {config.LOOP_MIN_GAIN}）"
            res.rollbacks = rollbacks
            break
        feedback, prev = local, draft
    else:
        res.stop_reason = f"达到最大轮数 {max_iter}"
        res.rollbacks = [x for x in res.rounds[-1].issues if x.get("stage_owner") in upstream_stages]

    res.best = max(res.rounds, key=lambda r: r.avg).draft
    return res
