from pathlib import Path

import pytest
from promptfuse.errors import InvalidPromptRequest
from promptfuse.registry import Registry
from promptfuse.stores.memory import MemoryStore
from promptfuse.stores.sqlite import SqliteStore
from promptfuse.stores.yaml import YamlStore


def _stores(tmp_path: Path):
    return [
        ("memory", MemoryStore()),
        ("yaml", YamlStore(tmp_path / "prompts")),
        ("sqlite", SqliteStore(tmp_path / "prompts.db")),
    ]


@pytest.mark.parametrize("kind", ["memory", "yaml", "sqlite"])
def test_store_supports_registry_rules(tmp_path: Path, kind: str) -> None:
    store = dict(_stores(tmp_path))[kind]
    registry = Registry(store)
    registry.create_prompt(name="movie-critic", type="text", prompt="v1", labels=["production"])
    registry.create_prompt(name="movie-critic", type="text", prompt="v2", labels=["staging"])
    assert registry.get_prompt("movie-critic").prompt == "v1"
    assert registry.get_prompt("movie-critic", label="latest").prompt == "v2"
    assert registry.get_prompt("movie-critic", version=2).labels == ("latest", "staging")
    registry.update_prompt(name="movie-critic", version=2, new_labels=["production"])
    assert registry.get_prompt("movie-critic").prompt == "v2"
    with pytest.raises(InvalidPromptRequest):
        registry.create_prompt(name="movie-critic", type="chat", prompt=[], labels=["production"])
