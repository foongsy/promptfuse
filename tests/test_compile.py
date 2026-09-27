import promptfuse.models as models
from promptfuse.models import ChatPrompt, TextPrompt, make_client


def test_text_compile_substitutes_variables() -> None:
    prompt = make_client(
        name="movie-critic",
        version=1,
        prompt_type="text",
        prompt="As a {{criticLevel}} movie critic, do you like {{movie}}?",
    )
    assert isinstance(prompt, TextPrompt)
    assert prompt.compile(criticLevel="expert", movie="Dune 2") == (
        "As a expert movie critic, do you like Dune 2?"
    )


def test_whitespace_inside_braces_matches_the_same_variable() -> None:
    prompt = make_client(
        name="deep-agent/system",
        version=1,
        prompt_type="text",
        prompt="You are a {{ persona }} research assistant.",
    )
    assert prompt.compile(persona="analyst") == "You are a analyst research assistant."
    assert prompt.variables == ["persona"]


def test_missing_variable_stays_literal_and_none_is_empty() -> None:
    prompt = make_client(
        name="movie-critic",
        version=1,
        prompt_type="text",
        prompt="Do you like {{movie}}? Score: {{score}}.",
    )
    assert prompt.compile(score=None, extra="ignored") == "Do you like {{movie}}? Score: ."


def test_prompt_reference_is_not_expanded() -> None:
    body = "See @@@langfusePrompt:name=shared|label=production@@@"
    prompt = make_client(name="wrapper", version=1, prompt_type="text", prompt=body)
    assert prompt.compile() == body


def test_chat_compile_substitutes_and_splices_placeholders() -> None:
    prompt = make_client(
        name="movie-critic-chat",
        version=1,
        prompt_type="chat",
        prompt=[
            {"role": "system", "content": "You are a {{criticLevel}} movie critic."},
            {"type": "placeholder", "name": "chat_history"},
            {"role": "user", "content": "What about {{movie}}?"},
        ],
    )
    assert isinstance(prompt, ChatPrompt)
    assert prompt.variables == ["criticLevel", "movie"]
    compiled = prompt.compile(
        criticLevel="expert",
        movie="Dune 2",
        chat_history=[
            {"role": "user", "content": "I liked {{movie}}"},
            "not-a-message",
        ],
    )
    assert compiled == [
        {"role": "system", "content": "You are a expert movie critic."},
        {"role": "user", "content": "I liked Dune 2"},
        {"role": "NOT_GIVEN", "content": "not-a-message"},
        {"role": "user", "content": "What about Dune 2?"},
    ]


def test_unresolved_placeholder_stays_in_the_result() -> None:
    prompt = make_client(
        name="movie-critic-chat",
        version=1,
        prompt_type="chat",
        prompt=[{"type": "placeholder", "name": "chat_history"}],
    )
    assert prompt.compile() == [{"type": "placeholder", "name": "chat_history"}]


def test_non_list_placeholder_becomes_a_single_message() -> None:
    prompt = make_client(
        name="movie-critic-chat",
        version=1,
        prompt_type="chat",
        prompt=[{"type": "placeholder", "name": "chat_history"}],
    )
    assert prompt.compile(chat_history="nope") == [{"role": "NOT_GIVEN", "content": "nope"}]


def test_find_variable_names_keeps_duplicates_in_order() -> None:
    assert models.find_variable_names("{{a}} {{b}} {{a}}") == ["a", "b", "a"]
