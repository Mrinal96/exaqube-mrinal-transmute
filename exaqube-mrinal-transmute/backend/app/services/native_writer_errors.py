"""Errors raised when canonical IR cannot be represented safely by a native writer."""


class UnsupportedIRContentError(ValueError):
    """The validated IR contains content the selected deterministic writer cannot represent."""
