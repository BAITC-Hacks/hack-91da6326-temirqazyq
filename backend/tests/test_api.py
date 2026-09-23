from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    with TestClient(app) as test_client:
        sid = test_client.post("/api/sessions").json()["session_id"]
        test_client.headers["X-Session-ID"] = sid
        yield test_client


@pytest.fixture
def example():
    return {"decisions": [
        {"measure_id": "M7", "district": "Нура"},
        {"measure_id": "M8", "district": "Нура"},
        {"measure_id": "M10", "district": "Нура"},
        {"measure_id": "M12"},
        {"measure_id": "M5", "district": "Сарыарка"},
    ]}


def test_health_dataset_and_baseline(client):
    assert client.get("/health").json()["status"] == "ok"
    assert len(client.get("/api/districts").json()) == 5
    assert len(client.get("/api/measures").json()) == 14
    baseline = client.get("/api/base-state").json()
    assert baseline["score"]["after"] == pytest.approx(52.55768)
    assert len(baseline["critical_after"]) == 2


def test_preview_supports_empty_and_partial_but_final_requires_five(client):
    for decisions in [[], [{"measure_id": "M12"}]]:
        assert client.post("/api/scenario/preview", json={"decisions": decisions}).status_code == 200
        result = client.post("/api/scenario/simulate", json={"decisions": decisions})
        assert result.status_code == 422
        assert "score" not in result.json()
        assert result.json()["errors"][0]["code"] == "DECISION_COUNT"


def test_simulate_demo_and_explain(client, example):
    response = client.post("/api/scenario/simulate", json=example)
    assert response.status_code == 200
    result = response.json()
    assert result["score"]["after"] == pytest.approx(56.54307)
    assert result["budget"]["spent"] == 95
    assert len(result["activated_synergies"]) == 1
    assert len(result["measure_contributions"]) == 5
    explanation = client.post("/api/ai/explain", json=result)
    assert explanation.status_code == 200
    assert explanation.json()["source"] == "template"
    assert "56.54" in explanation.json()["summary"]


def test_explain_recomputes_client_metrics(client, example):
    result = client.post("/api/scenario/simulate", json=example).json()
    result["score"]["after"] = 999999
    result["budget"]["remaining"] = 999999
    explanation = client.post("/api/ai/explain", json=result).json()
    assert "999999" not in str(explanation)
    assert "56.54" in explanation["summary"]


def test_invalid_semantics_have_errors_and_no_score(client):
    result = client.post("/api/scenario/preview", json={"decisions": [
        {"measure_id": "M1", "district": "Нура"},
        {"measure_id": "M3", "district": "Есиль"},
    ]})
    assert result.status_code == 422
    assert "score" not in result.json()
    assert result.json()["errors"][0]["code"] == "INCOMPATIBLE_MEASURES"


@pytest.mark.parametrize("body", [
    {"decisions": [{"measure_id": "M12", "extra": 1}]},
    {"decisions": "wrong"},
    {"decisions": [None]},
    {"decisions": [{"district": "Нура"}]},
    {"wrong": []},
])
def test_request_shape_errors_are_structured(client, body):
    response = client.post("/api/scenario/preview", json=body)
    assert response.status_code == 422
    assert response.json()["valid"] is False
    assert response.json()["errors"][0]["code"] == "INVALID_REQUEST"
    assert "score" not in response.json()


def test_validate_reports_invalid_with_200(client):
    response = client.post("/api/scenario/validate", json={"decisions": []})
    assert response.status_code == 200
    assert response.json()["valid"] is False


def test_compare_returns_full_metrics_and_explanation(client, example):
    other = deepcopy(example)
    other["decisions"][-1] = {"measure_id": "M4", "district": "Сарыарка"}
    response = client.post("/api/scenario/compare", json={"scenario_a": example, "scenario_b": other})
    assert response.status_code == 200
    result = response.json()
    assert len(result["category_comparison"]) == 5
    assert result["scenario_a"]["budget"]["spent"] == 95
    assert result["scenario_b"]["budget"]["spent"] == 85
    assert result["explanation"]["source"] == "template"


def test_compare_rejects_incomplete_scenario(client, example):
    response = client.post("/api/scenario/compare", json={"scenario_a": example, "scenario_b": {"decisions": []}})
    assert response.status_code == 422
    assert "scenario_a" not in response.json()


def test_optimizer_via_http_and_bad_constraints(client):
    request = {"focus_district": "Нура", "priority": "weakest_district", "max_budget": 90, "reserve_budget": 10, "exclude_measures": ["M3"], "limit": 3}
    response = client.post("/api/optimizer/search", json=request)
    assert response.status_code == 200
    result = response.json()
    assert len(result["scenarios"]) == 3
    for scenario in result["scenarios"]:
        assert scenario["result"]["valid"]
        assert scenario["result"]["budget"]["spent"] <= 90
    bad = client.post("/api/optimizer/search", json={"priority": "invented"})
    assert bad.status_code == 422
    assert bad.json()["errors"][0]["code"] == "INVALID_REQUEST"


def test_openapi_available(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert "/api/optimizer/search" in response.json()["paths"]
