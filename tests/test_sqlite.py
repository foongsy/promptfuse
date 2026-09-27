import threading
from pathlib import Path

from promptfuse.registry import Registry
from promptfuse.stores.sqlite import SqliteStore


def test_threads_open_their_own_connections(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "prompts.db")
    registry = Registry(store)
    registry.create_prompt(name="movie-critic", type="text", prompt="v1", labels=["production"])
    errors: list[BaseException] = []

    def read() -> None:
        try:
            assert registry.get_prompt("movie-critic").prompt == "v1"
        except BaseException as exc:  # noqa: BLE001 - collect worker failures
            errors.append(exc)

    workers = [threading.Thread(target=read) for _ in range(4)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert errors == []
