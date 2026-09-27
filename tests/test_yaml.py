from pathlib import Path

import pytest
import yaml
from promptfuse.errors import InvalidPromptRequest, PromptNotFound
from promptfuse.registry import Registry
from promptfuse.stores.yaml import YamlStore


def test_parent_and_child_prompts_coexist(tmp_path: Path) -> None:
    registry = Registry(YamlStore(tmp_path))
    registry.create_prompt(name="deep-agent", type="text", prompt="parent", labels=["production"])
    registry.create_prompt(
        name="deep-agent/system",
        type="text",
        prompt="child",
        labels=["production"],
    )
    assert registry.get_prompt("deep-agent").prompt == "parent"
    assert registry.get_prompt("deep-agent/system").prompt == "child"
    assert (tmp_path / "deep-agent" / "v1.yaml").is_file()
    assert (tmp_path / "deep-agent" / "system" / "v1.yaml").is_file()


def test_label_move_does_not_rewrite_the_version_file(tmp_path: Path) -> None:
    store = YamlStore(tmp_path)
    registry = Registry(store)
    registry.create_prompt(name="movie-critic", type="text", prompt="v1", labels=["production"])
    registry.create_prompt(name="movie-critic", type="text", prompt="v2", labels=["staging"])
    original = (tmp_path / "movie-critic" / "v1.yaml").read_text(encoding="utf-8")
    registry.update_prompt(name="movie-critic", version=2, new_labels=["production"])
    assert (tmp_path / "movie-critic" / "v1.yaml").read_text(encoding="utf-8") == original
    index = yaml.safe_load((tmp_path / "index.yaml").read_text(encoding="utf-8"))
    assert index["prompts"]["movie-critic"]["production"] == 2
    assert "latest" not in index["prompts"]["movie-critic"]


def test_latest_in_the_index_is_rejected(tmp_path: Path) -> None:
    (tmp_path).mkdir(exist_ok=True)
    (tmp_path / "index.yaml").write_text(
        yaml.safe_dump({"prompts": {"movie-critic": {"latest": 1}}}),
        encoding="utf-8",
    )
    registry = Registry(YamlStore(tmp_path))
    with pytest.raises(InvalidPromptRequest):
        registry.get_prompt("movie-critic", label="production")


def test_version_file_must_match_its_path(tmp_path: Path) -> None:
    version = tmp_path / "movie-critic"
    version.mkdir()
    (version / "v1.yaml").write_text(
        yaml.safe_dump({"name": "other", "version": 1, "type": "text", "prompt": "x"}),
        encoding="utf-8",
    )
    (tmp_path / "index.yaml").write_text(
        yaml.safe_dump({"prompts": {"movie-critic": {"production": 1}}}),
        encoding="utf-8",
    )
    registry = Registry(YamlStore(tmp_path))
    with pytest.raises(InvalidPromptRequest):
        registry.get_prompt("movie-critic")


def test_path_escape_is_rejected(tmp_path: Path) -> None:
    registry = Registry(YamlStore(tmp_path))
    with pytest.raises(InvalidPromptRequest):
        registry.create_prompt(name="../outside", type="text", prompt="x", labels=["production"])
    with pytest.raises(PromptNotFound):
        registry.get_prompt("missing/prompt")
