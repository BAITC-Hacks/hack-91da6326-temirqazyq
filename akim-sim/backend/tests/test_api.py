import os
import tempfile

os.environ["AKIM_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["LLM_PROVIDER"] = "none"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
EXAMPLE = [
    {"measure_id": "M7", "district_id": "nura"},
    {"measure_id": "M8", "district_id": "nura"},
    {"measure_id": "M10", "district_id": "nura"},
    {"measure_id": "M12"},
    {"measure_id": "M5", "district_id": "saryarka"},
]


def test_meta_and_health():
    with client:
        assert client.get("/api/health").json()["ok"]
        m = client.get("/api/meta").json()
        assert m["rules"]["budget"] == 100 and len(m["measures"]) == 14 and m["base_score"] == 52.56


def test_score_and_budget_guard():
    with client:
        r = client.post("/api/score", json={"decisions": EXAMPLE}).json()
        assert r["validation"]["valid"] and abs(r["result"]["score"] - 56.54) < 0.01
        bad = EXAMPLE[:3] + [EXAMPLE[4], {"measure_id": "M3", "district_id": "esil"}]  # 111 > 100
        r = client.post("/api/score", json={"decisions": bad}).json()
        assert not r["validation"]["valid"] and r["result"] is None
        assert any(i["rule"] == "budget" for i in r["validation"]["issues"])
        assert client.post("/api/analyze", json={"decisions": bad}).status_code == 422


def test_analyze_council_oracle_fallback():
    with client:
        a = client.post("/api/analyze", json={"decisions": EXAMPLE}).json()
        assert a["analyst"]["_mode"] == "fallback" and a["analyst"]["strengths"]
        assert a["advisor"]["recommendations"][0]["verified"]
        assert a["oracle"]["best_score"] >= 56.54
        c = client.post("/api/council", json={"decisions": EXAMPLE}).json()
        assert len(c["speeches"]) == 4
        o = client.get("/api/oracle").json()
        assert o["n_valid"] > 500_000 and o["pareto"]
        p = client.post("/api/oracle/position", json={"decisions": EXAMPLE}).json()
        assert 99 < p["percentile"] <= 100


def test_event_leaderboard_compare_report():
    with client:
        ev = client.post("/api/event/trigger", json={"decisions": EXAMPLE, "trigger_event_id": "EV5"}).json()
        assert ev["event"]["id"] == "EV5" and "M3" in ev["world"]["blocked_measures"]
        assert ev["narration"]["briefing"]
        e1 = client.post("/api/leaderboard", json={"team": "Alpha", "decisions": EXAMPLE}).json()
        cheap = [{"measure_id": "M9", "district_id": "nura"}, {"measure_id": "M11", "district_id": "esil"}, {"measure_id": "M10", "district_id": "nura"}, {"measure_id": "M12"}, {"measure_id": "M4", "district_id": "saryarka"}]
        e2 = client.post("/api/leaderboard", json={"team": "Beta", "decisions": cheap}).json()
        lb = client.get("/api/leaderboard").json()
        assert lb[0]["team"] == "Alpha" and lb[0]["rank"] == 1 and lb[1]["team"] == "Beta"
        cmp_ = client.post("/api/compare", json={"a": {"decisions": EXAMPLE}, "b": {"decisions": cheap}}).json()
        assert cmp_["score_diff"] < 0 and cmp_["only_a"]
        html = client.get(f"/api/report/{e1['id']}").text
        assert "Alpha" in html and "56.54" in html
        assert e2["id"] != e1["id"]
