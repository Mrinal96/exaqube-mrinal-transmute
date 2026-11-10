class ExtractionError(ValueError):
    """A well-typed source file cannot be extracted within supported limits."""


class ExtractionLimitError(ExtractionError):
    """The source exceeds an explicitly supported ingestion limit."""
