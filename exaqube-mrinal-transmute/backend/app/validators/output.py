"""Future output artifact validation hooks."""

from app.models.documents import DocumentFormat


def validate_format(filename: str, expected: DocumentFormat) -> bool:
    return filename.lower().endswith(f".{expected.value}")

