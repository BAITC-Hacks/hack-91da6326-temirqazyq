"""Small persistent SQLite repository with session-scoped parameterized queries."""

import json
import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY, constraints_json TEXT NOT NULL,
                    history_json TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS scenarios (
                    scenario_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                    name TEXT NOT NULL, decisions_json TEXT NOT NULL,
                    result_json TEXT NOT NULL, provenance TEXT NOT NULL,
                    constraints_json TEXT NOT NULL, dataset_version TEXT NOT NULL,
                    saved INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                );
                CREATE INDEX IF NOT EXISTS scenarios_session ON scenarios(session_id, created_at);
                CREATE TABLE IF NOT EXISTS ai_runs (
                    session_id TEXT NOT NULL, run_id TEXT NOT NULL, data_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL, PRIMARY KEY(session_id, run_id),
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                );
                CREATE TABLE IF NOT EXISTS ai_cache (
                    session_id TEXT NOT NULL, cache_key TEXT NOT NULL, data_json TEXT NOT NULL,
                    PRIMARY KEY(session_id, cache_key),
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                );
                CREATE TABLE IF NOT EXISTS ai_tool_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
                    run_id TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL,
                    summary_json TEXT NOT NULL, created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                );
            """)
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(scenarios)")}
            if "identity" not in columns:
                connection.execute("ALTER TABLE scenarios ADD COLUMN identity TEXT")
            connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS scenario_identity ON scenarios(session_id, identity)")

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def create_session(self) -> str:
        identifier = uuid4().hex
        with self._connection() as connection:
            connection.execute("INSERT INTO sessions VALUES (?, ?, ?, ?)", (identifier, "{}", "[]", _now()))
        return identifier

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        if row is None:
            return None
        return {"session_id": row["session_id"], "constraints": json.loads(row["constraints_json"]), "history": json.loads(row["history_json"])}

    def update_session(self, session_id: str, *, constraints: dict[str, Any] | None = None, history: list[Any] | None = None) -> None:
        with self._connection() as connection:
            if connection.execute("SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)).fetchone() is None:
                raise KeyError("Session does not exist")
            if constraints is not None:
                connection.execute("UPDATE sessions SET constraints_json = ? WHERE session_id = ?", (_json(constraints), session_id))
            if history is not None:
                connection.execute("UPDATE sessions SET history_json = ? WHERE session_id = ?", (_json(history[-40:]), session_id))

    @staticmethod
    def _scenario(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "scenario_id": row["scenario_id"], "name": row["name"],
            "decisions": json.loads(row["decisions_json"]), "result": json.loads(row["result_json"]),
            "provenance": row["provenance"], "constraints": json.loads(row["constraints_json"]),
            "dataset_version": row["dataset_version"], "saved": bool(row["saved"]), "created_at": row["created_at"],
        }

    def save_scenario(self, session_id: str, *, decisions: list[dict[str, Any]], result: dict[str, Any], provenance: str, constraints: dict[str, Any], dataset_version: str, name: str | None = None, saved: bool = False) -> dict[str, Any]:
        if provenance not in {"llm_generated", "algorithmic", "manual"}:
            raise ValueError("Unknown scenario provenance")
        if result.get("valid") is not True:
            raise ValueError("Only verified valid scenarios can be persisted")
        canonical = sorted(
            [{"measure_id": item["measure_id"], "district": item.get("district")} for item in decisions],
            key=lambda item: (item["measure_id"], item["district"] or ""),
        )
        identity = hashlib.sha256(_json({"decisions": canonical, "dataset_version": dataset_version, "provenance": provenance, "constraints": constraints}).encode("utf-8")).hexdigest()
        identifier = uuid4().hex
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT scenario_id FROM scenarios WHERE session_id = ? AND identity = ?", (session_id, identity)).fetchone()
            if existing:
                identifier = existing["scenario_id"]
                connection.execute(
                    "UPDATE scenarios SET saved = MAX(saved, ?), name = COALESCE(?, name), decisions_json = ?, result_json = ? WHERE session_id = ? AND scenario_id = ?",
                    (int(saved), name[:120] if name is not None else None, _json(decisions), _json(result), session_id, identifier),
                )
            else:
                connection.execute(
                    "INSERT INTO scenarios (scenario_id, session_id, name, decisions_json, result_json, provenance, constraints_json, dataset_version, saved, created_at, identity) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (identifier, session_id, (name or "Сценарий")[:120], _json(decisions), _json(result), provenance, _json(constraints), dataset_version, int(saved), _now(), identity),
                )
        return self.get_scenario(session_id, identifier)  # type: ignore[return-value]

    def get_scenario(self, session_id: str, scenario_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM scenarios WHERE session_id = ? AND scenario_id = ?", (session_id, scenario_id)).fetchone()
        return self._scenario(row) if row else None

    def list_scenarios(self, session_id: str, saved_only: bool = False) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM scenarios WHERE session_id = ? AND (? = 0 OR saved = 1) ORDER BY created_at DESC, scenario_id",
                (session_id, int(saved_only)),
            ).fetchall()
        return [self._scenario(row) for row in rows]

    def mark_saved(self, session_id: str, scenario_id: str, name: str | None = None) -> dict[str, Any] | None:
        with self._connection() as connection:
            if name is None:
                connection.execute("UPDATE scenarios SET saved = 1 WHERE session_id = ? AND scenario_id = ?", (session_id, scenario_id))
            else:
                connection.execute("UPDATE scenarios SET saved = 1, name = ? WHERE session_id = ? AND scenario_id = ?", (name[:120], session_id, scenario_id))
        return self.get_scenario(session_id, scenario_id)

    def put_run(self, session_id: str, run_id: str, data: dict[str, Any]) -> None:
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO ai_runs VALUES (?, ?, ?, ?) ON CONFLICT(session_id, run_id) DO UPDATE SET data_json = excluded.data_json, updated_at = excluded.updated_at",
                (session_id, run_id, _json(data), _now()),
            )

    def get_run(self, session_id: str, run_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute("SELECT data_json FROM ai_runs WHERE session_id = ? AND run_id = ?", (session_id, run_id)).fetchone()
        return json.loads(row["data_json"]) if row else None

    def list_runs(self, session_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute("SELECT data_json FROM ai_runs WHERE session_id = ? ORDER BY updated_at DESC, run_id LIMIT ?", (session_id, min(max(limit, 1), 100))).fetchall()
        return [json.loads(row["data_json"]) for row in rows]

    def recover_runs(self) -> int:
        recovered = 0
        terminal = {"completed", "failed", "cancelled", "interrupted", "needs_clarification", "clarification_required"}
        with self._connection() as connection:
            rows = connection.execute("SELECT session_id, run_id, data_json FROM ai_runs").fetchall()
            for row in rows:
                data = json.loads(row["data_json"])
                if data.get("status") in terminal:
                    continue
                data["status"] = "interrupted"
                data["stage"] = "interrupted"
                data["error"] = {"code": "SERVER_RESTARTED", "message": "Выполнение прервано перезапуском сервера; начните новую операцию."}
                connection.execute("UPDATE ai_runs SET data_json = ?, updated_at = ? WHERE session_id = ? AND run_id = ?", (_json(data), _now(), row["session_id"], row["run_id"]))
                recovered += 1
        return recovered

    def cache_get(self, session_id: str, key: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute("SELECT data_json FROM ai_cache WHERE session_id = ? AND cache_key = ?", (session_id, key)).fetchone()
        return json.loads(row["data_json"]) if row else None

    def cache_set(self, session_id: str, key: str, data: dict[str, Any]) -> None:
        with self._connection() as connection:
            connection.execute("INSERT INTO ai_cache VALUES (?, ?, ?) ON CONFLICT(session_id, cache_key) DO UPDATE SET data_json = excluded.data_json", (session_id, key, _json(data)))

    def log_tool(self, session_id: str, run_id: str, name: str, status: str, summary: dict[str, Any] | str) -> None:
        with self._connection() as connection:
            connection.execute("INSERT INTO ai_tool_logs (session_id, run_id, name, status, summary_json, created_at) VALUES (?, ?, ?, ?, ?, ?)", (session_id, run_id, name[:80], status[:40], _json(summary), _now()))
