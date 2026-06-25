from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from security import TokenCipher


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def initialise(path: Path) -> None:
    with connect(path) as db:
        db.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS participants (
                athlete_id INTEGER PRIMARY KEY,
                display_name TEXT NOT NULL,
                firstname TEXT,
                lastname TEXT,
                access_token TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                scope TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reports (
                report_date TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )


def upsert_participant(path: Path, cipher: TokenCipher, *, athlete_id: int,
                       display_name: str, firstname: str, lastname: str,
                       access_token: str, refresh_token: str, expires_at: int,
                       scope: str = "") -> None:
    now = utc_now_iso()
    with connect(path) as db:
        db.execute(
            """
            INSERT INTO participants (
                athlete_id, display_name, firstname, lastname,
                access_token, refresh_token, expires_at, scope,
                active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(athlete_id) DO UPDATE SET
                display_name = excluded.display_name,
                firstname = excluded.firstname,
                lastname = excluded.lastname,
                access_token = excluded.access_token,
                refresh_token = excluded.refresh_token,
                expires_at = excluded.expires_at,
                scope = excluded.scope,
                active = 1,
                updated_at = excluded.updated_at
            """,
            (athlete_id, display_name, firstname, lastname,
             cipher.encrypt(access_token), cipher.encrypt(refresh_token),
             expires_at, scope, now, now),
        )


def list_active_participants(path: Path, cipher: TokenCipher) -> list[dict]:
    with connect(path) as db:
        rows = db.execute(
            "SELECT * FROM participants WHERE active = 1 "
            "ORDER BY display_name COLLATE NOCASE, athlete_id"
        ).fetchall()
    participants = []
    for row in rows:
        item = dict(row)
        item["access_token"] = cipher.decrypt(item["access_token"])
        item["refresh_token"] = cipher.decrypt(item["refresh_token"])
        participants.append(item)
    return participants


def update_tokens(path: Path, cipher: TokenCipher, athlete_id: int, *,
                  access_token: str, refresh_token: str, expires_at: int) -> None:
    with connect(path) as db:
        db.execute(
            """
            UPDATE participants
            SET access_token = ?, refresh_token = ?, expires_at = ?, updated_at = ?
            WHERE athlete_id = ?
            """,
            (cipher.encrypt(access_token), cipher.encrypt(refresh_token),
             expires_at, utc_now_iso(), athlete_id),
        )


def save_report(path: Path, report_date: str, title: str, content: str) -> None:
    with connect(path) as db:
        db.execute(
            """
            INSERT INTO reports (report_date, title, content, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(report_date) DO UPDATE SET
                title = excluded.title,
                content = excluded.content,
                created_at = excluded.created_at
            """,
            (report_date, title, content, utc_now_iso()),
        )


def get_latest_report(path: Path) -> dict | None:
    with connect(path) as db:
        row = db.execute(
            "SELECT report_date, title, content, created_at FROM reports "
            "ORDER BY report_date DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def count_participants(path: Path) -> int:
    with connect(path) as db:
        row = db.execute(
            "SELECT COUNT(*) AS total FROM participants WHERE active = 1"
        ).fetchone()
    return int(row["total"])
