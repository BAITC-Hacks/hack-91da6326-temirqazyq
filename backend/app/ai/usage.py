"""Persistent application cost accounting, including conservative reservations."""

import json
import math
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from .settings import Settings


class UsageLimitError(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


class UsageLedger:
    def __init__(self, db_path: str | Path, settings: Settings):
        self.db_path, self.settings = Path(db_path), settings
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.pricing = json.loads(settings.ai_pricing_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.pricing = {"models": {}}
        with self._connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS ai_usage_attempts (
                id TEXT PRIMARY KEY, run_id TEXT NOT NULL, day TEXT NOT NULL,
                requested_model TEXT NOT NULL, actual_model TEXT,
                status TEXT NOT NULL, reserved_cost REAL NOT NULL, accounted_cost REAL NOT NULL,
                estimated_cost REAL, input_tokens INTEGER, output_tokens INTEGER,
                cached_input_tokens INTEGER, usage_unknown INTEGER NOT NULL DEFAULT 1,
                successful_response INTEGER NOT NULL DEFAULT 0, error_code TEXT
            )""")
            connection.execute("CREATE INDEX IF NOT EXISTS ai_usage_run ON ai_usage_attempts(run_id)")
            connection.execute("CREATE INDEX IF NOT EXISTS ai_usage_day ON ai_usage_attempts(day)")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA journal_mode=WAL")
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def price(self, model: str) -> dict[str, float] | None:
        raw = self.pricing.get("models", {}).get(model)
        if not isinstance(raw, dict):
            return None
        try:
            prices = {key: float(raw[key]) for key in ("input", "cached_input", "output")}
        except (KeyError, TypeError, ValueError):
            return None
        return prices if all(math.isfinite(value) and value >= 0 for value in prices.values()) else None

    def reserve(self, run_id: str, input_bound: int, output_bound: int) -> str:
        model = self.settings.openai_model
        price = self.price(model)
        if price is None:
            raise UsageLimitError("UNKNOWN_PRICING", "Тариф модели неизвестен; платный вызов заблокирован до настройки тарифа.")
        cost = (input_bound * max(price["input"], price["cached_input"]) + output_bound * price["output"]) / 1_000_000
        day = datetime.now(timezone.utc).date().isoformat()
        attempt_id = uuid4().hex
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            count, run_cost = connection.execute(
                "SELECT COUNT(*), COALESCE(SUM(accounted_cost),0) FROM ai_usage_attempts WHERE run_id=?", (run_id,)
            ).fetchone()
            daily = connection.execute(
                "SELECT COALESCE(SUM(accounted_cost),0) FROM ai_usage_attempts WHERE day=?", (day,)
            ).fetchone()[0]
            if count >= self.settings.ai_max_model_calls_per_run:
                raise UsageLimitError("MODEL_CALL_LIMIT", "Достигнут лимит обращений к модели для операции.")
            if run_cost + cost > self.settings.ai_run_estimated_cost_limit_usd + 1e-12:
                raise UsageLimitError("RUN_COST_LIMIT", "Следующий вызов превысит бюджет AI-операции.")
            if daily + cost > self.settings.ai_daily_spend_limit_usd + 1e-12:
                raise UsageLimitError("DAILY_COST_LIMIT", "Достигнут дневной лимит расходов этого приложения.")
            connection.execute(
                "INSERT INTO ai_usage_attempts(id,run_id,day,requested_model,status,reserved_cost,accounted_cost) VALUES(?,?,?,?,?,?,?)",
                (attempt_id, run_id, day, model, "pending", cost, cost),
            )
        return attempt_id

    def finish(self, attempt_id: str, response: dict[str, Any]) -> None:
        usage = response.get("usage")
        actual_model = response.get("model") or None
        tokens = None
        if isinstance(usage, dict):
            incoming, outgoing = usage.get("input_tokens"), usage.get("output_tokens")
            details = usage.get("input_tokens_details") or {}
            cached = details.get("cached_tokens", 0) if isinstance(details, dict) else None
            if all(type(value) is int and value >= 0 for value in (incoming, outgoing, cached)) and cached <= incoming:
                tokens = (incoming, outgoing, cached)
        price = self.price(actual_model or self.settings.openai_model)
        cost = None
        if tokens is not None and price is not None:
            incoming, outgoing, cached = tokens
            cost = ((incoming - cached) * price["input"] + cached * price["cached_input"] + outgoing * price["output"]) / 1_000_000
        with self._connect() as connection:
            connection.execute(
                """UPDATE ai_usage_attempts SET status='succeeded',actual_model=?,successful_response=1,
                estimated_cost=?,accounted_cost=COALESCE(?,reserved_cost),input_tokens=?,output_tokens=?,
                cached_input_tokens=?,usage_unknown=? WHERE id=?""",
                (actual_model, cost, cost, *(tokens or (None, None, None)), int(tokens is None), attempt_id),
            )

    def fail(self, attempt_id: str, code: str) -> None:
        # A failed/cancelled HTTP attempt can still have incurred inference cost.
        # Without authoritative usage, retain the reservation across restarts.
        with self._connect() as connection:
            connection.execute(
                "UPDATE ai_usage_attempts SET status='failed',error_code=?,usage_unknown=1 WHERE id=?", (code, attempt_id)
            )

    def _aggregate(self, rows: list[sqlite3.Row]) -> dict[str, Any]:
        unknown = any(row["usage_unknown"] for row in rows)
        cost_unknown = any(row["estimated_cost"] is None for row in rows) or (not rows and self.price(self.settings.openai_model) is None)
        incoming = sum(row["input_tokens"] or 0 for row in rows)
        outgoing = sum(row["output_tokens"] or 0 for row in rows)
        cached = sum(row["cached_input_tokens"] or 0 for row in rows)
        known = sum(row["estimated_cost"] or 0 for row in rows)
        reserved = sum(row["accounted_cost"] for row in rows if row["estimated_cost"] is None)
        reported = any(row["input_tokens"] is not None for row in rows)
        return {
            "api_calls": len(rows), "input_tokens": incoming, "output_tokens": outgoing,
            "cached_input_tokens": cached, "usage_unknown": unknown,
            "usage": {"input_tokens": incoming, "output_tokens": outgoing, "cached_input_tokens": cached,
                      "total_tokens": incoming + outgoing} if reported else None,
            "estimated_cost_usd": None if cost_unknown else known,
            "cost_unknown": cost_unknown,
            "known_cost_usd": known, "reserved_cost_usd": reserved,
            "accounted_cost_usd": known + reserved,
            "unknown_usage_attempts": sum(bool(row["usage_unknown"]) for row in rows),
            "in_flight_calls": sum(row["status"] == "pending" for row in rows),
        }

    def metadata(self, run_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM ai_usage_attempts WHERE run_id=? ORDER BY rowid", (run_id,)).fetchall()
        actual = next((row["actual_model"] for row in reversed(rows) if row["actual_model"]), None)
        return {
            "provider": self.settings.ai_provider, "requested_model": rows[0]["requested_model"] if rows else self.settings.openai_model,
            "actual_model": actual, "used_llm": any(row["successful_response"] for row in rows),
            "fallback_used": False, "cache_hit": False, **self._aggregate(rows),
        }

    def summary(self) -> dict[str, Any]:
        day = datetime.now(timezone.utc).date().isoformat()
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM ai_usage_attempts WHERE day=? ORDER BY rowid", (day,)).fetchall()
        return {
            "day": day, "timezone": "UTC", "daily_limit_usd": self.settings.ai_daily_spend_limit_usd,
            "scope": "Расходы этого приложения; не баланс аккаунта OpenAI.",
            "pricing_source": self.pricing.get("source"), "pricing_verified_at": self.pricing.get("verified_at"),
            **self._aggregate(rows),
        }
