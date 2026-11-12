"""Atomic, persistent binding of client idempotency keys to request fingerprints."""

import json
import hashlib
import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID


class IdempotencyConflictError(ValueError):
    """A client key was already used for a different operation input."""


def bind_key(root: Path, document_id: str, key: str, fingerprint: str) -> None:
    try:
        normalized_id = str(UUID(document_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Invalid document ID.") from exc
    if normalized_id != document_id.lower():
        raise ValueError("Invalid document ID.")
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", key):
        raise ValueError("Invalid idempotency key.")
    key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
    path = root / ".idempotency" / normalized_id / f"{key_hash}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"fingerprint": fingerprint}, separators=(",", ":"))
    temp_name: str | None = None
    try:
        with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as temp:
            temp.write(payload)
            temp_name = temp.name
        try:
            os.link(temp_name, path)
        except FileExistsError:
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError("Stored idempotency record could not be read.") from exc
            if existing.get("fingerprint") != fingerprint:
                raise IdempotencyConflictError("The idempotency key is already bound to different request content.")
    finally:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)
