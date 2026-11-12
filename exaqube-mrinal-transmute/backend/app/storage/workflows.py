"""Persistent workflow definitions and run snapshots under the outputs volume."""

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID

from app.models.documents import WorkflowDefinition
from app.models.workflow_execution import WorkflowRun


class WorkflowStore:
    def __init__(self, storage_root: Path) -> None:
        self.root = storage_root / "outputs" / "workflows"

    def save_definition(self, workflow: WorkflowDefinition) -> None:
        directory = self._workflow_directory(workflow.id)
        directory.mkdir(parents=True, exist_ok=True)
        self._atomic_json(directory / "definition.json", workflow.model_dump(mode="json"))

    def get_definition(self, workflow_id: str) -> WorkflowDefinition | None:
        path = self._workflow_directory(workflow_id) / "definition.json"
        try:
            return WorkflowDefinition.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            raise RuntimeError("Stored workflow definition could not be read.") from exc

    def save_run(self, run: WorkflowRun) -> None:
        directory = self._workflow_directory(str(run.workflow_id)) / "runs"
        directory.mkdir(parents=True, exist_ok=True)
        self._atomic_json(directory / f"{run.run_id}.json", run.model_dump(mode="json"))

    def get_run(self, workflow_id: str, run_id: str) -> WorkflowRun | None:
        workflow = self._uuid(workflow_id, "workflow")
        run = self._uuid(run_id, "run")
        path = self.root / workflow / "runs" / f"{run}.json"
        try:
            return WorkflowRun.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            raise RuntimeError("Stored workflow run could not be read.") from exc

    def list_runs(self, workflow_id: str) -> list[WorkflowRun]:
        directory = self._workflow_directory(workflow_id) / "runs"
        if not directory.exists():
            return []
        runs = [
            WorkflowRun.model_validate_json(path.read_text(encoding="utf-8"))
            for path in directory.glob("*.json")
        ]
        return sorted(runs, key=lambda run: run.created_at, reverse=True)

    @staticmethod
    def _atomic_json(path: Path, payload: dict) -> None:
        temp_name: str | None = None
        try:
            with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as temp:
                json.dump(payload, temp, ensure_ascii=False, separators=(",", ":"))
                temp_name = temp.name
            os.replace(temp_name, path)
            temp_name = None
        finally:
            if temp_name:
                Path(temp_name).unlink(missing_ok=True)

    def _workflow_directory(self, workflow_id: str) -> Path:
        return self.root / self._uuid(workflow_id, "workflow")

    @staticmethod
    def _uuid(value: str, label: str) -> str:
        try:
            normalized = str(UUID(value))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError(f"Invalid {label} ID.") from exc
        if normalized != value.lower():
            raise ValueError(f"Invalid {label} ID.")
        return normalized
