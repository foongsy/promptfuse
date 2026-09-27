"""Disk cache of prompt clients returned by a successful store read."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from promptfuse.errors import PromptStoreError
from promptfuse.models import PromptClient, make_client


class Snapshot:
    """JSON file of resolved prompt clients, keyed like the memory cache."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    def get(self, key: tuple[str, str, str | int]) -> PromptClient | None:
        with self._lock:
            for entry in self._load():
                if _entry_key(entry) == key:
                    return _client_from_entry(entry)
            return None

    def put(self, key: tuple[str, str, str | int], client: PromptClient) -> None:
        if client.is_fallback:
            return
        with self._lock:
            entries = [entry for entry in self._load() if _entry_key(entry) != key]
            entries.append(_entry_from_client(key, client))
            self._write(entries)

    def drop_labels(self, name: str) -> None:
        with self._lock:
            entries = [
                entry
                for entry in self._load()
                if not (entry.get("name") == name and entry.get("kind") == "label")
            ]
            self._write(entries)

    def _load(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        try:
            loaded = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PromptStoreError(f"could not read snapshot: {self._path}") from exc
        if not isinstance(loaded, dict) or not isinstance(loaded.get("entries"), list):
            raise PromptStoreError(f"snapshot is invalid: {self._path}")
        return loaded["entries"]

    def _write(self, entries: list[dict[str, Any]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(self._path.suffix + ".tmp")
        try:
            temporary.write_text(
                json.dumps({"entries": entries}, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(temporary, self._path)
        except OSError as exc:
            raise PromptStoreError(f"could not write snapshot: {self._path}") from exc


def _entry_key(entry: dict[str, Any]) -> tuple[str, str, str | int]:
    return (entry["name"], entry["kind"], entry["selector"])


def _entry_from_client(key: tuple[str, str, str | int], client: PromptClient) -> dict[str, Any]:
    name, kind, selector = key
    prompt = client.prompt
    return {
        "name": name,
        "kind": kind,
        "selector": selector,
        "client": {
            "name": client.name,
            "version": client.version,
            "type": client.type,
            "prompt": prompt,
            "config": client.config,
            "labels": list(client.labels),
            "tags": list(client.tags),
            "commit_message": client.commit_message,
        },
    }


def _client_from_entry(entry: dict[str, Any]) -> PromptClient:
    body = entry["client"]
    return make_client(
        name=body["name"],
        version=body["version"],
        prompt_type=body["type"],
        prompt=body["prompt"],
        config=body["config"],
        labels=body["labels"],
        tags=body["tags"],
        commit_message=body["commit_message"],
    )
