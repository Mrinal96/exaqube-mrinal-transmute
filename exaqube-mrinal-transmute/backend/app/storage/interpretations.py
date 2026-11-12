"""Separate, fingerprint-addressed storage for multiple interpretations per document."""

import hashlib
import json
import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from uuid import UUID

from app.models.interpretation import DocumentInterpretation
from app.storage.idempotency import bind_key


FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class InterpretationStore:
    def __init__(self, storage_root: Path) -> None:
        self.root = storage_root / "outputs" / "interpretations"

    @staticmethod
    def fingerprint(payload: dict[str, Any]) -> str:
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def get(self, document_id: str, input_fingerprint: str) -> DocumentInterpretation | None:
        path = self._path(document_id, input_fingerprint)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("Stored interpretation could not be read.") from exc
        return DocumentInterpretation.model_validate(raw)

    def save_if_absent(self, interpretation: DocumentInterpretation) -> DocumentInterpretation:
        fingerprint = interpretation.metadata.input_fingerprint
        path = self._path(interpretation.document_id, fingerprint)
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(interpretation.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
        temp_name: str | None = None
        try:
            with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as temp_file:
                temp_file.write(encoded)
                temp_name = temp_file.name
            try:
                # A hard link publishes the completed file atomically without replacing
                # an interpretation already stored for the same input fingerprint.
                os.link(temp_name, path)
            except FileExistsError:
                existing = self.get(interpretation.document_id, fingerprint)
                if existing is None:
                    raise RuntimeError("Interpretation appeared concurrently but could not be read.")
                return existing
        except OSError:
            raise
        finally:
            if temp_name:
                Path(temp_name).unlink(missing_ok=True)
        return interpretation

    def list_for_document(self, document_id: str) -> list[DocumentInterpretation]:
        directory = self._document_directory(document_id)
        if not directory.exists():
            return []
        records = [
            DocumentInterpretation.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(directory.glob("*.json"))
        ]
        return records

    def get_by_id(self, document_id: str, interpretation_id: str) -> DocumentInterpretation | None:
        try:
            wanted = str(UUID(interpretation_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("Invalid interpretation ID.") from exc
        if wanted != interpretation_id.lower():
            raise ValueError("Invalid interpretation ID.")
        for path in self._document_directory(document_id).glob("*.json"):
            record = self.get(document_id, path.stem)
            if record is not None and str(record.interpretation_id) == wanted:
                return record
        return None

    def bind_idempotency_key(self, document_id: str, key: str, fingerprint: str) -> None:
        bind_key(self.root, document_id, key, fingerprint)

    def _path(self, document_id: str, input_fingerprint: str) -> Path:
        if not FINGERPRINT_PATTERN.fullmatch(input_fingerprint):
            raise ValueError("Invalid interpretation fingerprint.")
        return self._document_directory(document_id) / f"{input_fingerprint}.json"

    def _document_directory(self, document_id: str) -> Path:
        try:
            parsed = UUID(document_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("Invalid document ID.") from exc
        if str(parsed) != document_id.lower():
            raise ValueError("Invalid document ID.")
        return self.root / str(parsed)
