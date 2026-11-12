"""Fingerprint-addressed persistence for independent transformation plans."""

import hashlib
import json
import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from app.models.transformation import DOCX_PLAN_SCHEMA_VERSION, TransformationPlan
from app.storage.idempotency import bind_key


FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class IncompatibleStoredPlanError(RuntimeError):
    """A persisted plan uses a schema that must not be reinterpreted silently."""


class TransformationStore:
    def __init__(self, storage_root: Path) -> None:
        self.root = storage_root / "outputs" / "transformations"

    @staticmethod
    def fingerprint(payload: dict[str, Any]) -> str:
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def get(self, document_id: str, interpretation_id: str, input_fingerprint: str) -> TransformationPlan | None:
        path = self._path(document_id, interpretation_id, input_fingerprint)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("Stored transformation plan could not be read.") from exc
        return self._validate_stored_plan(raw)

    def save_if_absent(self, plan: TransformationPlan) -> TransformationPlan:
        fingerprint = plan.metadata.input_fingerprint
        path = self._path(plan.document_id, str(plan.interpretation_id), fingerprint)
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
        temp_name: str | None = None
        try:
            with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as temp_file:
                temp_file.write(encoded)
                temp_name = temp_file.name
            try:
                # Publish the complete JSON atomically without replacing a prior plan.
                os.link(temp_name, path)
            except FileExistsError:
                existing = self.get(plan.document_id, str(plan.interpretation_id), fingerprint)
                if existing is None:
                    raise RuntimeError("Transformation plan appeared concurrently but could not be read.")
                return existing
        finally:
            if temp_name:
                Path(temp_name).unlink(missing_ok=True)
        return plan

    def list_for_interpretation(self, document_id: str, interpretation_id: str) -> list[TransformationPlan]:
        directory = self._interpretation_directory(document_id, interpretation_id)
        if not directory.exists():
            return []
        return [self._read_plan(path) for path in sorted(directory.glob("*.json"))]

    def list_for_document(self, document_id: str) -> list[TransformationPlan]:
        directory = self.root / self._normalize_uuid(document_id)
        if not directory.exists():
            return []
        return [self._read_plan(path) for path in sorted(directory.glob("*/*.json"))]

    def get_by_id(self, document_id: str, plan_id: str) -> TransformationPlan | None:
        try:
            wanted = str(UUID(plan_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("Invalid plan ID.") from exc
        if wanted != plan_id.lower():
            raise ValueError("Invalid plan ID.")
        directory = self.root / self._normalize_uuid(document_id)
        if not directory.exists():
            return None
        for path in directory.glob("*/*.json"):
            plan = self.get(document_id, path.parent.name, path.stem)
            if plan is not None and str(plan.plan_id) == wanted:
                return plan
        return None

    def bind_idempotency_key(self, document_id: str, key: str, fingerprint: str) -> None:
        bind_key(self.root, document_id, key, fingerprint)

    def _read_plan(self, path: Path) -> TransformationPlan:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("Stored transformation plan could not be read.") from exc
        return self._validate_stored_plan(raw)

    @staticmethod
    def _validate_stored_plan(raw: dict[str, Any]) -> TransformationPlan:
        is_docx = raw.get("target_format") == "docx"
        schema_version = raw.get("schema_version", "1.0")
        if is_docx and schema_version != DOCX_PLAN_SCHEMA_VERSION:
            raise IncompatibleStoredPlanError(
                "This DOCX plan uses an older destination schema and cannot be read as the current plan format."
            )
        try:
            return TransformationPlan.model_validate(raw)
        except ValidationError as exc:
            if is_docx:
                raise IncompatibleStoredPlanError(
                    "This DOCX plan does not match its declared destination schema version."
                ) from exc
            raise

    def _path(self, document_id: str, interpretation_id: str, input_fingerprint: str) -> Path:
        if not FINGERPRINT_PATTERN.fullmatch(input_fingerprint):
            raise ValueError("Invalid transformation fingerprint.")
        return self._interpretation_directory(document_id, interpretation_id) / f"{input_fingerprint}.json"

    def _interpretation_directory(self, document_id: str, interpretation_id: str) -> Path:
        return self.root / self._normalize_uuid(document_id) / self._normalize_uuid(interpretation_id)

    @staticmethod
    def _normalize_uuid(value: str) -> str:
        try:
            parsed = UUID(value)
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("Invalid transformation document or interpretation ID.") from exc
        if str(parsed) != value.lower():
            raise ValueError("Invalid transformation document or interpretation ID.")
        return str(parsed)
