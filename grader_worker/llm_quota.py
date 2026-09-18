from __future__ import annotations

import sqlite3
import time
from pathlib import Path


class CapacityUnavailable(RuntimeError):
    pass


class QuotaLedger:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS reservations(id TEXT PRIMARY KEY,tokens INTEGER NOT NULL,state TEXT NOT NULL,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL)")
        self.db.commit()

    def reserve(self, reservation_id: str, tokens: int, daily_budget: int) -> None:
        now = int(time.time()); day_start = now - now % 86400
        self.db.execute("BEGIN IMMEDIATE")
        try:
            existing = self.db.execute(
                "SELECT tokens,state FROM reservations WHERE id=?", (reservation_id,),
            ).fetchone()
            if existing:
                if existing[1] in {"reserved", "consumed"}:
                    self.db.commit()
                    return
            used = self.db.execute("SELECT coalesce(sum(tokens),0) FROM reservations WHERE state IN ('reserved','consumed') AND created_at>=?", (day_start,)).fetchone()[0]
            if used + tokens > daily_budget:
                raise CapacityUnavailable("Недостаточно зарезервированного LLM budget")
            if existing:
                self.db.execute(
                    "UPDATE reservations SET tokens=?,state='reserved',created_at=?,updated_at=? WHERE id=?",
                    (tokens, now, now, reservation_id),
                )
            else:
                self.db.execute("INSERT INTO reservations(id,tokens,state,created_at,updated_at) VALUES(?,?,'reserved',?,?)", (reservation_id, tokens, now, now))
            self.db.commit()
        except BaseException:
            self.db.rollback(); raise

    def finish(self, reservation_id: str, consumed: bool) -> None:
        self.db.execute("UPDATE reservations SET state=?,updated_at=? WHERE id=? AND state='reserved'", ("consumed" if consumed else "released", int(time.time()), reservation_id))
        self.db.commit()
