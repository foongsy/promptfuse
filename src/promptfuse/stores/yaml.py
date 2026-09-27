"""YAML prompt tree. The directory path is the prompt name, and ``vN.yaml`` is the version."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

import yaml

from promptfuse.errors import InvalidPromptRequest, PromptStoreError
from promptfuse.models import normalize_prompt
from promptfuse.registry import validate_name
from promptfuse.stores.protocol import StoredVersion


class YamlStore:
    """Immutable version files plus a mutable label index."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._lock = threading.RLock()

    def get_version(self, name: str, version: int) -> StoredVersion | None:
        with self._lock:
            path = self._version_path(name, version)
            if not path.is_file():
                return None
            return self._read_version(name, version, path)

    def get_label(self, name: str, label: str) -> int | None:
        with self._lock:
            if label == "latest":
                return self.highest_version(name)
            labels = self._read_index().get(name, {})
            return labels.get(label)

    def highest_version(self, name: str) -> int | None:
        versions = self.list_versions(name)
        if not versions:
            return None
        return versions[-1]

    def list_versions(self, name: str) -> list[int]:
        with self._lock:
            directory = self._prompt_dir(name)
            if not directory.is_dir():
                return []
            versions: list[int] = []
            for entry in directory.iterdir():
                if entry.is_file():
                    parsed = _version_number(entry.name)
                    if parsed is not None:
                        versions.append(parsed)
            return sorted(versions)

    def list_names(self) -> list[str]:
        with self._lock:
            names: list[str] = []
            if not self._root.exists():
                return names
            root = self._root.resolve()
            for dirpath, _dirnames, filenames in os.walk(root):
                current = Path(dirpath).resolve()
                if current == root:
                    if any(_version_number(name) is not None for name in filenames):
                        raise InvalidPromptRequest("version files must live under a prompt name")
                    continue
                if any(_version_number(name) is not None for name in filenames):
                    names.append("/".join(current.relative_to(root).parts))
            return sorted(names)

    def labels_for_version(self, name: str, version: int) -> list[str]:
        with self._lock:
            labels = [
                label
                for label, pointed in self._read_index().get(name, {}).items()
                if pointed == version
            ]
            if self.highest_version(name) == version:
                labels.append("latest")
            return sorted(labels)

    def label_assignments(self) -> list[tuple[str, str, int]]:
        with self._lock:
            rows: list[tuple[str, str, int]] = []
            for name, labels in self._read_index().items():
                for label, version in labels.items():
                    rows.append((name, label, version))
            return sorted(rows)

    def insert_version(self, record: StoredVersion) -> None:
        with self._lock:
            path = self._version_path(record.name, record.version)
            if path.exists():
                raise InvalidPromptRequest(
                    f"prompt version already exists: {record.name}@{record.version}"
                )
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "name": record.name,
                "version": record.version,
                "type": record.type,
                "prompt": record.prompt,
                "config": record.config,
                "tags": list(record.tags),
                "commit_message": record.commit_message,
                "created_at": record.created_at,
                "updated_at": record.updated_at,
            }
            _atomic_write(path, yaml.safe_dump(payload, sort_keys=False, allow_unicode=True))

    def set_label(self, name: str, label: str, version: int) -> None:
        with self._lock:
            if label == "latest":
                return
            if self.get_version(name, version) is None:
                raise InvalidPromptRequest(f"prompt version not found: {name}@{version}")
            index = self._read_index()
            labels = dict(index.get(name, {}))
            labels[label] = version
            index[name] = labels
            self._write_index(index)

    def clear_label(self, name: str, label: str) -> None:
        with self._lock:
            if label == "latest":
                return
            index = self._read_index()
            labels = dict(index.get(name, {}))
            if label not in labels:
                return
            del labels[label]
            if labels:
                index[name] = labels
            else:
                index.pop(name, None)
            self._write_index(index)

    def _prompt_dir(self, name: str) -> Path:
        validate_name(name)
        root = self._root.resolve()
        path = root.joinpath(*name.split("/")).resolve()
        if not path.is_relative_to(root):
            raise InvalidPromptRequest(f"prompt path escapes the seed tree: {name}")
        return path

    def _version_path(self, name: str, version: int) -> Path:
        return self._prompt_dir(name) / f"v{version}.yaml"

    def _read_version(self, name: str, version: int, path: Path) -> StoredVersion:
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise PromptStoreError(f"could not read prompt file: {path}") from exc
        except yaml.YAMLError as exc:
            raise InvalidPromptRequest(f"prompt file is not valid YAML: {name}@{version}") from exc
        if not isinstance(loaded, dict):
            raise InvalidPromptRequest(f"prompt file is not a mapping: {name}@{version}")
        if loaded.get("name") != name or loaded.get("version") != version:
            raise InvalidPromptRequest(f"prompt file disagrees with its path: {name}@{version}")
        prompt_type = loaded.get("type")
        if prompt_type not in ("text", "chat"):
            raise InvalidPromptRequest(f"prompt type is missing: {name}@{version}")
        try:
            prompt = normalize_prompt(prompt_type, loaded.get("prompt"))
        except InvalidPromptRequest:
            raise
        config = loaded.get("config", {})
        if config is None:
            config = {}
        if not isinstance(config, dict):
            raise InvalidPromptRequest(f"prompt config is not a mapping: {name}@{version}")
        tags = loaded.get("tags", [])
        if tags is None:
            tags = []
        if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
            raise InvalidPromptRequest(f"prompt tags are invalid: {name}@{version}")
        commit_message = loaded.get("commit_message")
        if commit_message is not None and not isinstance(commit_message, str):
            raise InvalidPromptRequest(f"prompt commit_message is invalid: {name}@{version}")
        created_at = loaded.get("created_at") or ""
        updated_at = loaded.get("updated_at") or ""
        return StoredVersion(
            name=name,
            version=version,
            type=prompt_type,
            prompt=prompt,
            config=config,
            tags=tuple(tags),
            commit_message=commit_message,
            created_at=str(created_at),
            updated_at=str(updated_at),
        )

    def _read_index(self) -> dict[str, dict[str, int]]:
        path = self._root / "index.yaml"
        if not path.exists():
            return {}
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise PromptStoreError("could not read prompt index") from exc
        except yaml.YAMLError as exc:
            raise InvalidPromptRequest("prompt index is not valid YAML") from exc
        if loaded is None:
            return {}
        if not isinstance(loaded, dict):
            raise InvalidPromptRequest("prompt index is not a mapping")
        prompts = loaded.get("prompts", {})
        if prompts is None:
            prompts = {}
        if not isinstance(prompts, dict):
            raise InvalidPromptRequest("prompt index prompts is not a mapping")
        parsed: dict[str, dict[str, int]] = {}
        for name, labels in prompts.items():
            if not isinstance(name, str):
                raise InvalidPromptRequest("prompt index name is invalid")
            validate_name(name)
            if not isinstance(labels, dict):
                raise InvalidPromptRequest(f"prompt index entry is invalid: {name}")
            cleaned: dict[str, int] = {}
            for label, version in labels.items():
                if label == "latest":
                    raise InvalidPromptRequest("latest must not appear in index.yaml")
                if not isinstance(label, str) or not label:
                    raise InvalidPromptRequest(f"prompt index label is invalid: {name}")
                if isinstance(version, bool) or not isinstance(version, int) or version < 1:
                    raise InvalidPromptRequest(f"prompt index version is invalid: {name} {label}")
                cleaned[label] = version
            parsed[name] = cleaned
        return parsed

    def _write_index(self, index: dict[str, dict[str, int]]) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {"prompts": index}
        _atomic_write(
            self._root / "index.yaml",
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        )


def _version_number(filename: str) -> int | None:
    path = Path(filename)
    if path.suffix != ".yaml":
        return None
    stem = path.stem
    if len(stem) < 2 or not stem.startswith("v"):
        return None
    number = stem[1:]
    if not number.isdigit() or number.startswith("0"):
        return None
    value = int(number)
    if f"v{value}" != stem or value < 1:
        return None
    return value


def _atomic_write(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)
    except OSError as exc:
        raise PromptStoreError(f"could not write {path}") from exc
