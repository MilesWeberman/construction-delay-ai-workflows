"""Event log in SQLite. Every step of the workflow reads and writes events."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple

from pydantic import BaseModel

EMAIL_RECEIVED = "EmailReceived"
EMAIL_IGNORED = "EmailIgnored"
MATERIAL_ORDERED = "MaterialOrdered"
DELIVERY_DATE_CHANGED = "DeliveryDateChanged"
DELIVERY_CONFIRMED = "DeliveryConfirmed"
NEEDS_REVIEW = "NeedsReview"
LINK_SUGGESTED = "LinkSuggested"
MATERIAL_LINKED = "MaterialLinked"
DELAY_ASSESSED = "DelayAssessed"

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    caused_by INTEGER REFERENCES events(id),
    dedupe_key TEXT UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | done | failed
    error TEXT
)
"""


class Event(BaseModel):
    id: int
    type: str
    payload: dict[str, Any]
    created_at: datetime
    caused_by: int | None
    status: str
    error: str | None


class Emit(NamedTuple):
    """A new event for a handler to emit."""

    type: str
    payload: dict[str, Any]


class EventStore:
    def __init__(self, path: Path | str = ":memory:"):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(SCHEMA)

    def append(
        self,
        type: str,
        payload: dict[str, Any],
        caused_by: int | None = None,
        dedupe_key: str | None = None,
    ) -> Event | None:
        """Add an event. Returns None if one with the same dedupe_key already exists."""
        with self.conn:
            event_id = self._insert(type, payload, caused_by, dedupe_key)
        return self.get(event_id) if event_id else None

    def complete(self, event_id: int, emitted: list[Emit]) -> None:
        """Mark an event done and add the events it caused, in one transaction."""
        with self.conn:
            for emit in emitted:
                self._insert(emit.type, emit.payload, caused_by=event_id, dedupe_key=None)
            self.conn.execute("UPDATE events SET status = 'done' WHERE id = ?", (event_id,))

    def fail(self, event_id: int, error: str) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE events SET status = 'failed', error = ? WHERE id = ?", (error, event_id)
            )

    def retry_failed(self) -> int:
        """Put failed events back to pending. Returns how many."""
        with self.conn:
            cur = self.conn.execute(
                "UPDATE events SET status = 'pending', error = NULL WHERE status = 'failed'"
            )
        return cur.rowcount

    def get(self, event_id: int) -> Event:
        row = self.conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        return _to_event(row)

    def pending(self) -> list[Event]:
        return self._select("WHERE status = 'pending'")

    def all(self) -> list[Event]:
        return self._select("")

    def _insert(
        self,
        type: str,
        payload: dict[str, Any],
        caused_by: int | None,
        dedupe_key: str | None,
    ) -> int | None:
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO events (type, payload, created_at, caused_by, dedupe_key)"
            " VALUES (?, ?, ?, ?, ?)",
            (type, json.dumps(payload), datetime.now(UTC).isoformat(), caused_by, dedupe_key),
        )
        return cur.lastrowid if cur.rowcount else None

    def _select(self, where: str) -> list[Event]:
        rows = self.conn.execute(f"SELECT * FROM events {where} ORDER BY id").fetchall()
        return [_to_event(row) for row in rows]


def _to_event(row: sqlite3.Row) -> Event:
    return Event(**{**dict(row), "payload": json.loads(row["payload"])})
