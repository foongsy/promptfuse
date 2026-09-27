# promptfuse

[![ci](https://github.com/foongsy/promptfuse/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/foongsy/promptfuse/actions/workflows/ci.yml)

Local prompt registry with a Langfuse-compatible prompt API. Prompts are stored in a YAML tree, in SQLite, or in SQLite with the YAML tree as the seed. `promptfuse` does not call Langfuse Cloud and does not send traces.

This document is the contract for the public API.

The prompt record and the fetch, label, cache, compile, and fallback rules match [Langfuse prompt management](https://langfuse.com/docs/prompt-management/data-model). Where Langfuse leaves a local-store choice open, this document defines it.

## Install

Requires Python 3.10+.

```bash
pip install promptfuse
```

## Client

```python
from promptfuse import Promptfuse

client = Promptfuse(
    yaml_dir="prompts",       # optional YAML store
    sqlite_path="prompts.db", # optional SQLite store
    snapshot_path=None,       # optional disk cache of successful reads
    cache_ttl_seconds=60,     # default; 0 disables the memory cache
)
```

At least one of `yaml_dir` and `sqlite_path` is required. See [Stores](#stores) for which one is read and written.

```python
prompt = client.get_prompt("deep-agent/system")
text = prompt.compile(persona="analyst")

client.create_prompt(
    name="deep-agent/system",
    type="text",
    prompt="You are a {{persona}} research assistant.",
    labels=["production"],
    config={"model": "gpt-4.1", "temperature": 0.2},
    tags=["deep-agent"],
    commit_message="initial system prompt",
)

client.update_prompt(
    name="deep-agent/system",
    version=1,
    new_labels=["staging"],
)
```

`get_prompt` follows [`GET /api/public/v2/prompts/{name}`](https://langfuse.com/docs/prompt-management/features/prompt-version-control). `create_prompt` and `update_prompt` follow the Langfuse Python SDK methods of the same names.

## Prompt client

`get_prompt`, `create_prompt`, and a fallback all return a prompt client.

| Attribute | Meaning |
|---|---|
| `name` | Prompt name. Slashes are folders (`deep-agent/system`). |
| `version` | Integer. Store versions start at 1. |
| `type` | `"text"` or `"chat"`. Fixed for a name after the first version. |
| `prompt` | Text prompt: `str`. Chat prompt: list of messages. |
| `config` | JSON object versioned with this prompt. `{}` when omitted. |
| `labels` | Labels currently pointing at this version. |
| `tags` | String list. `[]` when omitted. |
| `commit_message` | Optional string. |
| `is_fallback` | `True` only for a client built from the `fallback` argument. |
| `variables` | `{{name}}` placeholders found in the prompt, in order. |

A text prompt's `prompt` is a string. A chat prompt's `prompt` is a list of either of:

```python
{"type": "message", "role": "system", "content": "You are a {{persona}}."}
{"type": "placeholder", "name": "chat_history"}
```

`role` is any string. `promptfuse` does not restrict it to `system`, `user`, or `assistant`.

`config` is an arbitrary JSON object. Typical keys are `model`, `temperature`, `max_tokens`, `response_format`, `tools`, and `tool_choice`. `promptfuse` stores and returns `config`. It does not call a model.

## Fetching

From [How label resolution works](https://langfuse.com/docs/prompt-management/features/prompt-version-control#label-resolution):

| Call | Result |
|---|---|
| `get_prompt(name)` | Version labeled `production`. |
| `get_prompt(name, label="staging")` | Version labeled `staging`. |
| `get_prompt(name, version=3)` | Version 3, whatever its labels are. |
| `get_prompt(name, label=..., version=...)` | `InvalidPromptRequest`. `label` and `version` are mutually exclusive. |

A missing name, a missing label, or a missing version raises `PromptNotFound`. There is no silent fallback from `staging` to `production` or `latest`.

`label` defaults to `"production"` only when `version` is omitted. `type` defaults to `"text"`. Passing `type="chat"` for a text prompt, or the reverse, raises `PromptNotFound`. The default `type` does not coerce a chat prompt into text.

`latest` is a real label. It always points at the highest version of that name. Callers fetch it with `label="latest"`. They cannot assign it.

`cache_ttl_seconds` overrides the client default for that call. `fallback` is used only as described in [Fallback](#fallback).

## Creating a version

`create_prompt` appends a version. It does not edit an existing version.

- The first version of a name is `1`. The next is `max(version) + 1`.
- `type` must match every existing version of that name. A change raises `InvalidPromptRequest`.
- `labels` moves each listed label onto the new version and off any older version. Omitted labels stay where they are.
- `latest` always moves to the new version. An entry of `"latest"` in `labels` raises `InvalidPromptRequest`.
- `config`, `tags`, and `commit_message` belong to this version.

```python
client.create_prompt(
    name="movie-critic",
    type="text",
    prompt="As a {{criticLevel}} movie critic, do you like {{movie}}?",
    labels=["production"],
)
```

The same call with `type="chat"` takes a message list:

```python
client.create_prompt(
    name="movie-critic-chat",
    type="chat",
    prompt=[
        {"role": "system", "content": "You are a {{criticLevel}} movie critic."},
        {"type": "placeholder", "name": "chat_history"},
        {"role": "user", "content": "What should I watch next?"},
    ],
    labels=["production"],
)
```

A chat item with `role` and `content` is stored as `{"type": "message", "role": ..., "content": ...}`. `type` may be omitted on input. A placeholder must be `{"type": "placeholder", "name": "..."}` and must not include `role` or `content`.

## Moving labels

`update_prompt(name, version, new_labels)` replaces the labels on that version. Prompt text, `config`, `tags`, and `commit_message` stay as stored.

- Each name in `new_labels` is removed from every other version of this prompt, then pointed at `version`.
- Labels previously on `version` and absent from `new_labels` are removed.
- `"latest"` in `new_labels` raises `InvalidPromptRequest`. `latest` stays on the highest version.
- A version that does not exist raises `PromptNotFound`.

Rollback is this call. Repoint `production` at the earlier version:

```python
client.update_prompt(name="movie-critic", version=2, new_labels=["production"])
```

## Compile

`compile` substitutes `{{variable}}` the way the Langfuse Python SDK's `TemplateParser` does.

- The name is the text between `{{` and `}}`, with surrounding whitespace removed. `{{ persona }}` and `{{persona}}` are the same variable.
- A provided value is inserted with `str(value)`. `None` is inserted as an empty string.
- A variable with no matching keyword argument is left unchanged, including its original braces.
- `compile` does not require every variable to be present, and it does not reject extra keyword arguments. There is no `throw_on_incomplete_variables` switch.

```python
prompt.compile(criticLevel="expert", movie="Dune 2")
# "As an expert movie critic, do you like Dune 2?"
```

Text `compile(**kwargs)` returns a `str`.

Chat `compile(**kwargs)` returns a list of messages:

- A message gets `{{variable}}` substitution in `content`. The result is `{"role": ..., "content": ...}` with no `type` key.
- A placeholder whose name is a keyword argument must be a list of messages. Each dict in that list is copied, and its `content` is compiled when it is a string. A non-dict item, or a value that is not a list, is appended as `{"role": "NOT_GIVEN", "content": str(value)}`.
- A placeholder with no keyword argument stays `{"type": "placeholder", "name": ...}` in the result.

Prompt references are stored and returned as literal text. `promptfuse` does not expand `@@@langfusePrompt:name=...|version=1@@@` or `@@@langfusePrompt:name=...|label=production@@@`.

`get_langchain_prompt` is not part of this package.

## Cache

The memory cache matches the [Langfuse client cache](https://langfuse.com/docs/prompt-management/features/caching).

- The key is `(name, "label", label)` or `(name, "version", version)`. A label and a version pin do not share an entry.
- Default TTL is 60 seconds.
- A fresh entry is returned without reading the store.
- After the TTL, the stale client is returned immediately and the store is read in the background. A failed refresh keeps the stale client.
- `cache_ttl_seconds=0` skips the memory cache and reads the store on every call.

The cache stores the resolved client, so a label move is visible on the next read after the TTL, not at the moment the label changes. Use `cache_ttl_seconds=0` when a call must see the store immediately. `label="latest"` with a TTL of 0 is the usual development setting.

## Fallback

`fallback` matches [guaranteed availability](https://langfuse.com/docs/prompt-management/features/guaranteed-availability).

`get_prompt` raises if the memory cache has neither a fresh nor a stale client and every store read fails, and `fallback` was not passed.

`fallback` is used only in that case. A successful store read ignores `fallback`. A stale cache hit ignores `fallback` and does not build a fallback client.

A string fallback returns a text client. A list fallback returns a chat client. The client uses the requested `name`, `version=0`, `labels=[]`, `config={}`, `tags=[]`, `commit_message=None`, and `is_fallback=True`. `compile` still runs on the fallback body.

```python
prompt = client.get_prompt("movie-critic", fallback="Do you like {{movie}}?")
prompt.is_fallback  # True only when the stores and the cache could not answer
```

## Stores

YAML and SQLite store the same prompt record. The memory cache sits in front of both.

| Constructor | Source of truth | Writes |
|---|---|---|
| `yaml_dir` only | YAML | YAML |
| `sqlite_path` only | SQLite | SQLite |
| both | SQLite, when it can be opened | SQLite |

A healthy SQLite database that does not contain the prompt raises `PromptNotFound`. It does not continue into YAML. YAML is consulted when SQLite cannot be opened or a query fails, and when SQLite was not configured.

### YAML

```text
prompts/
├── index.yaml
└── deep-agent/
    └── system/
        ├── v1.yaml
        └── v2.yaml
```

The directory under `yaml_dir` is the prompt name. `deep-agent/system/v2.yaml` is version 2 of `deep-agent/system`. The file stem must be `v` plus the integer version. Names must not contain `..` or escape `yaml_dir`.

Version files are immutable. A label change edits `index.yaml` only.

```yaml
# prompts/deep-agent/system/v1.yaml
name: deep-agent/system
version: 1
type: text
prompt: |
  You are a {{persona}} research assistant.
config:
  model: gpt-4.1
  temperature: 0.2
tags: ["deep-agent", "system"]
commit_message: initial system prompt
created_at: "2026-09-28T00:00:00Z"
updated_at: "2026-09-28T00:00:00Z"
```

`name` and `version` in the file must match the path. `type` is `text` or `chat`. For `chat`, `prompt` is the message list. `config`, `tags`, `commit_message`, `created_at`, and `updated_at` may be omitted.

```yaml
# prompts/index.yaml
prompts:
  deep-agent/system:
    development: 1
    staging: 1
    production: 1
```

Index values are integers. A label points at one version. `latest` must not appear in the index; the highest `vN.yaml` for that name is `latest`. A version file does not list its labels.

`create_prompt` writes `vN.yaml` and updates the index. `update_prompt` updates the index only. Neither rewrites an existing `vN.yaml`.

### SQLite

Two tables:

```sql
CREATE TABLE prompt_version (
    name TEXT NOT NULL,
    version INTEGER NOT NULL,
    type TEXT NOT NULL,
    prompt TEXT NOT NULL,          -- JSON: a string or a message list
    config TEXT NOT NULL,          -- JSON object
    tags TEXT NOT NULL,            -- JSON array of strings
    commit_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (name, version)
);

CREATE TABLE prompt_label (
    name TEXT NOT NULL,
    label TEXT NOT NULL,
    version INTEGER NOT NULL,
    PRIMARY KEY (name, label),
    FOREIGN KEY (name, version) REFERENCES prompt_version (name, version)
);
```

`prompt_version` rows are inserted, never updated. `prompt_label` is the only mutable data. `latest` is a row in `prompt_label`, moved when a version is inserted.

### Using both

`import_yaml()` copies the YAML tree into SQLite.

- A YAML version that is not in SQLite is inserted.
- A YAML version that is already in SQLite with the same body, `type`, `config`, `tags`, and `commit_message` is left as stored.
- A YAML version whose stored body differs raises `InvalidPromptRequest`. Versions stay immutable.
- Labels in `index.yaml` replace the SQLite label rows for names present in the index. SQLite versions that exist only in SQLite are kept.
- `latest` is recomputed as the highest version after the import.

`Promptfuse(..., import_yaml=True)` runs `import_yaml()` once at construction. The default is `False`. Import overwrites SQLite label pointers for the imported names, including labels that were moved at runtime.

### Disk snapshot

`snapshot_path` is a JSON file of prompt clients from successful store reads. It is a cache. It is not edited by hand and it is not a third source of truth.

On a store outage, `get_prompt` uses the snapshot entry for that cache key when the memory cache is empty. A missing snapshot entry then uses YAML if SQLite failed and `yaml_dir` is set. A snapshot hit sets `is_fallback` to `False`.

The snapshot is updated after a successful SQLite or YAML read. A fallback client is not written to the snapshot.

## Errors

| Exception | When |
|---|---|
| `PromptNotFound` | Unknown name, label, or version. `type` does not match the stored prompt. SQLite is healthy and the row is absent. |
| `InvalidPromptRequest` | `label` and `version` both set. `type` changes on `create_prompt`. `"latest"` is assigned by the caller or written in `index.yaml`. A version file disagrees with its path. `import_yaml()` finds a body that differs from SQLite. The YAML path escapes `yaml_dir`. |
| `PromptStoreError` | SQLite cannot be opened or a query fails, and snapshot, YAML, and `fallback` do not produce a client. |

`PromptNotFound` and `InvalidPromptRequest` are not retried through the seed files when SQLite is healthy.

## Out of scope

- Langfuse Cloud, API keys, tracing, and linking a prompt to a generation
- Expanding `@@@langfusePrompt:...@@@` references
- `get_langchain_prompt`
- Protected labels
- Postgres and other database engines
- A network server

## References

- [Prompt data model](https://langfuse.com/docs/prompt-management/data-model)
- [Version control and label resolution](https://langfuse.com/docs/prompt-management/features/prompt-version-control)
- [Variables](https://langfuse.com/docs/prompt-management/features/variables)
- [Message placeholders](https://langfuse.com/docs/prompt-management/features/message-placeholders)
- [Prompt config](https://langfuse.com/docs/prompt-management/features/config)
- [Client cache](https://langfuse.com/docs/prompt-management/features/caching)
- [Guaranteed availability](https://langfuse.com/docs/prompt-management/features/guaranteed-availability)
- [Folders](https://langfuse.com/docs/prompt-management/features/folders)
- Compile rules follow `TemplateParser` in the Langfuse Python SDK (`langfuse/model.py`): brace text is stripped, missing variables stay literal, and `None` becomes an empty string.
