"""Langfuse label and version rules over a prompt store."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from typing import Any

from promptfuse.errors import InvalidPromptRequest, PromptNotFound
from promptfuse.models import PromptClient, make_client, normalize_prompt
from promptfuse.stores.protocol import PromptStore, StoredVersion


class Registry:
    """Resolve, create, and relabel prompts."""

    def __init__(self, store: PromptStore) -> None:
        self._store = store

    def get_prompt(
        self,
        name: str,
        *,
        version: int | None = None,
        label: str | None = None,
        type: str = "text",
    ) -> PromptClient:
        validate_name(name)
        _reject_both(version, label)
        if version is None:
            selected = label if label is not None else "production"
            _validate_label(selected)
            resolved = self._store.get_label(name, selected)
            if resolved is None:
                raise PromptNotFound(f"prompt label not found: {name!r} {selected!r}")
            version = resolved
        else:
            _validate_version(version)
        record = self._store.get_version(name, version)
        if record is None:
            raise PromptNotFound(f"prompt version not found: {name}@{version}")
        if record.type != type:
            raise PromptNotFound(f"prompt type mismatch for {name}: stored {record.type!r}")
        return _client_from(record, self._store.labels_for_version(name, version))

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
        validate_name(name)
        if type not in ("text", "chat"):
            raise InvalidPromptRequest(f"unknown prompt type: {type!r}")
        assigned = list(labels or [])
        if "latest" in assigned:
            raise InvalidPromptRequest("latest is maintained by the registry")
        for label in assigned:
            _validate_label(label)
        stored_prompt = normalize_prompt(type, prompt)
        stored_config = _json_object(config)
        stored_tags = _string_tuple(tags)
        for existing in self._store.list_versions(name):
            current = self._store.get_version(name, existing)
            if current is not None and current.type != type:
                raise InvalidPromptRequest(
                    f"prompt type for {name} is {current.type!r} and cannot change"
                )
        highest = self._store.highest_version(name)
        version = 1 if highest is None else highest + 1
        now = _now()
        self._store.insert_version(
            StoredVersion(
                name=name,
                version=version,
                type=type,
                prompt=stored_prompt,
                config=stored_config,
                tags=stored_tags,
                commit_message=commit_message,
                created_at=now,
                updated_at=now,
            )
        )
        for label in assigned:
            self._store.set_label(name, label, version)
        self._store.set_label(name, "latest", version)
        return self.get_prompt(name, version=version, type=type)

    def update_prompt(self, name: str, *, version: int, new_labels: list[str]) -> PromptClient:
        validate_name(name)
        _validate_version(version)
        if "latest" in new_labels:
            raise InvalidPromptRequest("latest is maintained by the registry")
        for label in new_labels:
            _validate_label(label)
        record = self._store.get_version(name, version)
        if record is None:
            raise PromptNotFound(f"prompt version not found: {name}@{version}")
        current = set(self._store.labels_for_version(name, version)) - {"latest"}
        desired = set(new_labels)
        for label in current - desired:
            self._store.clear_label(name, label)
        for label in desired:
            self._store.set_label(name, label, version)
        return self.get_prompt(name, version=version, type=record.type)

    def import_records(self, source: PromptStore) -> None:
        """Copy versions from ``source`` and replace labels named in its index."""

        for name in source.list_names():
            for version in source.list_versions(name):
                incoming = source.get_version(name, version)
                if incoming is None:
                    continue
                existing = self._store.get_version(name, version)
                if existing is None:
                    self._store.insert_version(incoming)
                elif not _same_body(existing, incoming):
                    raise InvalidPromptRequest(
                        f"prompt version changed: {name}@{version}"
                    )
        assignments = source.label_assignments()
        names = sorted({name for name, _label, _version in assignments})
        for name in names:
            pointed = {
                label
                for stored_name, label, _version in self._store.label_assignments()
                if stored_name == name
            }
            for label in pointed:
                self._store.clear_label(name, label)
        for name, label, version in assignments:
            self._store.set_label(name, label, version)
        for name in self._store.list_names():
            highest = self._store.highest_version(name)
            if highest is not None:
                self._store.set_label(name, "latest", highest)


def validate_name(name: str) -> None:
    if not isinstance(name, str) or not name or name.startswith("/") or "\\" in name:
        raise InvalidPromptRequest(f"invalid prompt name: {name!r}")
    parts = name.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise InvalidPromptRequest(f"invalid prompt name: {name!r}")


def _reject_both(version: int | None, label: str | None) -> None:
    if version is not None and label is not None:
        raise InvalidPromptRequest("label and version are mutually exclusive")


def _validate_version(version: int) -> None:
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise InvalidPromptRequest(f"invalid prompt version: {version!r}")


def _validate_label(label: str) -> None:
    if not isinstance(label, str) or not label:
        raise InvalidPromptRequest(f"invalid prompt label: {label!r}")


def _json_object(config: dict[str, Any] | None) -> dict[str, Any]:
    if config is None:
        return {}
    if not isinstance(config, dict):
        raise InvalidPromptRequest("config must be a JSON object")
    try:
        encoded = json.dumps(config)
    except TypeError as exc:
        raise InvalidPromptRequest("config must be JSON serializable") from exc
    loaded = json.loads(encoded)
    if not isinstance(loaded, dict):
        raise InvalidPromptRequest("config must be a JSON object")
    return loaded


def _string_tuple(tags: list[str] | None) -> tuple[str, ...]:
    if tags is None:
        return ()
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise InvalidPromptRequest("tags must be a list of strings")
    return tuple(tags)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _client_from(record: StoredVersion, labels: list[str]) -> PromptClient:
    prompt = copy.deepcopy(record.prompt)
    return make_client(
        name=record.name,
        version=record.version,
        prompt_type=record.type,
        prompt=prompt,
        config=record.config,
        labels=labels,
        tags=list(record.tags),
        commit_message=record.commit_message,
    )


def _same_body(existing: StoredVersion, incoming: StoredVersion) -> bool:
    return (
        existing.type == incoming.type
        and existing.prompt == incoming.prompt
        and existing.config == incoming.config
        and existing.tags == incoming.tags
        and existing.commit_message == incoming.commit_message
    )
