import time

import pytest
from promptfuse.cache import MemoryCache
from promptfuse.errors import InvalidPromptRequest, PromptNotFound, PromptStoreError
from promptfuse.registry import Registry
from promptfuse.stores.memory import MemoryStore


class _FlakyRegistry:
    def __init__(self, registry: Registry) -> None:
        self.registry = registry
        self.fail = False

    def get_prompt(self, *args, **kwargs):
        if self.fail:
            raise PromptStoreError("down")
        return self.registry.get_prompt(*args, **kwargs)


def test_fresh_cache_hides_a_label_move_until_ttl() -> None:
    clock = {"now": 0.0}
    registry = Registry(MemoryStore())
    registry.create_prompt(name="movie-critic", type="text", prompt="v1", labels=["production"])
    cache = MemoryCache(registry, ttl_seconds=10, clock=lambda: clock["now"])
    assert cache.get_prompt("movie-critic").prompt == "v1"
    registry.create_prompt(name="movie-critic", type="text", prompt="v2", labels=["production"])
    assert cache.get_prompt("movie-critic").prompt == "v1"
    assert cache.get_prompt("movie-critic", cache_ttl_seconds=0).prompt == "v2"
    clock["now"] = 11
    assert cache.get_prompt("movie-critic").prompt == "v1"
    deadline = time.time() + 2
    while time.time() < deadline:
        if cache.get_prompt("movie-critic").prompt == "v2":
            break
        time.sleep(0.01)
    else:
        pytest.fail("stale prompt was not refreshed")


def test_invalidate_labels_shows_a_write_immediately() -> None:
    registry = Registry(MemoryStore())
    registry.create_prompt(name="movie-critic", type="text", prompt="v1", labels=["production"])
    cache = MemoryCache(registry, ttl_seconds=60)
    assert cache.get_prompt("movie-critic").prompt == "v1"
    registry.create_prompt(name="movie-critic", type="text", prompt="v2", labels=["production"])
    cache.invalidate_labels("movie-critic")
    assert cache.get_prompt("movie-critic").prompt == "v2"


def test_version_pin_is_a_separate_cache_entry() -> None:
    clock = {"now": 0.0}
    registry = Registry(MemoryStore())
    registry.create_prompt(name="movie-critic", type="text", prompt="v1", labels=["production"])
    cache = MemoryCache(registry, ttl_seconds=10, clock=lambda: clock["now"])
    assert cache.get_prompt("movie-critic", version=1).prompt == "v1"
    cache.invalidate_labels("movie-critic")
    clock["now"] = 11
    assert cache.get_prompt("movie-critic", version=1).prompt == "v1"


def test_fallback_is_used_only_when_the_cache_cannot_answer() -> None:
    registry = Registry(MemoryStore())
    registry.create_prompt(name="movie-critic", type="text", prompt="v1", labels=["production"])
    flaky = _FlakyRegistry(registry)
    cache = MemoryCache(flaky, ttl_seconds=10)
    assert cache.get_prompt("movie-critic", fallback="fallback").prompt == "v1"
    flaky.fail = True
    clock_cache = MemoryCache(flaky, ttl_seconds=10)
    missing = clock_cache.get_prompt("movie-critic", fallback="Do you like {{movie}}?")
    assert missing.is_fallback is True
    assert missing.version == 0
    assert missing.compile(movie="Dune 2") == "Do you like Dune 2?"
    with pytest.raises(PromptStoreError):
        clock_cache.get_prompt("movie-critic")
    healthy = MemoryCache(registry, ttl_seconds=10)
    with pytest.raises(PromptNotFound):
        healthy.get_prompt("missing")
    fallback = healthy.get_prompt("missing", fallback="fallback text")
    assert fallback.is_fallback is True
    assert fallback.prompt == "fallback text"


def test_stale_cache_ignores_fallback_when_refresh_fails() -> None:
    clock = {"now": 0.0}
    registry = Registry(MemoryStore())
    registry.create_prompt(name="movie-critic", type="text", prompt="v1", labels=["production"])
    flaky = _FlakyRegistry(registry)
    cache = MemoryCache(flaky, ttl_seconds=10, clock=lambda: clock["now"])
    assert cache.get_prompt("movie-critic").prompt == "v1"
    flaky.fail = True
    clock["now"] = 11
    stale = cache.get_prompt("movie-critic", fallback="fallback")
    assert stale.prompt == "v1"
    assert stale.is_fallback is False


def test_label_and_version_together_are_rejected() -> None:
    cache = MemoryCache(Registry(MemoryStore()), ttl_seconds=10)
    with pytest.raises(InvalidPromptRequest):
        cache.get_prompt("movie-critic", label="production", version=1, fallback="x")
