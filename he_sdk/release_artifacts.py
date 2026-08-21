"""Public-key handoff and released-result loading for the PRE notebook trial."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, TYPE_CHECKING

from he_sdk.artifacts import (
    _artifact_name,
    _read_manifest,
    _sha256,
    _workspace_member,
    _workspace_path,
)
from he_sdk.ciphertext import CiphertextMetadata
from he_sdk.errors import ArtifactError
from he_sdk.result_release import (
    ALLOWED_RESULT_OPERATIONS,
    RecipientPublicKey,
    ReleasedResult,
)

if TYPE_CHECKING:
    from he_sdk.result_release import ResultRecipient
    from he_sdk.session import HESession


PUBLIC_KEY_FORMAT = "he-sdk-recipient-public-v1"
PUBLIC_KEY_MANIFEST = "recipient-public-key.json"
PUBLIC_KEY_FILE = "recipient-public-key.bin"


def _recipient_directory(path: str | os.PathLike[str]) -> Path:
    directory = Path(path).expanduser().resolve()
    if directory == Path(directory.anchor):
        raise ArtifactError("recipient public-key path must not be a filesystem root")
    return directory


def save_recipient_public_key(
    recipient: "ResultRecipient", path: str | os.PathLike[str]
) -> Path:
    """Write no secret material: one public key plus a checksummed manifest."""
    directory = _recipient_directory(path)
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.iterdir()):
        raise ArtifactError("new recipient public-key directory must be empty")

    target = directory / PUBLIC_KEY_FILE
    temporary = directory / f".{PUBLIC_KEY_FILE}.tmp"
    recipient._public_key_serializer(recipient._public_key, temporary)
    os.replace(temporary, target)
    checksum = _sha256(target)
    manifest = {
        "format_version": PUBLIC_KEY_FORMAT,
        "recipient_id": recipient.recipient_id,
        "context_id": recipient.context_id,
        "context_fingerprint": recipient.context_fingerprint,
        "backend": recipient.backend,
        "engine_version": recipient.engine_version,
        "serialization_version": recipient.serialization_version,
        "public_key": {
            "file": PUBLIC_KEY_FILE,
            "sha256": checksum,
        },
        "contains_secret_key": False,
    }
    manifest_path = directory / PUBLIC_KEY_MANIFEST
    temporary_manifest = directory / f".{PUBLIC_KEY_MANIFEST}.tmp"
    temporary_manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary_manifest, manifest_path)
    return manifest_path


def load_recipient_public_key(
    session: "HESession", path: str | os.PathLike[str]
) -> RecipientPublicKey:
    """Load and bind an analyst public key to a compatible owner session."""
    directory = _recipient_directory(path)
    manifest_path = directory / PUBLIC_KEY_MANIFEST
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ArtifactError(
            f"recipient public-key manifest not found: {manifest_path}"
        ) from error
    except (OSError, json.JSONDecodeError) as error:
        raise ArtifactError(f"recipient public-key manifest is unreadable: {error}") from error
    if not isinstance(manifest, dict) or manifest.get("format_version") != PUBLIC_KEY_FORMAT:
        raise ArtifactError("unsupported recipient public-key artifact")
    if manifest.get("contains_secret_key") is not False:
        raise ArtifactError("recipient public-key artifact must not contain a secret key")

    expected = {
        "context_id": session._backend.context_id,
        "context_fingerprint": session.config.fingerprint,
        "backend": session._backend.name,
        "engine_version": session._backend.engine_version,
        "serialization_version": session.config.serialization_version,
    }
    mismatches = [
        field for field, value in expected.items() if manifest.get(field) != value
    ]
    if mismatches:
        raise ArtifactError(
            "recipient public key is incompatible with this session: "
            + ", ".join(mismatches)
        )

    record = manifest.get("public_key")
    if not isinstance(record, dict) or record.get("file") != PUBLIC_KEY_FILE:
        raise ArtifactError("recipient public-key file record is invalid")
    target = directory / PUBLIC_KEY_FILE
    checksum = record.get("sha256")
    if not target.is_file() or not isinstance(checksum, str) or _sha256(target) != checksum:
        raise ArtifactError("recipient public key failed checksum")
    recipient_id = manifest.get("recipient_id")
    if not isinstance(recipient_id, str) or not recipient_id:
        raise ArtifactError("recipient public-key identity is missing")

    return RecipientPublicKey(
        recipient_id=recipient_id,
        context_id=str(manifest["context_id"]),
        context_fingerprint=str(manifest["context_fingerprint"]),
        backend=str(manifest["backend"]),
        engine_version=str(manifest.get("engine_version", "")),
        serialization_version=str(manifest["serialization_version"]),
        _handle=session._backend.deserialize_public_key(target),
    )


def load_released_result(
    recipient: "ResultRecipient",
    workspace_path: str | os.PathLike[str],
    *,
    name: str,
) -> ReleasedResult:
    """Load a checksummed scalar only when it targets this analyst key."""
    artifact_name = _artifact_name(name)
    workspace = _workspace_path(workspace_path)
    manifest = _read_manifest(workspace)
    expected = {
        "context_id": recipient.context_id,
        "context_fingerprint": recipient.context_fingerprint,
        "backend": recipient.backend,
        "engine_version": recipient.engine_version,
    }
    mismatches = [
        field for field, value in expected.items() if manifest.get(field) != value
    ]
    if mismatches:
        raise ArtifactError(
            "released-result workspace is incompatible with this analyst: "
            + ", ".join(mismatches)
        )
    if manifest.get("contains_plaintext") is not False:
        raise ArtifactError("released-result workspace must not contain plaintext")
    if manifest.get("contains_secret_key") is not False:
        raise ArtifactError("released-result workspace must not contain secret keys")

    ciphertexts = manifest.get("ciphertexts")
    record = ciphertexts.get(artifact_name) if isinstance(ciphertexts, dict) else None
    if not isinstance(record, dict) or record.get("kind") != "released_scalar":
        raise ArtifactError(f"released result not found: {artifact_name}")
    if record.get("recipient_id") != recipient.recipient_id:
        raise ArtifactError("released result belongs to a different analyst")

    target = _workspace_member(workspace, record.get("file"))
    checksum = record.get("sha256")
    if not target.is_file() or not isinstance(checksum, str) or _sha256(target) != checksum:
        raise ArtifactError(f"released result failed checksum: {artifact_name}")
    raw_metadata = record.get("metadata")
    if not isinstance(raw_metadata, dict):
        raise ArtifactError("released-result metadata is invalid")
    metadata_values: dict[str, Any] = dict(raw_metadata)
    metadata_values["logical_shape"] = tuple(metadata_values.get("logical_shape", ()))
    try:
        metadata = CiphertextMetadata(**metadata_values)
    except (TypeError, ValueError) as error:
        raise ArtifactError(f"released-result metadata is invalid: {error}") from error
    if metadata.checksum != checksum:
        raise ArtifactError("released-result metadata checksum failed")
    if metadata.key_bundle_id != recipient.recipient_id:
        raise ArtifactError("released-result key identity does not match analyst")
    if metadata.backend != recipient.backend:
        raise ArtifactError("released-result backend does not match analyst")
    if metadata.serialization_version != recipient.serialization_version:
        raise ArtifactError(
            "released-result serialization does not match analyst"
        )
    if metadata.logical_shape != () or metadata.valid_count != 1:
        raise ArtifactError("released result must be an encrypted scalar")
    if metadata.result_operation not in ALLOWED_RESULT_OPERATIONS:
        raise ArtifactError("released result has no approved operation provenance")

    return ReleasedResult(
        metadata=metadata,
        recipient_id=recipient.recipient_id,
        _handle=recipient._ciphertext_deserializer(target),
        _session_id=recipient._session_id,
    )
