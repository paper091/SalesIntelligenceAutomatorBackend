"""Persistence layer. Only this module talks SQL; everything else goes
through the LeadRepository interface so a Postgres/Supabase implementation
can drop in later without touching pipeline or orchestrator code.
"""
from __future__ import annotations

import json
import os
import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from app.models.schemas import LeadResult


class LeadRepository(ABC):
    @abstractmethod
    def save(self, lead: LeadResult) -> None: ...

    @abstractmethod
    def get(self, lead_id: str) -> LeadResult | None: ...

    @abstractmethod
    def list(self) -> list[LeadResult]: ...

    @abstractmethod
    def update(self, lead: LeadResult) -> None: ...

    @abstractmethod
    def clear(self) -> None: ...


class SqliteLeadRepository(LeadRepository):
    """Single-table SQLite repository storing each LeadResult as JSON."""

    def __init__(self, db_path: str) -> None:
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        # check_same_thread=False because FastAPI's background tasks and the
        # request handlers may touch the connection from different threads.
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        # Each lead is stored as a JSON blob rather than a wide table -
        # the schema (LeadResult/SalesBrief) lives in Pydantic, not SQL,
        # so it can evolve without migrations.
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS lead_results (
                id TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def save(self, lead: LeadResult) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO lead_results (id, data, updated_at) VALUES (?, ?, ?)",
            (lead.id, lead.model_dump_json(), lead.updated_at.isoformat()),
        )
        self._conn.commit()

    def get(self, lead_id: str) -> LeadResult | None:
        row = self._conn.execute(
            "SELECT data FROM lead_results WHERE id = ?", (lead_id,)
        ).fetchone()
        if row is None:
            return None
        return LeadResult.model_validate(json.loads(row[0]))

    def list(self) -> list[LeadResult]:
        rows = self._conn.execute(
            "SELECT data FROM lead_results ORDER BY updated_at DESC"
        ).fetchall()
        return [LeadResult.model_validate(json.loads(row[0])) for row in rows]

    def update(self, lead: LeadResult) -> None:
        lead.updated_at = datetime.now(timezone.utc)
        self.save(lead)

    def clear(self) -> None:
        self._conn.execute("DELETE FROM lead_results")
        self._conn.commit()
