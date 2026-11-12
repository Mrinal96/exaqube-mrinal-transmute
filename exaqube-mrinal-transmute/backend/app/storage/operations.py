"""Small persistent record of completed synchronous API operations."""

import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID

from app.models.api import OperationRecord


class OperationStore:
    def __init__(self, storage_root: Path) -> None:
        self.root = storage_root / "outputs" / "operations"

    def save(self, record: OperationRecord) -> None:
        directory = self.root / str(UUID(record.document_id))
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{record.run_id}.json"
        encoded = json.dumps(record.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
        temp_name: str | None = None
        try:
            with NamedTemporaryFile("w", encoding="utf-8", dir=directory, delete=False) as temp:
                temp.write(encoded)
                temp_name = temp.name
            Path(temp_name).replace(path)
        finally:
            if temp_name:
                Path(temp_name).unlink(missing_ok=True)
