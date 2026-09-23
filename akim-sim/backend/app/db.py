"""SQLite-хранилище сценариев команд (лидерборд). Без ORM — одна таблица, stdlib."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path(os.environ.get("AKIM_DB_PATH", Path(__file__).resolve().parents[1] / "akim.db"))
_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    with _lock, _conn() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS scenarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team TEXT NOT NULL,
                event_id TEXT,
                decisions TEXT NOT NULL,
                score REAL NOT NULL,
                delta REAL NOT NULL,
                total_cost INTEGER NOT NULL,
                n_crit INTEGER NOT NULL,
                d_min REAL NOT NULL,
                result TEXT NOT NULL,
                analysis TEXT,
                note TEXT,
                created_at TEXT NOT NULL
            )"""
        )


def insert(team: str, event_id: Optional[str], decisions: List[Dict[str, Any]], result: Dict[str, Any], analysis: Optional[Dict[str, Any]], note: Optional[str]) -> int:
    with _lock, _conn() as c:
        cur = c.execute(
            "INSERT INTO scenarios (team, event_id, decisions, score, delta, total_cost, n_crit, d_min, result, analysis, note, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                team.strip()[:64],
                event_id,
                json.dumps(decisions, ensure_ascii=False),
                result["score"],
                result["delta"],
                result["total_cost"],
                result["n_crit"],
                result["d_min"],
                json.dumps(result, ensure_ascii=False),
                json.dumps(analysis, ensure_ascii=False) if analysis else None,
                (note or "")[:500],
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )
        return int(cur.lastrowid)


def _row(r: sqlite3.Row, full: bool) -> Dict[str, Any]:
    d = {
        "id": r["id"], "team": r["team"], "event_id": r["event_id"], "decisions": json.loads(r["decisions"]),
        "score": r["score"], "delta": r["delta"], "total_cost": r["total_cost"], "n_crit": r["n_crit"], "d_min": r["d_min"],
        "note": r["note"], "created_at": r["created_at"],
    }
    if full:
        d["result"] = json.loads(r["result"])
        d["analysis"] = json.loads(r["analysis"]) if r["analysis"] else None
    return d


def list_entries(event_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    with _lock, _conn() as c:
        if event_id is None:
            rows = c.execute("SELECT * FROM scenarios ORDER BY score DESC, total_cost ASC, created_at ASC LIMIT ?", (limit,)).fetchall()
        else:
            rows = c.execute("SELECT * FROM scenarios WHERE event_id IS ? ORDER BY score DESC, total_cost ASC, created_at ASC LIMIT ?", (event_id or None, limit)).fetchall()
    return [_row(r, full=False) for r in rows]


def get(entry_id: int) -> Optional[Dict[str, Any]]:
    with _lock, _conn() as c:
        r = c.execute("SELECT * FROM scenarios WHERE id = ?", (entry_id,)).fetchone()
    return _row(r, full=True) if r else None


def clear() -> None:
    with _lock, _conn() as c:
        c.execute("DELETE FROM scenarios")
