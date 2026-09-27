"""Public promptfuse client."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from promptfuse.cache import MemoryCache
from promptfuse.errors import InvalidPromptRequest
from promptfuse.models import PromptClient
from promptfuse.registry import Registry
from promptfuse.snapshot import Snapshot
from promptfuse.stores.sqlite import SqliteStore
from promptfuse.stores.yaml import YamlStore


class Promptfuse:
    """Local prompt registry with a Langfuse-compatible prompt API."""

    def __init__(
        self,
        *,
        yaml_dir: Path | str | None = None,
        sqlite_path: Path | str | None = None,
        snapshot_path: Path | str | None = None,
        cache_ttl_seconds: float = 60,
        import_yaml: bool = False,
    ) -> None:
        if yaml_dir is None and sqlite_path is None:
            raise InvalidPromptRequest("yaml_dir or sqlite_path is required")
        self._yaml = YamlStore(yaml_dir) if yaml_dir is not None else None
        self._sqlite = SqliteStore(sqlite_path) if sqlite_path is not None else None
        if self._sqlite is not None:
            primary = self._sqlite
            seed = Registry(self._yaml) if self._yaml is not None else None
        else:
            primary = self._yaml
            seed = None
        if primary is None:
            raise InvalidPromptRequest("yaml_dir or sqlite_path is required")
        self._registry = Registry(primary)
        snapshot = Snapshot(snapshot_path) if snapshot_path is not None else None
        self._cache = MemoryCache(
            self._registry,
            ttl_seconds=cache_ttl_seconds,
            seed=seed,
            snapshot=snapshot,
        )
        if import_yaml:
            self.import_yaml()

    def get_prompt(
        self,
        name: str,
        *,
        version: int | None = None,
        label: str | None = None,
        type: str = "text",
        cache_ttl_seconds: float | None = None,
        fallback: str | list[Any] | None = None,
    ) -> PromptClient:
        return self._cache.get_prompt(
            name,
            version=version,
            label=label,
            type=type,
            cache_ttl_seconds=cache_ttl_seconds,
            fallback=fallback,
        )

    def create_prompt(
        self,
        name: str,
        *,
        type: str,
        prompt: Any,
        labels: list[str] | None = None,
        config: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        commit_message: str | None = None,
    ) -> PromptClient:
        client = self._registry.create_prompt(
            name,
            type=type,
            prompt=prompt,
            labels=labels,
            config=config,
            tags=tags,
            commit_message=commit_message,
        )
        self._cache.invalidate_labels(name)
        return client

    def update_prompt(self, name: str, *, version: int, new_labels: list[str]) -> PromptClient:
        client = self._registry.update_prompt(name, version=version, new_labels=new_labels)
        self._cache.invalidate_labels(name)
        return client

    def import_yaml(self) -> None:
        """Copy the YAML tree into the primary SQLite store."""

        if self._yaml is None or self._sqlite is None:
            raise InvalidPromptRequest("import_yaml requires yaml_dir and sqlite_path")
        self._registry.import_records(self._yaml)
        names = set(self._yaml.list_names())
        names.update(name for name, _label, _version in self._yaml.label_assignments())
        for name in names:
            self._cache.invalidate_labels(name)
