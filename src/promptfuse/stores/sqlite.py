"""SQLite prompt store. Each thread opens its own connection."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from promptfuse.errors import InvalidPromptRequest, PromptStoreError
from promptfuse.models import normalize_prompt
from promptfuse.stores.protocol import StoredVersion

_SCHEMA = """
CREATE TABLE IF NOT EXISTS prompt_version (
    name TEXT NOT NULL,
    version INTEGER NOT NULL,
    type TEXT NOT NULL,
    prompt TEXT NOT NULL,
    config TEXT NOT NULL,
    tags TEXT NOT NULL,
    commit_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (name, version)
);

CREATE TABLE IF NOT EXISTS prompt_label (
    name TEXT NOT NULL,
    label TEXT NOT NULL,
    version INTEGER NOT NULL,
    PRIMARY KEY (name, label),
    FOREIGN KEY (name, version) REFERENCES prompt_version (name, version)
);
"""


class SqliteStore:
    """Versions are insert-only. Labels are the only mutable rows."""

    def __init__(self, path: Path | str) -> None:
        self._path = str(path)
        self._local = threading.local()

    def get_version(self, name: str, version: int) -> StoredVersion | None:
        row = self._query_one(
            """
            SELECT name, version, type, prompt, config, tags, commit_message, created_at, updated_at
            FROM prompt_version
            WHERE name = ? AND version = ?
            """,
            (name, version),
        )
        if row is None:
            return None
        return _row_to_version(row)

    def get_label(self, name: str, label: str) -> int | None:
        row = self._query_one(
            "SELECT version FROM prompt_label WHERE name = ? AND label = ?",
            (name, label),
        )
        if row is None:
            return None
        return int(row["version"])

    def highest_version(self, name: str) -> int | None:
        row = self._query_one(
            "SELECT MAX(version) AS version FROM prompt_version WHERE name = ?",
            (name,),
        )
        if row is None or row["version"] is None:
            return None
        return int(row["version"])

    def list_versions(self, name: str) -> list[int]:
        rows = self._query_all(
            "SELECT version FROM prompt_version WHERE name = ? ORDER BY version",
            (name,),
        )
        return [int(row["version"]) for row in rows]

    def list_names(self) -> list[str]:
        rows = self._query_all("SELECT DISTINCT name FROM prompt_version ORDER BY name", ())
        return [str(row["name"]) for row in rows]

    def labels_for_version(self, name: str, version: int) -> list[str]:
        rows = self._query_all(
            "SELECT label FROM prompt_label WHERE name = ? AND version = ? ORDER BY label",
            (name, version),
        )
        return [str(row["label"]) for row in rows]

    def label_assignments(self) -> list[tuple[str, str, int]]:
        rows = self._query_all(
            """
            SELECT name, label, version
            FROM prompt_label
            WHERE label != 'latest'
            ORDER BY name, label
            """,
            (),
        )
        return [(str(row["name"]), str(row["label"]), int(row["version"])) for row in rows]

    def insert_version(self, record: StoredVersion) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO prompt_version (
                        name, version, type, prompt, config, tags,
                        commit_message, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.name,
                        record.version,
                        record.type,
                        json.dumps(record.prompt, ensure_ascii=False),
                        json.dumps(record.config, ensure_ascii=False),
                        json.dumps(list(record.tags), ensure_ascii=False),
                        record.commit_message,
                        record.created_at,
                        record.updated_at,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise InvalidPromptRequest(
                f"prompt version already exists: {record.name}@{record.version}"
            ) from exc

    def set_label(self, name: str, label: str, version: int) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO prompt_label (name, label, version) VALUES (?, ?, ?)
                    ON CONFLICT(name, label) DO UPDATE SET version = excluded.version
                    """,
                    (name, label, version),
                )
        except sqlite3.IntegrityError as exc:
            raise InvalidPromptRequest(f"prompt version not found: {name}@{version}") from exc

    def clear_label(self, name: str, label: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM prompt_label WHERE name = ? AND label = ?",
                (name, label),
            )

    def _connect(self) -> sqlite3.Connection:
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            return connection
        try:
            connection = sqlite3.connect(self._path)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript(_SCHEMA)
        except sqlite3.Error as exc:
            raise PromptStoreError(f"could not open prompt database: {self._path}") from exc
        self._local.connection = connection
        return connection

    def _query_one(self, sql: str, params: tuple[Any, ...]) -> sqlite3.Row | None:
        try:
            return self._connect().execute(sql, params).fetchone()
        except sqlite3.Error as exc:
            raise PromptStoreError("prompt database query failed") from exc

    def _query_all(self, sql: str, params: tuple[Any, ...]) -> list[sqlite3.Row]:
        try:
            return list(self._connect().execute(sql, params).fetchall())
        except sqlite3.Error as exc:
            raise PromptStoreError("prompt database query failed") from exc


def _row_to_version(row: sqlite3.Row) -> StoredVersion:
    prompt_type = str(row["type"])
    prompt = normalize_prompt(prompt_type, json.loads(row["prompt"]))
    config = json.loads(row["config"])
    tags = json.loads(row["tags"])
    if not isinstance(config, dict) or not isinstance(tags, list):
        raise InvalidPromptRequest(f"stored prompt is invalid: {row['name']}@{row['version']}")
    return StoredVersion(
        name=str(row["name"]),
        version=int(row["version"]),
        type=prompt_type,
        prompt=prompt,
        config=config,
        tags=tuple(str(tag) for tag in tags),
        commit_message=row["commit_message"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )
