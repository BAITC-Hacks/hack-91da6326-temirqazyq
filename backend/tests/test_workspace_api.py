"""Session/persistence HTTP tests with an isolated app and no provider client."""

import json
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.ai.settings import Settings
from app.api.workspace import router
from app.storage import Store


DEMO = [
    {"measure_id": "M7", "district": "Нура"}, {"measure_id": "M8", "district": "Нура"},
    {"measure_id": "M10", "district": "Нура"}, {"measure_id": "M12"},
    {"measure_id": "M5", "district": "Сарыарка"},
]


@pytest.fixture
def workspace(tmp_path):
    store = Store(tmp_path / "workspace.sqlite3")
    application = FastAPI()
    application.state.agent = SimpleNamespace(
        store=store,
        settings=Settings(openai_api_key="offline-api-test-key", db_path=store.path),
        provider=SimpleNamespace(ledger=SimpleNamespace(summary=lambda: {"attempts": 0})),
    )
    application.include_router(router)
    with TestClient(application) as client:
        session = client.post("/api/sessions").json()["session_id"]
        yield client, store, session, {"X-Session-ID": session}


def post_scenario(client, headers, **changes):
    response = client.post("/api/scenarios", headers=headers, json={"name": "Проверенный вариант", "decisions": DEMO, **changes})
    return response


def test_session_required_and_public_ai_configuration_never_exposes_key(workspace):
    client, store, session, headers = workspace
    assert len(session) == 32
    assert client.get("/api/scenarios").status_code == 401
    assert client.get("/api/sessions/current", headers={"X-Session-ID": "f" * 32}).status_code == 401
    state = client.get("/api/sessions/current", headers=headers).json()
    assert state["session_id"] == session
    assert state["constraints"]["requested_scenario_count"] == 3
    assert state["history"] == []
    config = client.get("/api/ai/config")
    assert config.status_code == 200
    assert "offline-api-test-key" not in config.text
    assert "openai_api_key" not in config.json()
    assert config.json()["key_configured"]


def test_manual_save_list_load_export_and_persistent_deduplication(workspace):
    client, store, session, headers = workspace
    created = post_scenario(client, headers)
    assert created.status_code == 200
    row = created.json()
    assert row["result"]["score"]["after"] == pytest.approx(56.54307)
    assert row["provenance"] == "manual"
    assert row["saved"]
    duplicate = post_scenario(client, headers, name="Другое имя", decisions=list(reversed(DEMO))).json()
    assert duplicate["scenario_id"] == row["scenario_id"]
    assert len(client.get("/api/scenarios", headers=headers).json()) == 1
    path = f"/api/scenarios/{row['scenario_id']}"
    assert client.get(path, headers=headers).json()["name"] == "Другое имя"
    exported = client.get(path + "/export", headers=headers)
    assert exported.status_code == 200
    assert "attachment" in exported.headers["content-disposition"]
    assert exported.json()["decisions"] == row["decisions"]
    reopened = Store(store.path)
    assert reopened.get_scenario(session, row["scenario_id"])["saved"]


def test_save_requires_final_valid_scenario_and_rejects_model_numbers(workspace):
    client, store, session, headers = workspace
    invalid = post_scenario(client, headers, decisions=DEMO[:4])
    assert invalid.status_code == 422
    assert not invalid.json()["valid"]
    assert "score" not in invalid.json()
    for changes in [{"score": 100}, {"cost": 0}, {"provenance": "llm_generated"}]:
        assert post_scenario(client, headers, **changes).status_code == 422
    limited = post_scenario(client, headers, constraints={"max_budget": 90})
    assert limited.status_code == 422
    assert any(error["code"] == "USER_BUDGET_EXCEEDED" for error in limited.json()["errors"])
    assert client.get("/api/scenarios", headers=headers).json() == []


def test_scenario_save_export_compare_and_run_ids_are_session_isolated(workspace):
    client, store, session, headers = workspace
    first = post_scenario(client, headers).json()
    alternate = [dict(item) for item in DEMO]
    alternate[-1] = {"measure_id": "M11", "district": "Алматы"}
    second = post_scenario(client, headers, decisions=alternate).json()
    foreign_session = client.post("/api/sessions").json()["session_id"]
    foreign = {"X-Session-ID": foreign_session}
    prefix = f"/api/scenarios/{first['scenario_id']}"
    assert client.get(prefix, headers=foreign).status_code == 404
    assert client.get(prefix + "/export", headers=foreign).status_code == 404
    assert client.post(prefix + "/save", headers=foreign, json={}).status_code == 404
    assert client.get("/api/scenarios", headers=foreign).json() == []
    comparison = {"scenario_ids": [first["scenario_id"], second["scenario_id"]]}
    assert client.post("/api/scenarios/compare", headers=foreign, json=comparison).status_code == 404
    store.put_run(session, "private-run", {"status": "completed"})
    assert client.get("/api/ai/runs/private-run", headers=foreign).status_code == 404


def test_compare_and_export_recompute_persisted_metrics_from_decisions(workspace):
    client, store, session, headers = workspace
    first = post_scenario(client, headers).json()
    alternate = [dict(item) for item in DEMO]
    alternate[-1] = {"measure_id": "M11", "district": "Алматы"}
    second = post_scenario(client, headers, decisions=alternate).json()
    corrupted = first["result"]
    corrupted["score"]["after"] = 999999
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE scenarios SET result_json = ? WHERE scenario_id = ?", (json.dumps(corrupted), first["scenario_id"]))
    comparison = client.post("/api/scenarios/compare", headers=headers, json={"scenario_ids": [first["scenario_id"], second["scenario_id"]]})
    assert comparison.status_code == 200
    rows = comparison.json()["scenarios"]
    assert rows[0]["result"]["score"]["after"] == pytest.approx(56.54307)
    assert len(comparison.json()["category_comparison"]) == 5
    exported = client.get(f"/api/scenarios/{first['scenario_id']}/export", headers=headers).json()
    assert exported["result"]["score"]["after"] == pytest.approx(56.54307)
    duplicates = client.post("/api/scenarios/compare", headers=headers, json={"scenario_ids": [first["scenario_id"], first["scenario_id"]]})
    assert duplicates.status_code == 422


def test_saved_filter_mark_and_dataset_mismatch_errors(workspace):
    client, store, session, headers = workspace
    row = post_scenario(client, headers, saved=False).json()
    assert client.get("/api/scenarios?saved_only=true", headers=headers).json() == []
    marked = client.post(f"/api/scenarios/{row['scenario_id']}/save", headers=headers, json={"name": "Избранный"})
    assert marked.status_code == 200
    assert marked.json()["saved"]
    assert marked.json()["name"] == "Избранный"
    assert len(client.get("/api/scenarios?saved_only=true", headers=headers).json()) == 1
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE scenarios SET dataset_version = ? WHERE scenario_id = ?", ("old-version", row["scenario_id"]))
    assert client.get(f"/api/scenarios/{row['scenario_id']}", headers=headers).status_code == 409
    assert client.get(f"/api/scenarios/{row['scenario_id']}/export", headers=headers).status_code == 409
