"""Advisor regressions with a fake provider; no network or API key is needed."""




import openai
import pytest

from app.ai.advisor import explain
from app.ai.fallback import explain_comparison, explain_simulation

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




def test_template_helper_never_calls_provider_even_with_key(monkeypatch, demo):
    monkeypatch.setenv('OPENAI_API_KEY', 'unit-test-key-never-sent')
    assert explain(demo).source == 'template'
