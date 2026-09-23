"""Оркестрация агентов: параллельный запуск, деградация в fallback при ошибках."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional

from ..engine.data import Dataset, load_dataset
from ..engine.models import Decision, ScoreResult, WorldState
from . import agents, fallback
from .context import build_context
from .llm import LLM, get_llm

log = logging.getLogger("akim.ai")


def _guard(name: str, llm_fn: Callable[[], Dict[str, Any]], fb_fn: Callable[[], Dict[str, Any]], llm: LLM) -> Dict[str, Any]:
    if not llm.available():
        out = fb_fn()
        out["_mode"] = "fallback"
        return out
    try:
        out = llm_fn()
        if not isinstance(out, dict):
            raise ValueError("LLM вернул не объект")
        out["_mode"] = "llm"
        return out
    except Exception as exc:  # noqa: BLE001
        log.warning("Агент %s упал (%s) — используем fallback", name, exc)
        out = fb_fn()
        out["_mode"] = "fallback"
        out["_error"] = str(exc)
        return out


def analyze(decisions: List[Decision], result: ScoreResult, world: WorldState, ds: Optional[Dataset] = None, llm: Optional[LLM] = None, include: Optional[List[str]] = None) -> Dict[str, Any]:
    """Аналитик + Критик + Советник параллельно. ``include`` ограничивает набор агентов."""
    ds = ds or load_dataset()
    llm = llm or get_llm()
    ctx = build_context(decisions, result, world, ds)
    include = include or ["analyst", "critic", "advisor"]
    jobs = {
        "analyst": lambda: _guard("analyst", lambda: agents.run_analyst(llm, ctx), lambda: fallback.analyst(ctx), llm),
        "critic": lambda: _guard("critic", lambda: agents.run_critic(llm, ctx), lambda: fallback.critic(ctx), llm),
        "advisor": lambda: _guard("advisor", lambda: agents.run_advisor(llm, ctx, decisions, world, ds), lambda: fallback.advisor(ctx), llm),
    }
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {k: pool.submit(jobs[k]) for k in include if k in jobs}
        out = {k: f.result() for k, f in futures.items()}
    out["oracle"] = ctx.get("oracle")
    out["llm"] = llm.cfg.describe()
    return out


def council(decisions: List[Decision], result: ScoreResult, world: WorldState, ds: Optional[Dataset] = None, llm: Optional[LLM] = None) -> Dict[str, Any]:
    ds = ds or load_dataset()
    llm = llm or get_llm()
    ctx = build_context(decisions, result, world, ds, with_oracle=False)
    out = _guard("council", lambda: agents.run_council(llm, ctx), lambda: fallback.council(ctx), llm)
    out["personas"] = agents.COUNCIL_PERSONAS
    return out


def narrate_event(decisions: List[Decision], result_after: ScoreResult, world_after: WorldState, before_score: float, ds: Optional[Dataset] = None, llm: Optional[LLM] = None, event: Optional[Any] = None) -> Dict[str, Any]:
    ds = ds or load_dataset()
    llm = llm or get_llm()
    ctx = build_context(decisions, result_after, world_after, ds, with_oracle=False, event=event)
    return _guard("event", lambda: agents.run_event_narrator(llm, ctx, before_score), lambda: fallback.event_narrator(ctx, before_score), llm)
