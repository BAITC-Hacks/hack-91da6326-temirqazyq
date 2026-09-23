"""Exercise the running full stack through the same Next.js proxy as the UI."""

import argparse
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:3000")
    args = parser.parse_args()
    origin = args.base_url.rstrip("/")
    session = {}

    def api(path: str, body=None, expected: int = 200):
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = Request(origin + "/api/" + path, data=data, headers={"Content-Type": "application/json", **session})
        try:
            with urlopen(request, timeout=45) as response:
                status, payload = response.status, json.load(response)
        except HTTPError as error:
            status, payload = error.code, json.load(error)
        assert status == expected, (path, status, payload)
        return payload

    with urlopen(origin, timeout=20) as response:
        assert response.status == 200
        assert "Akim AI" in response.read().decode("utf-8")
    assert len(api("districts")) == 5
    assert len(api("measures")) == 14
    baseline = api("base-state")
    assert abs(baseline["score"]["after"] - 52.55768) < 1e-8
    preview = api("scenario/preview", {"decisions": [{"measure_id": "M7", "district": "Нура"}]})
    assert preview["districts"]["Нура"]["indicators_after"]["S1"] == 48
    assert preview["budget"]["remaining"] == 76
    example = {"decisions": [
        {"measure_id": "M7", "district": "Нура"},
        {"measure_id": "M8", "district": "Нура"},
        {"measure_id": "M10", "district": "Нура"},
        {"measure_id": "M12"},
        {"measure_id": "M5", "district": "Сарыарка"},
    ]}
    assert api("scenario/validate", example)["valid"]
    result = api("scenario/simulate", example)
    assert abs(result["score"]["after"] - 56.54307) < 1e-8
    assert result["budget"]["spent"] == 95
    assert len(result["activated_synergies"]) == 1
    assert not result["critical_after"]
    assert len(result["measure_contributions"]) == 5
    invalid = api("scenario/preview", {"decisions": [
        {"measure_id": "M1", "district": "Нура"},
        {"measure_id": "M3", "district": "Есиль"},
    ]}, expected=422)
    assert not invalid["valid"] and "score" not in invalid
    session["X-Session-ID"] = api("sessions", {})["session_id"]
    usage_before = api("ai/usage")
    saved = api("scenarios", {**example, "name": "Контрольный сценарий", "provenance": "manual"})
    assert api(f"scenarios/{saved['scenario_id']}")["result"]["score"] == result["score"]
    assert api(f"scenarios/{saved['scenario_id']}/export")["saved"]
    alternatives = api("optimizer/search", {
        "focus_district": "Нура", "max_budget": 90, "reserve_budget": 10,
        "exclude_measures": ["M3"], "priority": "weakest_district", "limit": 3,
    })
    assert len(alternatives["scenarios"]) >= 3
    for alternative in alternatives["scenarios"]:
        assert alternative["result"]["budget"]["spent"] <= 90
        assert all(decision["measure_id"] != "M3" for decision in alternative["decisions"])
        assert api("scenario/validate", {"decisions": alternative["decisions"]})["valid"]
    a, b = alternatives["scenarios"][:2]
    comparison = api("scenario/compare", {
        "scenario_a": {"decisions": a["decisions"]},
        "scenario_b": {"decisions": b["decisions"]},
    })
    assert len(comparison["category_comparison"]) == 5
    saved_b = api("scenarios", {"decisions": b["decisions"], "name": "Алгоритмический вариант", "provenance": "algorithmic"})
    assert len(api("scenarios/compare", {"scenario_ids": [saved["scenario_id"], saved_b["scenario_id"]]})["scenarios"]) == 2
    assert api("ai/usage")["api_calls"] == usage_before["api_calls"]
    print(json.dumps({
        "status": "passed", "base_score": baseline["score"]["after"],
        "demo_score": result["score"]["after"], "demo_budget": result["budget"]["spent"],
        "alternatives": len(alternatives["scenarios"]),
        "paid_api_calls": 0, "search_ms": alternatives["search"]["elapsed_ms"],
        "checked": "HTTP page, datasets, preview, final, conflicts, search, comparison, session, save/load/export via Next.js proxy",
    }, indent=2))


if __name__ == "__main__":
    main()
