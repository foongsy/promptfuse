"""Prompt clients and Langfuse-style ``{{variable}}`` compilation."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Mapping

from promptfuse.errors import InvalidPromptRequest

PromptType = str
ChatItem = dict[str, Any]


def find_variable_names(content: str) -> list[str]:
    """Return ``{{name}}`` placeholders in ``content``, in order."""

    names: list[str] = []
    index = 0
    while index < len(content):
        found = _parse_variable(content, index)
        if found is None:
            break
        names.append(found[0])
        index = found[2]
    return names


def compile_template(content: str, data: Mapping[str, Any] | None = None) -> str:
    """Substitute ``{{variable}}`` values.

    A missing name is left unchanged, including its braces. ``None`` becomes
    an empty string. Surrounding whitespace inside the braces is ignored.
    """

    if data is None:
        return content
    pieces: list[str] = []
    index = 0
    while index < len(content):
        found = _parse_variable(content, index)
        if found is None:
            pieces.append(content[index:])
            break
        name, start, end = found
        pieces.append(content[index:start])
        if name in data:
            value = data[name]
            pieces.append("" if value is None else str(value))
        else:
            pieces.append(content[start:end])
        index = end
    return "".join(pieces)


def _parse_variable(content: str, start_index: int) -> tuple[str, int, int] | None:
    opening = content.find("{{", start_index)
    if opening == -1:
        return None
    closing = content.find("}}", opening + 2)
    if closing == -1:
        return None
    name = content[opening + 2 : closing].strip()
    return name, opening, closing + 2


def normalize_prompt(prompt_type: str, prompt: Any) -> str | list[ChatItem]:
    """Return the stored form of a text or chat prompt."""

    if prompt_type == "text":
        if not isinstance(prompt, str):
            raise InvalidPromptRequest("a text prompt must be a string")
        return prompt
    if prompt_type == "chat":
        if not isinstance(prompt, list):
            raise InvalidPromptRequest("a chat prompt must be a list of messages")
        return [_normalize_chat_item(item) for item in prompt]
    raise InvalidPromptRequest(f"unknown prompt type: {prompt_type!r}")


def _normalize_chat_item(item: Any) -> ChatItem:
    if not isinstance(item, dict):
        raise InvalidPromptRequest("a chat item must be a mapping")
    kind = item.get("type")
    if kind == "placeholder" or (kind is None and "name" in item and "role" not in item):
        if "role" in item or "content" in item:
            raise InvalidPromptRequest("a placeholder must not include role or content")
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise InvalidPromptRequest("a placeholder name must be a non-empty string")
        return {"type": "placeholder", "name": name}
    if kind not in (None, "message"):
        raise InvalidPromptRequest(f"unknown chat item type: {kind!r}")
    role = item.get("role")
    content = item.get("content")
    if not isinstance(role, str) or not isinstance(content, str):
        raise InvalidPromptRequest("a chat message needs string role and content")
    return {"type": "message", "role": role, "content": content}


@dataclass(frozen=True)
class TextPrompt:
    """A text prompt client."""

    name: str
    version: int
    prompt: str
    config: dict[str, Any]
    labels: tuple[str, ...]
    tags: tuple[str, ...]
    commit_message: str | None
    is_fallback: bool = False

    @property
    def type(self) -> str:
        return "text"

    @property
    def variables(self) -> list[str]:
        return find_variable_names(self.prompt)

    def compile(self, **kwargs: Any) -> str:
        return compile_template(self.prompt, kwargs)


@dataclass(frozen=True)
class ChatPrompt:
    """A chat prompt client."""

    name: str
    version: int
    stored_messages: tuple[tuple[tuple[str, Any], ...], ...]
    config: dict[str, Any]
    labels: tuple[str, ...]
    tags: tuple[str, ...]
    commit_message: str | None
    is_fallback: bool = False

    @property
    def type(self) -> str:
        return "chat"

    @property
    def prompt(self) -> list[ChatItem]:
        return [dict(item) for item in self.stored_messages]

    @property
    def variables(self) -> list[str]:
        names: list[str] = []
        for item in self.prompt:
            if item.get("type") == "message":
                names.extend(find_variable_names(item["content"]))
        return names

    def compile(self, **kwargs: Any) -> list[dict[str, Any]]:
        compiled: list[dict[str, Any]] = []
        for item in self.prompt:
            if item["type"] == "message":
                compiled.append(
                    {
                        "role": item["role"],
                        "content": compile_template(item["content"], kwargs),
                    }
                )
                continue
            name = item["name"]
            if name not in kwargs:
                compiled.append({"type": "placeholder", "name": name})
                continue
            value = kwargs[name]
            if isinstance(value, list):
                for entry in value:
                    if isinstance(entry, dict):
                        copied = dict(entry)
                        content = copied.get("content", "")
                        if isinstance(content, str):
                            copied["content"] = compile_template(content, kwargs)
                        compiled.append(copied)
                    else:
                        compiled.append({"role": "NOT_GIVEN", "content": str(entry)})
            else:
                compiled.append({"role": "NOT_GIVEN", "content": str(value)})
        return compiled


PromptClient = TextPrompt | ChatPrompt


def make_client(
    *,
    name: str,
    version: int,
    prompt_type: str,
    prompt: str | list[ChatItem],
    config: Mapping[str, Any] | None = None,
    labels: list[str] | tuple[str, ...] = (),
    tags: list[str] | tuple[str, ...] = (),
    commit_message: str | None = None,
    is_fallback: bool = False,
) -> PromptClient:
    """Build a prompt client from stored fields."""

    stored_config = copy.deepcopy(dict(config or {}))
    stored_labels = tuple(sorted(labels))
    stored_tags = tuple(tags)
    if prompt_type == "text":
        if not isinstance(prompt, str):
            raise InvalidPromptRequest("a text prompt must be a string")
        return TextPrompt(
            name=name,
            version=version,
            prompt=prompt,
            config=stored_config,
            labels=stored_labels,
            tags=stored_tags,
            commit_message=commit_message,
            is_fallback=is_fallback,
        )
    if prompt_type == "chat":
        normalized = normalize_prompt("chat", prompt)
        assert isinstance(normalized, list)
        frozen = tuple(tuple(sorted(item.items())) for item in normalized)
        return ChatPrompt(
            name=name,
            version=version,
            stored_messages=frozen,
            config=stored_config,
            labels=stored_labels,
            tags=stored_tags,
            commit_message=commit_message,
            is_fallback=is_fallback,
        )
    raise InvalidPromptRequest(f"unknown prompt type: {prompt_type!r}")


def fallback_client(name: str, fallback: str | list[Any]) -> PromptClient:
    """Build the client used when the cache and the stores cannot answer."""

    if isinstance(fallback, str):
        prompt_type: str = "text"
        prompt: str | list[ChatItem] = fallback
    elif isinstance(fallback, list):
        prompt_type = "chat"
        prompt = normalize_prompt("chat", fallback)
    else:
        raise InvalidPromptRequest("fallback must be a string or a list of messages")
    return make_client(
        name=name,
        version=0,
        prompt_type=prompt_type,
        prompt=prompt,
        is_fallback=True,
    )


def clone_client(client: PromptClient) -> PromptClient:
    """Return a detached copy of a cached client."""

    return copy.deepcopy(client)
