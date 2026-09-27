"""Local prompt registry with a Langfuse-compatible read API."""

from promptfuse.client import Promptfuse
from promptfuse.errors import InvalidPromptRequest, PromptNotFound, PromptStoreError

__version__ = "0.1.0"

__all__ = [
    "InvalidPromptRequest",
    "PromptNotFound",
    "PromptStoreError",
    "Promptfuse",
    "__version__",
]
