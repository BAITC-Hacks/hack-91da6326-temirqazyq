"""Verify development live limits without constructing or calling a provider."""

import importlib.util
from pathlib import Path

import pytest

from app.ai.settings import Settings
from app.ai.usage import UsageLimitError

spec = importlib.util.spec_from_file_location("live_smoke", Path(__file__).resolve().parents[2] / "scripts" / "live_smoke.py")
live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live)


def test_live_attempt_cap_persists_between_instances_and_runs(tmp_path):
    path = tmp_path / "live.sqlite3"
    settings = Settings(db_path=path)
    ledger = live.LiveLedger(path, settings)
    for number in range(8):
        ledger.reserve(f"run-{number}", 100, 100)
    reopened = live.LiveLedger(path, settings)
    with pytest.raises(UsageLimitError, match="общий лимит") as failure:
        reopened.reserve("new-run", 100, 100)
    assert failure.value.code == "LIVE_ATTEMPT_LIMIT"
    assert reopened.totals()["api_calls"] == 8


def test_live_global_cost_cap_is_atomic_and_cannot_be_reset_by_new_run(tmp_path):
    path = tmp_path / "cost.sqlite3"
    settings = Settings(db_path=path, ai_run_estimated_cost_limit_usd=1, ai_daily_spend_limit_usd=2)
    ledger = live.LiveLedger(path, settings)
    ledger.reserve("first", 100, 100)
    with ledger._connect() as connection:
        connection.execute("UPDATE ai_usage_attempts SET accounted_cost=0.499")
    with pytest.raises(UsageLimitError) as failure:
        ledger.reserve("second", 12000, 2500)
    assert failure.value.code == "LIVE_COST_LIMIT"
    assert ledger.totals()["api_calls"] == 1
