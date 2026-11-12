"""Persistent storage for rendered artifacts under the outputs volume."""

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID

from app.models.artifacts import ArtifactMetadata


class ArtifactStore:
    def __init__(self, storage_root: Path) -> None:
        self.root = storage_root / "outputs" / "artifacts"

    def save(self, metadata: ArtifactMetadata, content: bytes) -> Path:
        document_id = self._uuid(metadata.document_id)
        output_id = str(metadata.output_id)
        directory = self.root / document_id
        directory.mkdir(parents=True, exist_ok=True)
        artifact_path = directory / f"{output_id}.{metadata.target_format.value}"
        metadata_path = directory / f"{output_id}.json"
        if artifact_path.exists() or metadata_path.exists():
            raise FileExistsError("Output ID already exists.")

        artifact_temp: str | None = None
        metadata_temp: str | None = None
        try:
            with NamedTemporaryFile("wb", dir=directory, delete=False) as temp:
                temp.write(content)
                artifact_temp = temp.name
            encoded = json.dumps(metadata.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
            with NamedTemporaryFile("w", encoding="utf-8", dir=directory, delete=False) as temp:
                temp.write(encoded)
                metadata_temp = temp.name
            os.replace(artifact_temp, artifact_path)
            artifact_temp = None
            os.replace(metadata_temp, metadata_path)
            metadata_temp = None
        except OSError:
            artifact_path.unlink(missing_ok=True)
            metadata_path.unlink(missing_ok=True)
            raise
        finally:
            if artifact_temp:
                Path(artifact_temp).unlink(missing_ok=True)
            if metadata_temp:
                Path(metadata_temp).unlink(missing_ok=True)
        return artifact_path

    def get(self, document_id: str, output_id: str) -> tuple[ArtifactMetadata, Path] | None:
        normalized_document_id = self._uuid(document_id)
        normalized_output_id = self._uuid(output_id)
        directory = self.root / normalized_document_id
        metadata_path = directory / f"{normalized_output_id}.json"
        try:
            metadata = ArtifactMetadata.model_validate_json(metadata_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            raise RuntimeError("Stored output metadata could not be read.") from exc
        if metadata.document_id != normalized_document_id or str(metadata.output_id) != normalized_output_id:
            raise RuntimeError("Stored output metadata does not match its path.")
        artifact_path = directory / f"{normalized_output_id}.{metadata.target_format.value}"
        if not artifact_path.is_file():
            return None
        return metadata, artifact_path

    @staticmethod
    def _uuid(value: str) -> str:
        try:
            parsed = str(UUID(value))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("Invalid output identifier.") from exc
        if parsed != value.lower():
            raise ValueError("Invalid output identifier.")
        return parsed
