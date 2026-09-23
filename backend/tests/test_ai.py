"""Advisor regressions with a fake provider; no network or API key is needed."""

import json
from types import SimpleNamespace

import openai
import pytest

from app.ai.advisor import explain
from app.ai.fallback import explain_comparison, explain_simulation
from app.ai.schemas import ExplanationText
from app.simulation.engine import simulate


@pytest.fixture(autouse=True)
def isolated_provider(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    def unavailable_provider(**kwargs):
        raise AssertionError("Tests must never instantiate a real provider")

    monkeypatch.setattr(openai, "OpenAI", unavailable_provider)


@pytest.fixture
def demo():
    return simulate([
        {"measure_id": "M7", "district": "Нура"},
        {"measure_id": "M8", "district": "Нура"},
        {"measure_id": "M10", "district": "Нура"},
        {"measure_id": "M12"},
        {"measure_id": "M5", "district": "Сарыарка"},
    ])


@pytest.fixture
def alternate():
    return simulate([
        {"measure_id": "M7", "district": "Нура"},
        {"measure_id": "M8", "district": "Нура"},
        {"measure_id": "M10", "district": "Нура"},
        {"measure_id": "M12"},
        {"measure_id": "M11", "district": "Алматы"},
    ])


def fake_provider(monkeypatch, *, output=None, error=None):
    calls = {}

    class FakeClient:
        def __init__(self, **kwargs):
            calls["client"] = kwargs
            self.responses = self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            calls["closed"] = True

        def parse(self, **kwargs):
            calls["request"] = kwargs
            if error is not None:
                raise error
            return SimpleNamespace(output_parsed=output)

    monkeypatch.setattr(openai, "OpenAI", FakeClient)
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-key-never-sent")
    return calls


def provider_text(summary, **changes):
    fields = {
        "summary": summary,
        "strengths": ["Социальная инфраструктура улучшилась."],
        "risks": ["Сохраняются различия между районами."],
        "tradeoffs": ["Бюджет распределён между несколькими направлениями."],
        "recommendations": ["Сравните альтернативный приоритет в Scenario Lab."],
    }
    fields.update(changes)
    return ExplanationText(**fields)


def test_no_key_explains_demo_with_exact_display_facts(demo):
    result = explain(demo)
    assert result.source == "template"
    assert "52.56 → 56.54 (+3.99)" in result.summary
    assert "2 → 0" in result.summary
    assert any("95 из 100" in item and "резерв — 5" in item for item in result.tradeoffs)
    assert any("M10 + M12" in item and "Нура" in item and "B1 +2" in item for item in result.strengths)
    assert any("Критических показателей не осталось" in item for item in result.recommendations)
    assert all("ниже критического порога" not in item for item in result.risks)
    weakest = demo["weakest_district"]["after"]
    assert any(weakest["name"] in item and f"{weakest['score']:.2f}" in item for item in result.risks)
    assert result == explain(demo)


def test_fallback_reports_negative_m11_effect():
    simulation = simulate([{"measure_id": "M11", "district": "Нура"}], preview=True)
    result = explain(simulation)
    assert result.source == "template"
    assert any("Нура" in item and "разгрузка дорог -1.75" in item for item in result.tradeoffs)
    assert any("38.00" in item and "школы" in item for item in result.risks)
    assert any("35.00" in item and "помощь" in item for item in result.risks)
    assert any("оставшиеся критические показатели" in item for item in result.recommendations)


def test_comparison_uses_each_scenarios_score_budget_and_remaining_metrics(demo, alternate):
    result = explain(demo, alternate)
    assert result.source == "template"
    assert f"A: Score {demo['score']['after']:.2f}, бюджет 95" in result.summary
    assert f"B: Score {alternate['score']['after']:.2f}, бюджет 80" in result.summary
    assert any("Резерв бюджета: A — 5, B — 20" in item for item in result.tradeoffs)
    assert any("Активных синергий: A — 1, B — 1" in item for item in result.tradeoffs)
    assert any("Критических показателей: A — 0, B — 1" in item for item in result.risks)
    assert any("Транспорт" in item and "B -0.21" in item for item in result.strengths)
    assert any("Экология" in item and "A +0.88" in item for item in result.strengths)
    assert "лучший" not in result.summary.lower()


def test_identical_comparison_reports_equal_category_improvements(demo):
    result = explain(demo, demo)
    assert result.strengths == ["У сценариев одинаковые изменения по направлениям."]


@pytest.mark.parametrize("exception_type", [RuntimeError, TimeoutError, ConnectionError])
def test_provider_failure_returns_fallback_without_logging_secrets(monkeypatch, caplog, demo, exception_type):
    sensitive_message = "unit-test-key-never-sent and a private provider response"
    calls = fake_provider(monkeypatch, error=exception_type(sensitive_message))
    result = explain(demo)
    assert result == explain_simulation(demo)
    assert calls["closed"] is True
    assert exception_type.__name__ in caplog.text
    assert sensitive_message not in caplog.text
    assert "unit-test-key-never-sent" not in caplog.text


def test_provider_refusal_returns_fallback(monkeypatch, demo):
    fake_provider(monkeypatch, output=None)
    assert explain(demo) == explain_simulation(demo)


@pytest.mark.parametrize("field", ["summary", "strengths", "risks", "tradeoffs", "recommendations"])
def test_unsupported_numeric_output_in_any_field_returns_fallback(monkeypatch, demo, field):
    bad_value = "Ожидается рост до 999999.91."
    changes = {field: bad_value if field == "summary" else [bad_value]}
    text = provider_text("Показатели изменились.")
    text = text.model_copy(update=changes)
    fake_provider(monkeypatch, output=text)
    assert explain(demo) == explain_simulation(demo)


def test_valid_provider_explanation_is_tagged_and_receives_only_engine_facts(monkeypatch, demo):
    expected = provider_text("Качество жизни: 52.56 → 56.54.", tradeoffs=["Использовано 95.00 из 100.00."])
    calls = fake_provider(monkeypatch, output=expected)
    monkeypatch.setenv("OPENAI_MODEL", "fake-test-model")
    result = explain(demo)
    assert result.source == "openai"
    assert result.model_dump(exclude={"source"}) == expected.model_dump()
    request = calls["request"]
    assert request["model"] == "fake-test-model"
    assert request["store"] is False
    assert calls["client"]["max_retries"] == 0
    assert calls["client"]["timeout"] <= 15
    supplied = request["input"][1]["content"]
    assert "unit-test-key-never-sent" not in supplied
    payload = json.loads(supplied)
    assert payload["display_facts"]["score"] == {"before": "52.56", "after": "56.54", "delta": "3.99"}
    assert payload["display_facts"]["budget"]["spent"] == "95.00"
    assert "deterministic_explanation" in payload


def test_comparison_provider_failure_uses_comparison_fallback(monkeypatch, demo, alternate):
    fake_provider(monkeypatch, error=RuntimeError("fake failure"))
    assert explain(demo, alternate) == explain_comparison(demo, alternate)


def test_comparison_provider_receives_both_engine_results(monkeypatch, demo, alternate):
    expected = provider_text(f"A: 56.54; B: {alternate['score']['after']:.2f}.")
    calls = fake_provider(monkeypatch, output=expected)
    result = explain(demo, alternate)
    assert result.source == "openai"
    facts = json.loads(calls["request"]["input"][1]["content"])["display_facts"]
    assert facts["scenario_a"]["budget"]["spent"] == "95.00"
    assert facts["scenario_b"]["budget"]["spent"] == "80.00"
