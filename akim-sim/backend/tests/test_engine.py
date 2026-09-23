"""Тесты движка: цифры из датасета должны воспроизводиться точно."""
import pytest

from app.engine import Decision, load_dataset, score_scenario, validate
from app.engine.events import custom_event_from_spec, world_for_event
from app.engine.optimizer import best_swaps, oracle, percentile
from app.engine.scorer import shapley_contributions

EXAMPLE = [
    Decision(measure_id="M7", district_id="nura"),
    Decision(measure_id="M8", district_id="nura"),
    Decision(measure_id="M10", district_id="nura"),
    Decision(measure_id="M12"),
    Decision(measure_id="M5", district_id="saryarka"),
]
CHEAPEST = [
    Decision(measure_id="M9", district_id="nura"),
    Decision(measure_id="M11", district_id="esil"),
    Decision(measure_id="M10", district_id="nura"),
    Decision(measure_id="M12"),
    Decision(measure_id="M4", district_id="saryarka"),
]


def test_baseline_score_matches_dataset():
    r = score_scenario([])
    assert r.base_score == pytest.approx(52.56, abs=0.01)
    assert r.base_n_crit == 2
    assert sorted(r.critical_cells) == ["nura:S1", "nura:S2"]
    assert r.base_d_avg == pytest.approx(56.86, abs=0.01)
    assert r.base_d_min == pytest.approx(49.18, abs=0.01)


def test_example_scenario_from_dataset():
    v = validate(EXAMPLE)
    assert v.valid, v.issues
    assert v.total_cost == 95
    r = score_scenario(EXAMPLE)
    assert r.score == pytest.approx(56.5, abs=0.1)
    assert r.delta == pytest.approx(4.0, abs=0.1)
    assert [s.first + "+" + s.second for s in r.synergies] == ["M10+M12"]
    assert r.n_crit == 0


def test_cheapest_set_valid():
    v = validate(CHEAPEST)
    assert v.valid and v.total_cost == 61


def test_lag_scaling_and_synergy_not_scaled():
    ds = load_dataset()
    r = score_scenario([Decision(measure_id="M10", district_id="nura"), Decision(measure_id="M12")])
    nura = next(d for d in r.districts if d.district_id == "nura")
    b1 = next(i for i in nura.indicators if i.code == "B1")
    # 12 × (8−1)/8 = 10.5 плюс синергия +2 без лага
    assert b1.delta == pytest.approx(10.5 + 2, abs=1e-6)
    assert ds.horizon == 8


def test_clip_to_100():
    r = score_scenario([Decision(measure_id="M10", district_id="esil"), Decision(measure_id="M9", district_id="esil")])
    esil = next(d for d in r.districts if d.district_id == "esil")
    b1 = next(i for i in esil.indicators if i.code == "B1")
    assert b1.final <= 100


@pytest.mark.parametrize(
    "decisions,rule",
    [
        (EXAMPLE[:4], "count"),
        (EXAMPLE[:4] + [Decision(measure_id="M7", district_id="nura")], "duplicate"),
        ([Decision(measure_id="M3", district_id="nura"), Decision(measure_id="M13", district_id="esil"), *EXAMPLE[:2], EXAMPLE[3]], "budget"),
        (EXAMPLE[:4] + [Decision(measure_id="M9", district_id="esil")], "max_per_direction"),
        ([Decision(measure_id="M1", district_id="esil"), Decision(measure_id="M3", district_id="nura"), Decision(measure_id="M9", district_id="nura"), Decision(measure_id="M10", district_id="nura"), Decision(measure_id="M12")], "incompatible"),
        ([Decision(measure_id="M4", district_id="nura"), Decision(measure_id="M7", district_id="nura"), Decision(measure_id="M9", district_id="nura"), Decision(measure_id="M10", district_id="nura"), Decision(measure_id="M12")], "incompatible"),
        ([Decision(measure_id="M7"), *EXAMPLE[1:]], "district_required"),
        ([Decision(measure_id="M12", district_id="nura"), *EXAMPLE[:3], EXAMPLE[4]], "district_forbidden"),
    ],
)
def test_validator_rules(decisions, rule):
    v = validate(decisions)
    assert not v.valid
    assert rule in {i.rule for i in v.issues}


def test_changing_decisions_changes_score():
    a = score_scenario(EXAMPLE).score
    b = score_scenario(CHEAPEST).score
    assert a != b


def test_oracle_and_swaps():
    res = oracle()
    assert res.n_valid > 500_000
    assert res.best_score >= score_scenario(EXAMPLE).score
    assert validate(res.best).valid
    assert 0 < percentile(score_scenario(EXAMPLE).score, res) <= 100
    swaps = best_swaps(CHEAPEST, limit=3)
    assert swaps and swaps[0]["gain"] > 0


def test_event_world():
    w = world_for_event("EV5")
    assert "M3" in w.blocked_measures
    v = validate([Decision(measure_id="M3", district_id="nura"), *EXAMPLE[1:]], w)
    assert "blocked_by_event" in {i.rule for i in v.issues}
    w4 = world_for_event("EV4")
    assert w4.budget == 85
    assert not validate(EXAMPLE, w4).valid


def test_shapley_sums_exactly_to_delta():
    """Маржинальные вклады не аддитивны (синергия считается дважды), Шепли — аддитивен точно."""
    r = score_scenario(EXAMPLE)
    exact_delta = r.score_exact - r.base_score_exact
    phi = shapley_contributions(EXAMPLE)

    assert sum(phi) == pytest.approx(exact_delta, abs=1e-9)
    # и это не совпадение с маржинальными: у пары M10+M12 бонус синергии должен разойтись пополам
    marginal = {m.measure_id: m.marginal_score for m in r.measures}
    shap = {m.measure_id: m.shapley_score for m in r.measures}
    assert shap["M10"] < marginal["M10"]
    assert shap["M12"] < marginal["M12"]
    assert sum(marginal.values()) > exact_delta  # сумма маржинальных завышена


def test_displayed_delta_is_consistent():
    """То, что видно на экране, должно сходиться: score − base == delta."""
    r = score_scenario(EXAMPLE)
    assert round(r.score - r.base_score, 2) == r.delta


def test_custom_event_spec_is_sanitized():
    """Ответ модели — не доверенный ввод: чужие районы, выдуманные меры и запредельные величины отсекаются."""
    ev = custom_event_from_spec({
        "title": "x" * 500,
        "shocks": [
            {"district": "nura", "indicator": "C1", "delta": -12},      # валидный
            {"district": "atlantis", "indicator": "C1", "delta": -12},  # нет такого района
            {"district": "nura", "indicator": "ZZ9", "delta": -12},     # нет такого показателя
            {"district": "esil", "indicator": "E2", "delta": -999},     # за пределами лимита
        ],
        "blocked_measures": ["M3", "M99"],
        "budget_delta": -500,
    })
    assert [(s.district, s.indicator) for s in ev.shocks] == [("nura", "C1"), ("esil", "E2")]
    assert ev.shocks[1].delta == -25.0          # зажато лимитом
    assert ev.blocked_measures == ["M3"]        # выдуманная мера отброшена
    assert ev.budget_delta == -40               # зажат лимит бюджета
    assert len(ev.title) <= 120
