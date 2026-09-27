"""Row storage for prompt versions and labels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class StoredVersion:
    """One immutable prompt version."""

    name: str
    version: int
    type: str
    prompt: str | list[dict[str, Any]]
    config: dict[str, Any]
    tags: tuple[str, ...]
    commit_message: str | None
    created_at: str
    updated_at: str


class PromptStore(Protocol):
    """Persistence for versions and labels.

    Implementations store rows. They do not apply label-resolution rules.
    ``latest`` may be stored as a label or derived by the implementation,
    but ``get_label(name, "latest")`` and ``labels_for_version`` must agree
    with the highest version.
    """

    def get_version(self, name: str, version: int) -> StoredVersion | None:
        """Return one version, or ``None`` when it is absent."""

    def get_label(self, name: str, label: str) -> int | None:
        """Return the version a label points at, or ``None``."""

    def highest_version(self, name: str) -> int | None:
        """Return the largest version number for ``name``, or ``None``."""

    def list_versions(self, name: str) -> list[int]:
        """Return version numbers for ``name`` in ascending order."""

    def list_names(self) -> list[str]:
        """Return prompt names that have at least one version."""

    def labels_for_version(self, name: str, version: int) -> list[str]:
        """Return labels pointing at this version, including ``latest``."""

    def label_assignments(self) -> list[tuple[str, str, int]]:
        """Return ``(name, label, version)`` rows, excluding ``latest``."""

    def insert_version(self, record: StoredVersion) -> None:
        """Insert a version. Existing versions are never updated."""

    def set_label(self, name: str, label: str, version: int) -> None:
        """Point ``label`` at ``version``, moving it off any other version."""

    def clear_label(self, name: str, label: str) -> None:
        """Remove ``label`` from ``name`` when it is present."""
