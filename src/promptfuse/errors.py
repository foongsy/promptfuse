"""Errors raised by the prompt registry."""


class PromptfuseError(Exception):
    """Base error for promptfuse."""


class PromptNotFound(PromptfuseError):
    """The name, label, version, or prompt type does not resolve."""


class InvalidPromptRequest(PromptfuseError):
    """The request or the stored prompt breaks the registry rules."""


class PromptStoreError(PromptfuseError):
    """The store could not be read or written."""
