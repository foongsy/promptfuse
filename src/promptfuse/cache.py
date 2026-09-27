"""In-memory prompt cache with stale-while-revalidate refresh."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from promptfuse.chain import load_prompt
from promptfuse.errors import InvalidPromptRequest, PromptNotFound, PromptStoreError
from promptfuse.models import PromptClient, clone_client, fallback_client
from promptfuse.registry import Registry
from promptfuse.snapshot import Snapshot

CacheKey = tuple[str, str, str | int]


@dataclass
class _Entry:
    client: PromptClient
    expires_at: float
    ttl: float
    prompt_type: str
    version: int | None
    label: str | None


class MemoryCache:
    """Cache resolved prompt clients in front of a registry."""

    def __init__(
        self,
        registry: Registry,
        *,
        ttl_seconds: float = 60,
        clock: Callable[[], float] | None = None,
        seed: Registry | None = None,
        snapshot: Snapshot | None = None,
    ) -> None:
        self._registry = registry
        self._seed = seed
        self._snapshot = snapshot
        self._ttl = ttl_seconds
        self._clock = clock if clock is not None else time.monotonic
        self._entries: dict[CacheKey, _Entry] = {}
        self._inflight: set[CacheKey] = set()
        self._lock = threading.Lock()

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
        if version is not None and label is not None:
            raise InvalidPromptRequest("label and version are mutually exclusive")
        ttl = self._ttl if cache_ttl_seconds is None else cache_ttl_seconds
        if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or ttl < 0:
            raise InvalidPromptRequest(f"invalid cache ttl: {ttl!r}")
        key = _key(name, version, label)
        if ttl == 0:
            return self._load(key, name, version, label, type, fallback, remember=False, ttl=0)
        now = self._clock()
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry.expires_at > now and entry.prompt_type == type:
                return clone_client(entry.client)
            stale = entry if entry is not None and entry.prompt_type == type else None
        if stale is not None:
            self._schedule(key, stale)
            return clone_client(stale.client)
        return self._load(key, name, version, label, type, fallback, remember=True, ttl=ttl)

    def invalidate_labels(self, name: str) -> None:
        with self._lock:
            for key in [key for key in self._entries if key[0] == name and key[1] == "label"]:
                del self._entries[key]
        if self._snapshot is not None:
            self._snapshot.drop_labels(name)

    def _load(
        self,
        key: CacheKey,
        name: str,
        version: int | None,
        label: str | None,
        prompt_type: str,
        fallback: str | list[Any] | None,
        *,
        remember: bool,
        ttl: float,
    ) -> PromptClient:
        try:
            loaded = load_prompt(
                self._registry,
                name=name,
                version=version,
                label=label,
                prompt_type=prompt_type,
                snapshot=self._snapshot,
                key=key,
                seed=self._seed,
                allow_snapshot=True,
            )
        except PromptNotFound:
            if fallback is not None:
                return fallback_client(name, fallback)
            raise
        except PromptStoreError:
            if fallback is not None:
                return fallback_client(name, fallback)
            raise
        if loaded.source == "snapshot":
            self._remember(
                key,
                loaded.client,
                expires_at=self._clock(),
                ttl=self._ttl,
                prompt_type=prompt_type,
                version=version,
                label=label,
            )
            return clone_client(loaded.client)
        self._remember_success(key, loaded.client, prompt_type, version, label, remember, ttl)
        return clone_client(loaded.client)

    def _remember_success(
        self,
        key: CacheKey,
        client: PromptClient,
        prompt_type: str,
        version: int | None,
        label: str | None,
        remember: bool,
        ttl: float,
    ) -> None:
        if remember:
            self._remember(
                key,
                client,
                expires_at=self._clock() + ttl,
                ttl=ttl,
                prompt_type=prompt_type,
                version=version,
                label=label,
            )
        if self._snapshot is not None:
            self._snapshot.put(key, client)

    def _remember(
        self,
        key: CacheKey,
        client: PromptClient,
        *,
        expires_at: float,
        ttl: float,
        prompt_type: str,
        version: int | None,
        label: str | None,
    ) -> None:
        with self._lock:
            self._entries[key] = _Entry(
                client=clone_client(client),
                expires_at=expires_at,
                ttl=ttl,
                prompt_type=prompt_type,
                version=version,
                label=label,
            )

    def _schedule(self, key: CacheKey, entry: _Entry) -> None:
        with self._lock:
            if key in self._inflight:
                return
            self._inflight.add(key)
        thread = threading.Thread(target=self._refresh, args=(key, entry), daemon=True)
        thread.start()

    def _refresh(self, key: CacheKey, entry: _Entry) -> None:
        try:
            try:
                loaded = load_prompt(
                    self._registry,
                    name=key[0],
                    version=entry.version,
                    label=entry.label,
                    prompt_type=entry.prompt_type,
                    snapshot=self._snapshot,
                    key=key,
                    seed=self._seed,
                    allow_snapshot=False,
                )
            except (PromptNotFound, PromptStoreError):
                return
            self._remember_success(
                key,
                loaded.client,
                entry.prompt_type,
                entry.version,
                entry.label,
                True,
                entry.ttl,
            )
        finally:
            with self._lock:
                self._inflight.discard(key)


def _key(name: str, version: int | None, label: str | None) -> CacheKey:
    if version is not None:
        return (name, "version", version)
    return (name, "label", "production" if label is None else label)
