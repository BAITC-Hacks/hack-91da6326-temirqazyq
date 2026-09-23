import sqlite3

import pytest

from app.storage import Store


def test_saved_scenario_survives_restart_and_is_session_scoped(tmp_path):
    store = Store(tmp_path / "app.sqlite3")
    first, other = store.create_session(), store.create_session()
    row = store.save_scenario(first, decisions=[], result={"valid": True}, provenance="manual", constraints={"max_budget": 90}, dataset_version="v1", name="Name'; DROP TABLE scenarios; --")
    assert store.get_scenario(other, row["scenario_id"]) is None
    assert store.mark_saved(other, row["scenario_id"], "wrong") is None
    assert store.list_scenarios(first, saved_only=True) == []
    store.mark_saved(first, row["scenario_id"], "Сохранённый вариант")
    reopened = Store(store.path)
    saved = reopened.list_scenarios(first, saved_only=True)
    assert len(saved) == 1
    assert saved[0]["name"] == "Сохранённый вариант"
    assert saved[0]["constraints"] == {"max_budget": 90}
    assert saved[0]["provenance"] == "manual"
    assert reopened.list_scenarios(other) == []
    assert reopened.get_scenario(first, "' OR 1=1 --") is None


def test_session_state_and_history_survive_restart_with_bounded_history(tmp_path):
    store = Store(tmp_path / "app.sqlite3")
    session = store.create_session()
    store.update_session(session, constraints={"reserve_budget": 20}, history=[{"content": str(index)} for index in range(55)])
    reopened = Store(store.path)
    state = reopened.get_session(session)
    assert state["constraints"] == {"reserve_budget": 20}
    assert len(state["history"]) == 40
    assert state["history"][0]["content"] == "15"
    reopened.update_session(session, constraints={"max_budget": 90})
    assert len(reopened.get_session(session)["history"]) == 40
    assert reopened.get_session("unknown") is None
    with pytest.raises(KeyError):
        reopened.update_session("unknown", history=[])


def test_run_recovery_and_cache_isolation(tmp_path):
    store = Store(tmp_path / "app.sqlite3")
    first, second = store.create_session(), store.create_session()
    store.put_run(first, "active", {"status": "running", "usage": {"input_tokens": 12}})
    store.put_run(first, "done", {"status": "completed"})
    store.cache_set(first, "same", {"valid": False})
    assert store.cache_get(second, "same") is None
    assert store.get_run(second, "active") is None
    reopened = Store(store.path)
    assert reopened.recover_runs() == 1
    assert reopened.get_run(first, "active")["status"] == "interrupted"
    assert reopened.get_run(first, "active")["usage"]["input_tokens"] == 12
    assert reopened.get_run(first, "done")["status"] == "completed"
    assert reopened.recover_runs() == 0


def test_store_rejects_invalid_scenarios_and_records_safe_tool_summary(tmp_path):
    store = Store(tmp_path / "app.sqlite3")
    session = store.create_session()
    with pytest.raises(ValueError):
        store.save_scenario(session, decisions=[], result={"valid": False}, provenance="manual", constraints={}, dataset_version="v1")
    store.log_tool(session, "run", "evaluate_scenarios", "rejected", {"error_codes": ["INVALID_CANDIDATE"]})
    with sqlite3.connect(store.path) as connection:
        row = connection.execute("SELECT name, summary_json FROM ai_tool_logs").fetchone()
    assert row[0] == "evaluate_scenarios"
    assert "INVALID_CANDIDATE" in row[1]


def test_save_deduplicates_canonical_decisions_but_preserves_provenance_and_session(tmp_path):
    store = Store(tmp_path / "app.sqlite3")
    session, second = store.create_session(), store.create_session()
    decisions = [{"measure_id": "M12"}, {"measure_id": "M7", "district": "Нура"}]
    common = {"result": {"valid": True}, "provenance": "manual", "constraints": {}, "dataset_version": "v1"}
    first = store.save_scenario(session, decisions=decisions, name="Initial", **common)
    duplicate = store.save_scenario(session, decisions=[{"measure_id": "M7", "district": "Нура"}, {"measure_id": "M12", "district": None}], name="Saved label", saved=True, **common)
    assert duplicate["scenario_id"] == first["scenario_id"]
    assert duplicate["saved"]
    assert duplicate["name"] == "Saved label"
    assert len(store.list_scenarios(session)) == 1
    third = store.save_scenario(session, decisions=decisions, **common)
    assert third["saved"]
    assert third["name"] == "Saved label"
    alternate = store.save_scenario(session, decisions=decisions, **{**common, "provenance": "llm_generated"})
    assert alternate["scenario_id"] != first["scenario_id"]
    isolated = store.save_scenario(second, decisions=decisions, **common)
    assert isolated["scenario_id"] != first["scenario_id"]
    changed = store.save_scenario(session, decisions=decisions, **{**common, "constraints": {"max_budget": 90}})
    assert changed["scenario_id"] != first["scenario_id"]


def test_list_runs_is_recent_first_bounded_and_session_scoped(tmp_path):
    store = Store(tmp_path / "app.sqlite3")
    session, second = store.create_session(), store.create_session()
    store.put_run(session, "a", {"id": "a", "status": "completed"})
    store.put_run(second, "other", {"id": "other", "status": "completed"})
    store.put_run(session, "b", {"id": "b", "status": "running"})
    assert [row["id"] for row in store.list_runs(session)] == ["b", "a"]
    assert [row["id"] for row in store.list_runs(session, limit=1)] == ["b"]


def test_deduplicated_save_refreshes_authoritative_engine_result(tmp_path):
    store = Store(tmp_path / "app.sqlite3")
    session = store.create_session()
    common = {"decisions": [{"measure_id": "M12"}], "provenance": "manual", "constraints": {}, "dataset_version": "v1"}
    initial = store.save_scenario(session, result={"valid": True, "score": {"after": 999999}}, **common)
    refreshed = store.save_scenario(session, result={"valid": True, "score": {"after": 53.25}}, **common)
    assert refreshed["scenario_id"] == initial["scenario_id"]
    assert refreshed["result"]["score"]["after"] == 53.25
    assert store.get_scenario(session, initial["scenario_id"])["result"]["score"]["after"] == 53.25
