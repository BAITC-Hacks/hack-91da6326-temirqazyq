"""Explicit paid smoke: two Russian turns, persistent <=8 attempts and <=$0.50."""

import argparse
import asyncio
import json
import sqlite3
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.ai.agent import AgentManager, RunRequest
from app.ai.provider import Provider
from app.ai.settings import Settings
from app.ai.usage import UsageLedger, UsageLimitError
from app.storage import Store

MAX_ATTEMPTS = 8
MAX_USD = 0.50
LIVE_DB = ROOT / "var" / "live-smoke.sqlite3"


class LiveLedger(UsageLedger):
    """SQLite trigger makes development limits atomic and persistent across days."""

    def __init__(self, path, settings):
        super().__init__(path, settings)
        with self._connect() as connection:
            connection.executescript("""
                CREATE TRIGGER IF NOT EXISTS live_smoke_guard
                BEFORE INSERT ON ai_usage_attempts
                BEGIN
                    SELECT CASE WHEN (SELECT COUNT(*) FROM ai_usage_attempts) >= 8
                        THEN RAISE(ABORT, 'LIVE_ATTEMPT_LIMIT') END;
                    SELECT CASE WHEN (SELECT COALESCE(SUM(accounted_cost), 0) FROM ai_usage_attempts)
                        + NEW.accounted_cost > 0.50
                        THEN RAISE(ABORT, 'LIVE_COST_LIMIT') END;
                END;
            """)

    def reserve(self, *args, **kwargs):
        try:
            return super().reserve(*args, **kwargs)
        except sqlite3.IntegrityError as error:
            code = str(error)
            if code in {"LIVE_ATTEMPT_LIMIT", "LIVE_COST_LIMIT"}:
                raise UsageLimitError(code, "Достигнут общий лимит платной live-проверки.") from None
            raise

    def totals(self):
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM ai_usage_attempts ORDER BY rowid").fetchall()
        return self._aggregate(rows)


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


async def run_live(settings: Settings, *, resume: bool = False) -> int:
    settings = settings.model_copy(update={
        "db_path": LIVE_DB, "ai_allow_template_fallback": False,
        "ai_daily_spend_limit_usd": min(settings.ai_daily_spend_limit_usd, MAX_USD),
        "ai_run_estimated_cost_limit_usd": min(settings.ai_run_estimated_cost_limit_usd, 0.10),
    })
    store = Store(LIVE_DB)
    provider = Provider(settings, LIVE_DB)
    provider.ledger = LiveLedger(LIVE_DB, settings)
    agent = AgentManager(settings, store, provider)
    receipt = ROOT / "var" / "live-smoke-report.json"
    report = json.loads(receipt.read_text(encoding="utf-8")) if resume and receipt.exists() else {}
    session = report.get("session_id") if resume else None
    if session and not store.get_session(session):
        await agent.close()
        raise ValueError("Сессия предыдущей проверки не найдена.")
    session = session or store.create_session()
    report = {"session_id": session, "requested_model": settings.openai_model,
              "runs": report.get("runs", []) if resume else [], "checks_passed": False}
    messages = [
        "Покажи три допустимых варианта с бюджетом не больше 90. Не используй M3. Отдельно покажи изменения школ и поликлиник Нуры.",
        "Теперь оставь минимум 20 единиц бюджета. Остальные ограничения сохрани.",
    ]
    if resume and report["runs"]:
        messages = messages[1:]
    code = 0
    try:
        for message in messages:
            previous = provider.ledger.totals()
            remaining = MAX_ATTEMPTS - previous["api_calls"]
            if remaining < 3:
                report["stopped"] = "Недостаточно оставшихся попыток для полного следующего хода."
                code = 1
                break
            settings.ai_max_model_calls_per_run = min(6, remaining)
            run = agent.start(session, RunRequest(message=message, request_id=uuid4().hex))
            task = agent.tasks[run["run_id"]]
            last_stage = None
            while not task.done():
                current = store.get_run(session, run["run_id"])
                if current["stage"] != last_stage:
                    emit({"run_id": run["run_id"], "stage": current["stage"]})
                    last_stage = current["stage"]
                await asyncio.sleep(0.25)
            await task
            run = store.get_run(session, run["run_id"])
            safe = {key: run[key] for key in ("run_id", "status", "error", "constraints", "metadata")}
            safe["tool_calls"] = run["tool_calls"]
            safe["scenarios"] = [{"scenario_id": row["scenario_id"], "provenance": row["provenance"],
                                  "budget": row["result"]["budget"], "score": row["result"]["score"]} for row in run["scenarios"]]
            safe["explanation_source"] = (run.get("explanation") or {}).get("source")
            report["runs"].append(safe)
            emit(safe)
            if run["status"] != "completed" or not run["metadata"]["used_llm"] or safe["explanation_source"] != "openai":
                code = 1
                break
            assert run["scenarios"] and run["tool_calls"] > 0
            assert "M3" in run["constraints"]["excluded_measure_ids"]
            assert run["constraints"]["max_budget"] == 90
            if len(report["runs"]) == 2:
                assert run["constraints"]["reserve_budget"] == 20
            budget = 80 if len(report["runs"]) == 2 else 90
            for row in run["scenarios"]:
                assert row["result"]["valid"] and row["result"]["budget"]["spent"] <= budget
                assert all(decision["measure_id"] != "M3" for decision in row["decisions"])
        report["checks_passed"] = code == 0 and len(report["runs"]) == 2
    except AssertionError:
        code = 1
        report["stopped"] = "Live-ответ не прошёл проверку ожидаемых условий; проверьте сохранённую квитанцию."
    finally:
        report["totals_all_live_attempts"] = provider.ledger.totals()
        report["status"] = ("passed" if all(run["status"] == "completed" for run in report["runs"]) else "followup_passed") if report["checks_passed"] else "incomplete"
        receipt.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        emit({"status": report["status"], "totals": report["totals_all_live_attempts"]})
        await agent.close()
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Explicitly authorize this paid smoke within its persistent cap")
    parser.add_argument("--resume", action="store_true", help="Continue with the follow-up in the saved session, preserving prior attempt costs")
    args = parser.parse_args()
    settings = Settings.from_env()
    if not (args.execute or settings.allow_live_ai_tests):
        emit({"status": "skipped", "reason": "Use --execute or ALLOW_LIVE_AI_TESTS=true to explicitly run paid checks."})
        return 0
    if not settings.public()["provider_available"]:
        emit({"status": "unavailable", "reason": "AI disabled, missing key, or unsupported provider/model; no paid calls made."})
        return 1
    return asyncio.run(run_live(settings, resume=args.resume))


if __name__ == "__main__":
    raise SystemExit(main())
