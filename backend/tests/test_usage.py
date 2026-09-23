from concurrent.futures import ThreadPoolExecutor
import json

import pytest

from app.ai.settings import Settings
from app.ai.usage import UsageLedger, UsageLimitError


def make_ledger(tmp_path, **settings):
    return UsageLedger(tmp_path / "usage.sqlite3", Settings(**settings))


def test_all_calls_and_cached_tokens_are_aggregated_and_persist(tmp_path):
    ledger = make_ledger(tmp_path)
    first = ledger.reserve("run", 12000, 2500)
    ledger.finish(first, {"model": "gpt-4.1-mini-2025-04-14", "usage": {
        "input_tokens": 1000, "output_tokens": 100, "input_tokens_details": {"cached_tokens": 400},
    }})
    second = ledger.reserve("run", 12000, 2500)
    ledger.finish(second, {"model": "gpt-4.1-mini", "usage": {"input_tokens": 500, "output_tokens": 200}})
    metadata = make_ledger(tmp_path).metadata("run")
    assert metadata["api_calls"] == 2
    assert metadata["input_tokens"] == 1500
    assert metadata["output_tokens"] == 300
    assert metadata["cached_input_tokens"] == 400
    assert metadata["usage"]["total_tokens"] == 1800
    assert metadata["estimated_cost_usd"] == pytest.approx((1100 * 0.4 + 400 * 0.1 + 300 * 1.6) / 1_000_000)
    assert metadata["used_llm"] is True
    assert metadata["usage_unknown"] is False
    assert metadata["reserved_cost_usd"] == 0


@pytest.mark.parametrize("finish", [False, True])
def test_missing_usage_retains_reservation_after_restart(tmp_path, finish):
    ledger = make_ledger(tmp_path)
    attempt = ledger.reserve("run", 12000, 2500)
    if finish:
        ledger.finish(attempt, {"id": "response", "output": []})
    else:
        ledger.fail(attempt, "TIMEOUT")
    metadata = make_ledger(tmp_path).metadata("run")
    assert metadata["estimated_cost_usd"] is None
    assert metadata["usage_unknown"] is True
    assert metadata["reserved_cost_usd"] == pytest.approx(0.0088)
    assert metadata["actual_model"] is None
    assert metadata["used_llm"] is finish
    assert metadata["api_calls"] == 1
    assert metadata["usage"] is None


def test_inflight_requests_atomically_reserve_daily_budget_across_connections(tmp_path):
    settings = Settings(ai_daily_spend_limit_usd=0.003)
    db_path = tmp_path / "shared.sqlite3"
    UsageLedger(db_path, settings)

    def attempt(index):
        ledger = UsageLedger(db_path, settings)
        try:
            ledger.reserve(f"run-{index}", 1000, 1000)
            return True
        except UsageLimitError as error:
            assert error.code == "DAILY_COST_LIMIT"
            return False

    with ThreadPoolExecutor(max_workers=8) as workers:
        assert sum(workers.map(attempt, range(16))) == 1
    summary = UsageLedger(db_path, settings).summary()
    assert summary["api_calls"] == 1
    assert summary["in_flight_calls"] == 1
    assert summary["reserved_cost_usd"] == pytest.approx(0.002)
    assert summary["daily_limit_usd"] == 0.003


def test_run_cost_limit_includes_pending_and_failed_attempts(tmp_path):
    ledger = make_ledger(tmp_path, ai_run_estimated_cost_limit_usd=0.003)
    attempt = ledger.reserve("run", 1000, 1000)
    ledger.fail(attempt, "PROVIDER_SERVER_ERROR")
    with pytest.raises(UsageLimitError) as error:
        ledger.reserve("run", 1000, 1000)
    assert error.value.code == "RUN_COST_LIMIT"
    assert ledger.metadata("run")["api_calls"] == 1


def test_attempt_limit_survives_restart(tmp_path):
    ledger = make_ledger(tmp_path, ai_max_model_calls_per_run=1)
    ledger.reserve("run", 1000, 1000)
    with pytest.raises(UsageLimitError) as error:
        make_ledger(tmp_path, ai_max_model_calls_per_run=1).reserve("run", 1000, 1000)
    assert error.value.code == "MODEL_CALL_LIMIT"


def test_unknown_price_blocks_paid_attempt_instead_of_inventing_cost(tmp_path):
    pricing = tmp_path / "prices.json"
    pricing.write_text(json.dumps({"models": {}}), encoding="utf-8")
    ledger = make_ledger(tmp_path, ai_pricing_path=pricing)
    with pytest.raises(UsageLimitError) as error:
        ledger.reserve("run", 1000, 1000)
    assert error.value.code == "UNKNOWN_PRICING"
    assert ledger.metadata("run")["estimated_cost_usd"] is None
    assert ledger.metadata("run")["api_calls"] == 0


def test_unknown_actual_price_preserves_tokens_and_marks_only_cost_unknown(tmp_path):
    ledger = make_ledger(tmp_path)
    attempt = ledger.reserve("run", 12000, 2500)
    ledger.finish(attempt, {"model": "unpriced-model", "usage": {"input_tokens": 200, "output_tokens": 50}})
    metadata = ledger.metadata("run")
    assert metadata["usage_unknown"] is False
    assert metadata["cost_unknown"] is True
    assert metadata["input_tokens"] == 200
    assert metadata["estimated_cost_usd"] is None
    assert metadata["reserved_cost_usd"] == pytest.approx(0.0088)


def test_malformed_usage_is_not_claimed_as_zero_cost(tmp_path):
    ledger = make_ledger(tmp_path)
    attempt = ledger.reserve("run", 12000, 2500)
    ledger.finish(attempt, {"usage": {"input_tokens": 1, "output_tokens": -1}})
    assert ledger.metadata("run")["usage_unknown"] is True
    assert ledger.metadata("run")["estimated_cost_usd"] is None
