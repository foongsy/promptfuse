"""Read a primary registry, then the disk snapshot, then a YAML seed."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from promptfuse.errors import PromptNotFound, PromptStoreError
from promptfuse.models import PromptClient
from promptfuse.registry import Registry
from promptfuse.snapshot import Snapshot

Source = Literal["primary", "snapshot", "seed"]


@dataclass(frozen=True)
class LoadedPrompt:
    client: PromptClient
    source: Source


def load_prompt(
    registry: Registry,
    *,
    name: str,
    version: int | None,
    label: str | None,
    prompt_type: str,
    snapshot: Snapshot | None,
    key: tuple[str, str, str | int],
    seed: Registry | None,
    allow_snapshot: bool,
) -> LoadedPrompt:
    """Resolve a prompt from the primary store.

    ``PromptNotFound`` from a healthy primary store propagates. ``PromptStoreError``
    tries the snapshot, then ``seed``, and then propagates.
    """

    try:
        client = registry.get_prompt(name, version=version, label=label, type=prompt_type)
    except PromptStoreError as exc:
        if allow_snapshot and snapshot is not None:
            try:
                snapped = snapshot.get(key)
            except PromptStoreError:
                snapped = None
            if snapped is not None and snapped.type == prompt_type:
                return LoadedPrompt(snapped, "snapshot")
        if seed is not None:
            try:
                seeded = seed.get_prompt(name, version=version, label=label, type=prompt_type)
            except (PromptNotFound, PromptStoreError):
                seeded = None
            if seeded is not None:
                return LoadedPrompt(seeded, "seed")
        raise exc
    return LoadedPrompt(client, "primary")
