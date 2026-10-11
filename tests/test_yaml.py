from pathlib import Path

import pytest
import yaml
from promptfuse.errors import InvalidPromptRequest, PromptNotFound
from promptfuse.registry import Registry
from promptfuse.stores.yaml import YamlStore


def _write_text_prompt(
    root: Path,
    name: str,
    version: int,
    body: str,
    *,
    frontmatter_extra: dict | None = None,
    file_name: str | None = None,
) -> None:
    directory = root.joinpath(*name.split("/"))
    directory.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "name": name,
        "version": version,
        "type": "text",
        "config": {},
        "tags": [],
        "commit_message": None,
        "created_at": "",
        "updated_at": "",
    }
    if frontmatter_extra:
        frontmatter.update(frontmatter_extra)
    dumped = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
    path = directory / (file_name or f"v{version}.md")
    path.write_bytes(f"---\n{dumped}---\n{body}".encode("utf-8"))


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
    assert (tmp_path / "deep-agent" / "v1.md").is_file()
    assert (tmp_path / "deep-agent" / "system" / "v1.md").is_file()


def test_label_move_does_not_rewrite_the_version_file(tmp_path: Path) -> None:
    store = YamlStore(tmp_path)
    registry = Registry(store)
    registry.create_prompt(name="movie-critic", type="text", prompt="v1", labels=["production"])
    registry.create_prompt(name="movie-critic", type="text", prompt="v2", labels=["staging"])
    original = (tmp_path / "movie-critic" / "v1.md").read_text(encoding="utf-8")
    registry.update_prompt(name="movie-critic", version=2, new_labels=["production"])
    assert (tmp_path / "movie-critic" / "v1.md").read_text(encoding="utf-8") == original
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
    _write_text_prompt(
        tmp_path,
        "movie-critic",
        1,
        "x",
        frontmatter_extra={"name": "other"},
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


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("trailing_newlines", [0, 1, 2])
def test_text_markdown_round_trip_preserves_body(
    tmp_path: Path, newline: str, trailing_newlines: int
) -> None:
    body = newline.join(["# Title", "", "You are a {{persona}}.", "", "- item one", "- item two"])
    body += newline * trailing_newlines
    registry = Registry(YamlStore(tmp_path))
    registry.create_prompt(
        name="deep-agent/system",
        type="text",
        prompt=body,
        labels=["production"],
        config={"model": "gpt-4.1"},
        tags=["deep-agent"],
        commit_message="initial",
    )
    text = (tmp_path / "deep-agent" / "system" / "v1.md").read_bytes().decode("utf-8")
    assert text.startswith("---\n")
    assert "prompt:" not in text.split("---", 2)[1]
    assert text.split("---\n", 2)[2] == body
    loaded = registry.get_prompt("deep-agent/system")
    assert loaded.prompt == body
    assert loaded.config == {"model": "gpt-4.1"}
    assert loaded.tags == ("deep-agent",)


@pytest.mark.parametrize("ending", ["\n", "\n\n", "\r\n"])
def test_hand_authored_text_preserves_trailing_newlines(tmp_path: Path, ending: str) -> None:
    body = "You are a {{persona}}." + ending
    _write_text_prompt(tmp_path, "deep-agent/system", 1, body)
    loaded = Registry(YamlStore(tmp_path)).get_prompt("deep-agent/system", version=1)
    assert loaded.prompt == body


def test_chat_round_trip_uses_frontmatter_prompt(tmp_path: Path) -> None:
    messages = [
        {"role": "system", "content": "You are a {{criticLevel}} movie critic."},
        {"type": "placeholder", "name": "chat_history"},
    ]
    registry = Registry(YamlStore(tmp_path))
    registry.create_prompt(
        name="movie-critic-chat",
        type="chat",
        prompt=messages,
        labels=["production"],
    )
    text = (tmp_path / "movie-critic-chat" / "v1.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert text.rstrip().endswith("---")
    loaded = registry.get_prompt("movie-critic-chat", type="chat")
    assert loaded.prompt == [
        {"type": "message", "role": "system", "content": "You are a {{criticLevel}} movie critic."},
        {"type": "placeholder", "name": "chat_history"},
    ]


def test_text_frontmatter_prompt_is_rejected(tmp_path: Path) -> None:
    _write_text_prompt(
        tmp_path,
        "movie-critic",
        1,
        "body",
        frontmatter_extra={"prompt": "from-frontmatter"},
    )
    (tmp_path / "index.yaml").write_text(
        yaml.safe_dump({"prompts": {"movie-critic": {"production": 1}}}),
        encoding="utf-8",
    )
    with pytest.raises(InvalidPromptRequest):
        Registry(YamlStore(tmp_path)).get_prompt("movie-critic")


def test_chat_non_empty_body_is_rejected(tmp_path: Path) -> None:
    directory = tmp_path / "movie-critic-chat"
    directory.mkdir()
    frontmatter = {
        "name": "movie-critic-chat",
        "version": 1,
        "type": "chat",
        "prompt": [{"role": "system", "content": "hi"}],
        "config": {},
        "tags": [],
    }
    dumped = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
    (directory / "v1.md").write_text(f"---\n{dumped}---\nnot empty\n", encoding="utf-8")
    (tmp_path / "index.yaml").write_text(
        yaml.safe_dump({"prompts": {"movie-critic-chat": {"production": 1}}}),
        encoding="utf-8",
    )
    with pytest.raises(InvalidPromptRequest):
        Registry(YamlStore(tmp_path)).get_prompt("movie-critic-chat", type="chat")


def test_legacy_yaml_version_file_is_rejected(tmp_path: Path) -> None:
    directory = tmp_path / "movie-critic"
    directory.mkdir()
    (directory / "v1.yaml").write_text(
        yaml.safe_dump({"name": "movie-critic", "version": 1, "type": "text", "prompt": "x"}),
        encoding="utf-8",
    )
    (tmp_path / "index.yaml").write_text(
        yaml.safe_dump({"prompts": {"movie-critic": {"production": 1}}}),
        encoding="utf-8",
    )
    with pytest.raises(InvalidPromptRequest, match="legacy yaml"):
        Registry(YamlStore(tmp_path)).get_prompt("movie-critic")
