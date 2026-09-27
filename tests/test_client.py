from pathlib import Path

import pytest
import yaml
from promptfuse import InvalidPromptRequest, PromptNotFound, Promptfuse
from promptfuse.registry import Registry
from promptfuse.stores.sqlite import SqliteStore
from promptfuse.stores.yaml import YamlStore


def test_yaml_and_sqlite_clients_round_trip(tmp_path: Path) -> None:
    yaml_client = Promptfuse(yaml_dir=tmp_path / "prompts")
    created = yaml_client.create_prompt(
        name="deep-agent/system",
        type="text",
        prompt="You are a {{persona}} research assistant.",
        labels=["production"],
        config={"temperature": 0.2},
    )
    assert created.compile(persona="analyst") == "You are a analyst research assistant."
    assert yaml_client.get_prompt("deep-agent/system").version == 1

    sqlite_client = Promptfuse(sqlite_path=tmp_path / "prompts.db")
    sqlite_client.create_prompt(
        name="movie-critic-chat",
        type="chat",
        prompt=[
            {"role": "system", "content": "You are a {{criticLevel}} movie critic."},
            {"type": "placeholder", "name": "chat_history"},
        ],
        labels=["production"],
    )
    chat = sqlite_client.get_prompt("movie-critic-chat", type="chat")
    assert chat.compile(criticLevel="expert")[0]["content"] == "You are a expert movie critic."


def test_create_is_visible_without_waiting_for_ttl(tmp_path: Path) -> None:
    client = Promptfuse(yaml_dir=tmp_path / "prompts", cache_ttl_seconds=60)
    client.create_prompt(name="movie-critic", type="text", prompt="v1", labels=["production"])
    assert client.get_prompt("movie-critic").prompt == "v1"
    client.create_prompt(name="movie-critic", type="text", prompt="v2", labels=["production"])
    assert client.get_prompt("movie-critic").prompt == "v2"


def test_healthy_sqlite_miss_does_not_read_yaml(tmp_path: Path) -> None:
    yaml_dir = tmp_path / "prompts"
    Registry(YamlStore(yaml_dir)).create_prompt(
        name="movie-critic",
        type="text",
        prompt="from-yaml",
        labels=["production"],
    )
    client = Promptfuse(yaml_dir=yaml_dir, sqlite_path=tmp_path / "prompts.db")
    with pytest.raises(PromptNotFound):
        client.get_prompt("movie-critic")
    client.create_prompt(name="movie-critic", type="text", prompt="from-sqlite", labels=["production"])
    assert client.get_prompt("movie-critic").prompt == "from-sqlite"
    assert "from-sqlite" not in (yaml_dir / "movie-critic" / "v1.yaml").read_text(encoding="utf-8")


def test_sqlite_outage_uses_snapshot_before_yaml(tmp_path: Path) -> None:
    snapshot = tmp_path / "snap.json"
    yaml_dir = tmp_path / "prompts"
    database = tmp_path / "prompts.db"
    client = Promptfuse(yaml_dir=yaml_dir, sqlite_path=database, snapshot_path=snapshot)
    client.create_prompt(name="movie-critic", type="text", prompt="from-sqlite", labels=["production"])
    assert client.get_prompt("movie-critic").prompt == "from-sqlite"
    version = yaml_dir / "movie-critic"
    version.mkdir(parents=True)
    (version / "v1.yaml").write_text(
        yaml.safe_dump(
            {"name": "movie-critic", "version": 1, "type": "text", "prompt": "from-yaml"}
        ),
        encoding="utf-8",
    )
    (yaml_dir / "index.yaml").write_text(
        yaml.safe_dump({"prompts": {"movie-critic": {"production": 1}}}),
        encoding="utf-8",
    )
    broken = tmp_path / "broken-db"
    broken.mkdir()
    outage = Promptfuse(yaml_dir=yaml_dir, sqlite_path=broken, snapshot_path=snapshot)
    restored = outage.get_prompt("movie-critic")
    assert restored.prompt == "from-sqlite"
    assert restored.is_fallback is False

    empty_snapshot = tmp_path / "empty.json"
    seeded = Promptfuse(yaml_dir=yaml_dir, sqlite_path=broken, snapshot_path=empty_snapshot)
    assert seeded.get_prompt("movie-critic").prompt == "from-yaml"


def test_import_yaml_copies_labels_and_keeps_sqlite_only_versions(tmp_path: Path) -> None:
    yaml_dir = tmp_path / "prompts"
    database = tmp_path / "prompts.db"
    Registry(YamlStore(yaml_dir)).create_prompt(
        name="movie-critic",
        type="text",
        prompt="v1",
        labels=["production"],
    )
    Registry(SqliteStore(database)).create_prompt(
        name="sqlite-only",
        type="text",
        prompt="keep",
        labels=["production"],
    )
    client = Promptfuse(yaml_dir=yaml_dir, sqlite_path=database, import_yaml=True)
    assert client.get_prompt("movie-critic").prompt == "v1"
    assert client.get_prompt("sqlite-only").prompt == "keep"
    client.update_prompt(name="movie-critic", version=1, new_labels=["production", "staging"])
    client.import_yaml()
    with pytest.raises(PromptNotFound):
        client.get_prompt("movie-critic", label="staging")
    text = (yaml_dir / "movie-critic" / "v1.yaml").read_text(encoding="utf-8")
    (yaml_dir / "movie-critic" / "v1.yaml").write_text(
        text.replace("prompt: v1", "prompt: changed"),
        encoding="utf-8",
    )
    with pytest.raises(InvalidPromptRequest):
        client.import_yaml()


def test_constructor_requires_a_store() -> None:
    with pytest.raises(InvalidPromptRequest):
        Promptfuse()
    with pytest.raises(InvalidPromptRequest):
        Promptfuse(yaml_dir="prompts").import_yaml()
