import pytest
from promptfuse.errors import InvalidPromptRequest, PromptNotFound
from promptfuse.registry import Registry
from promptfuse.stores.memory import MemoryStore


def registry() -> Registry:
    return Registry(MemoryStore())


def test_fetch_table() -> None:
    reg = registry()
    created = reg.create_prompt(
        name="movie-critic",
        type="text",
        prompt="As a {{criticLevel}} movie critic, do you like {{movie}}?",
        labels=["production", "staging"],
    )
    assert created.version == 1
    assert created.labels == ("latest", "production", "staging")

    assert reg.get_prompt("movie-critic").version == 1
    assert reg.get_prompt("movie-critic", label="staging").version == 1
    assert reg.get_prompt("movie-critic", version=1).prompt.startswith("As a")

    with pytest.raises(InvalidPromptRequest):
        reg.get_prompt("movie-critic", label="production", version=1)
    with pytest.raises(PromptNotFound):
        reg.get_prompt("movie-critic", label="development")
    with pytest.raises(PromptNotFound):
        reg.get_prompt("missing")
    with pytest.raises(PromptNotFound):
        reg.get_prompt("movie-critic", version=2)
    with pytest.raises(PromptNotFound):
        reg.get_prompt("movie-critic", type="chat")


def test_create_appends_and_moves_labels() -> None:
    reg = registry()
    reg.create_prompt(name="movie-critic", type="text", prompt="v1", labels=["production"])
    second = reg.create_prompt(name="movie-critic", type="text", prompt="v2", labels=["staging"])
    assert second.version == 2
    assert reg.get_prompt("movie-critic").prompt == "v1"
    assert reg.get_prompt("movie-critic", label="staging").prompt == "v2"
    assert reg.get_prompt("movie-critic", label="latest").prompt == "v2"
    assert reg.get_prompt("movie-critic", version=1).labels == ("production",)


def test_type_cannot_change_and_latest_cannot_be_assigned() -> None:
    reg = registry()
    reg.create_prompt(name="movie-critic", type="text", prompt="v1", labels=["production"])
    with pytest.raises(InvalidPromptRequest):
        reg.create_prompt(name="movie-critic", type="chat", prompt=[], labels=["production"])
    with pytest.raises(InvalidPromptRequest):
        reg.create_prompt(name="other", type="text", prompt="x", labels=["latest"])


def test_update_prompt_replaces_labels_and_keeps_latest_on_the_highest() -> None:
    reg = registry()
    reg.create_prompt(name="movie-critic", type="text", prompt="v1", labels=["production"])
    reg.create_prompt(name="movie-critic", type="text", prompt="v2", labels=["staging"])
    updated = reg.update_prompt(name="movie-critic", version=1, new_labels=["production"])
    assert "production" in updated.labels
    assert "latest" not in updated.labels
    assert reg.get_prompt("movie-critic", label="latest").version == 2
    assert reg.get_prompt("movie-critic", label="staging").version == 2
    cleared = reg.update_prompt(name="movie-critic", version=2, new_labels=[])
    assert cleared.labels == ("latest",)
    with pytest.raises(PromptNotFound):
        reg.get_prompt("movie-critic", label="staging")
    with pytest.raises(InvalidPromptRequest):
        reg.update_prompt(name="movie-critic", version=2, new_labels=["latest"])
    with pytest.raises(PromptNotFound):
        reg.update_prompt(name="movie-critic", version=9, new_labels=["production"])


def test_chat_prompt_normalizes_messages() -> None:
    reg = registry()
    created = reg.create_prompt(
        name="movie-critic-chat",
        type="chat",
        prompt=[
            {"role": "system", "content": "You are a {{criticLevel}} movie critic."},
            {"type": "placeholder", "name": "chat_history"},
        ],
        labels=["production"],
        config={"temperature": 0},
    )
    assert created.type == "chat"
    assert created.config == {"temperature": 0}
    assert created.prompt == [
        {"type": "message", "role": "system", "content": "You are a {{criticLevel}} movie critic."},
        {"type": "placeholder", "name": "chat_history"},
    ]


def test_omitted_production_label_is_not_assumed() -> None:
    reg = registry()
    reg.create_prompt(name="movie-critic", type="text", prompt="v1")
    with pytest.raises(PromptNotFound):
        reg.get_prompt("movie-critic")
    assert reg.get_prompt("movie-critic", label="latest").prompt == "v1"
