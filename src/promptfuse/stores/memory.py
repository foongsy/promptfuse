"""In-memory store used by tests and as the reference for the store contract."""

from __future__ import annotations

from promptfuse.errors import InvalidPromptRequest
from promptfuse.stores.protocol import StoredVersion


class MemoryStore:
    """Process-local versions and labels."""

    def __init__(self) -> None:
        self._versions: dict[tuple[str, int], StoredVersion] = {}
        self._labels: dict[tuple[str, str], int] = {}

    def get_version(self, name: str, version: int) -> StoredVersion | None:
        return self._versions.get((name, version))

    def get_label(self, name: str, label: str) -> int | None:
        if label == "latest":
            return self.highest_version(name)
        return self._labels.get((name, label))

    def highest_version(self, name: str) -> int | None:
        versions = self.list_versions(name)
        if not versions:
            return None
        return versions[-1]

    def list_versions(self, name: str) -> list[int]:
        return sorted(version for stored_name, version in self._versions if stored_name == name)

    def list_names(self) -> list[str]:
        return sorted({name for name, _version in self._versions})

    def labels_for_version(self, name: str, version: int) -> list[str]:
        labels = [
            label
            for (stored_name, label), pointed in self._labels.items()
            if stored_name == name and pointed == version and label != "latest"
        ]
        if self.highest_version(name) == version:
            labels.append("latest")
        return sorted(labels)

    def label_assignments(self) -> list[tuple[str, str, int]]:
        return sorted(
            (name, label, version)
            for (name, label), version in self._labels.items()
            if label != "latest"
        )

    def insert_version(self, record: StoredVersion) -> None:
        key = (record.name, record.version)
        if key in self._versions:
            raise InvalidPromptRequest(
                f"prompt version already exists: {record.name}@{record.version}"
            )
        self._versions[key] = record

    def set_label(self, name: str, label: str, version: int) -> None:
        if label == "latest":
            return
        if (name, version) not in self._versions:
            raise InvalidPromptRequest(f"prompt version not found: {name}@{version}")
        self._labels[(name, label)] = version

    def clear_label(self, name: str, label: str) -> None:
        if label == "latest":
            return
        self._labels.pop((name, label), None)
