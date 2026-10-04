"""SQLite-backed append-only audit trail and order ledger (CDR-style: every
signal -> decision -> order is a row you can replay)."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from .config import DATA_DIR

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
  kind TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS orders (
  client_id TEXT PRIMARY KEY, ts REAL NOT NULL, venue TEXT NOT NULL,
  symbol TEXT NOT NULL, side TEXT NOT NULL, notional REAL NOT NULL,
  status TEXT NOT NULL, signal_id TEXT);
CREATE TABLE IF NOT EXISTS pnl (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
  venue TEXT NOT NULL, realized REAL NOT NULL);
CREATE TABLE IF NOT EXISTS seen_signals (signal_id TEXT PRIMARY KEY, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS day_start (day TEXT PRIMARY KEY, equity REAL NOT NULL);
"""


class Store:
    def __init__(self, path: Path | str | None = None):
        if path is None:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            path = DATA_DIR / "audit.db"
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.executescript(_SCHEMA)

    def audit(self, kind: str, payload: dict) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO audit(ts, kind, payload) VALUES (?,?,?)",
                (time.time(), kind, json.dumps(payload, default=str)),
            )

    def record_order(self, client_id, venue, symbol, side, notional, status, signal_id=None):
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO orders VALUES (?,?,?,?,?,?,?,?)",
                (client_id, time.time(), venue, symbol, side, notional, status, signal_id),
            )

    def record_pnl(self, venue: str, realized: float) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO pnl(ts, venue, realized) VALUES (?,?,?)",
                (time.time(), venue, realized),
            )

    def mark_signal_seen(self, signal_id: str) -> bool:
        """True if newly recorded, False if it was a duplicate."""
        with self._lock, self._db:
            cur = self._db.execute(
                "INSERT OR IGNORE INTO seen_signals VALUES (?,?)", (signal_id, time.time())
            )
            return cur.rowcount == 1

    def set_day_start_equity(self, day: str, equity: float) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT OR IGNORE INTO day_start VALUES (?,?)", (day, equity))

    def day_start_equity(self, day: str) -> float | None:
        row = self._db.execute("SELECT equity FROM day_start WHERE day=?", (day,)).fetchone()
        return row[0] if row else None

    def trades_since(self, since_ts: float) -> int:
        return self._db.execute(
            "SELECT COUNT(*) FROM orders WHERE ts>=? AND status IN ('submitted','filled','dry_run')",
            (since_ts,),
        ).fetchone()[0]

    def last_trade_ts(self, symbol: str) -> float | None:
        row = self._db.execute(
            "SELECT MAX(ts) FROM orders WHERE symbol=? AND status IN ('submitted','filled','dry_run')",
            (symbol,),
        ).fetchone()
        return row[0]

    def realized_pnl_since(self, since_ts: float) -> float:
        return self._db.execute(
            "SELECT COALESCE(SUM(realized),0) FROM pnl WHERE ts>=?", (since_ts,)
        ).fetchone()[0]
