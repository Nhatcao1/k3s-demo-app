"""Versioned filesystem workspace for public HE material and ciphertexts."""

from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, TYPE_CHECKING

from he_sdk.ciphertext import (
    CiphertextMetadata,
    EncryptedScalar,
    EncryptedValue,
    EncryptedVector,
)
from he_sdk.config import CKKSConfig
from he_sdk.errors import ArtifactError
from he_sdk.result_release import (
    ALLOWED_RESULT_OPERATIONS,
    ReleasedResult,
)

if TYPE_CHECKING:
    from he_sdk.session import HESession


FORMAT_VERSION = "he-sdk-workspace-v1"
MANIFEST_NAME = "manifest.json"
MATERIAL_FILES = (
    "context.bin",
    "public-key.bin",
    "multiplication-keys.bin",
    "rotation-keys.bin",
)
NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _workspace_path(path: str | os.PathLike[str]) -> Path:
    workspace = Path(path).expanduser().resolve()
    if workspace == Path(workspace.anchor):
        raise ArtifactError("workspace must not be a filesystem root")
    return workspace


def _artifact_name(name: str) -> str:
    if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name):
        raise ArtifactError(
            "artifact name must start with a letter and contain only "
            "letters, numbers, dot, underscore, or dash"
        )
    return name


def _workspace_member(workspace: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ArtifactError("workspace artifact path is missing or invalid")
    candidate = (workspace / relative).resolve()
    try:
        candidate.relative_to(workspace)
    except ValueError as error:
        raise ArtifactError("workspace artifact path escapes its root") from error
    return candidate


def _read_manifest(workspace: Path) -> dict[str, Any]:
    manifest_path = workspace / MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ArtifactError(f"workspace manifest not found: {manifest_path}") from error
    except (OSError, json.JSONDecodeError) as error:
        raise ArtifactError(f"workspace manifest is unreadable: {error}") from error
    if not isinstance(manifest, dict):
        raise ArtifactError("workspace manifest must be a JSON object")
    if manifest.get("format_version") != FORMAT_VERSION:
        raise ArtifactError(
            f"unsupported workspace format: {manifest.get('format_version')!r}"
        )
    return manifest


def _write_manifest(workspace: Path, manifest: dict[str, Any]) -> None:
    target = workspace / MANIFEST_NAME
    temporary = workspace / f".{MANIFEST_NAME}.tmp"
    temporary.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)


def _config_from_manifest(manifest: dict[str, Any]) -> CKKSConfig:
    raw = manifest.get("config")
    if not isinstance(raw, dict):
        raise ArtifactError("workspace config is missing or invalid")
    values = dict(raw)
    values["rotation_indices"] = tuple(values.get("rotation_indices", ()))
    try:
        config = CKKSConfig(**values)
    except (TypeError, ValueError) as error:
        raise ArtifactError(f"workspace config is invalid: {error}") from error
    if config.fingerprint != manifest.get("context_fingerprint"):
        raise ArtifactError("workspace config fingerprint does not match")
    return config


def initialize_workspace(
    session: "HESession", path: str | os.PathLike[str]
) -> Path:
    workspace = _workspace_path(path)
    if (workspace / MANIFEST_NAME).exists():
        validate_workspace(session, workspace)
        return workspace
    if not session.capabilities.supports_serialization:
        raise ArtifactError(
            f"backend {session.capabilities.backend!r} does not support serialization"
        )

    workspace.mkdir(parents=True, exist_ok=True)
    if any(workspace.iterdir()):
        raise ArtifactError(
            "new workspace directory must be empty when no manifest exists"
        )
    material = workspace / "material"
    ciphertexts = workspace / "ciphertexts"
    material.mkdir(exist_ok=True)
    ciphertexts.mkdir(exist_ok=True)
    session._backend.export_public_material(material)

    missing = [name for name in MATERIAL_FILES if not (material / name).is_file()]
    if missing:
        raise ArtifactError(
            "backend did not export required public material: " + ", ".join(missing)
        )
    manifest: dict[str, Any] = {
        "format_version": FORMAT_VERSION,
        "backend": session.capabilities.backend,
        "engine_version": session._backend.engine_version,
        "context_id": session._backend.context_id,
        "context_fingerprint": session.config.fingerprint,
        "key_bundle_id": session._backend.key_bundle_id,
        "config": asdict(session.config),
        "public_material": {
            name: {
                "file": f"material/{name}",
                "sha256": _sha256(material / name),
            }
            for name in MATERIAL_FILES
        },
        "ciphertexts": {},
        "contains_plaintext": False,
        "contains_secret_key": False,
    }
    _write_manifest(workspace, manifest)
    return workspace


def validate_workspace(
    session: "HESession", path: str | os.PathLike[str]
) -> dict[str, Any]:
    workspace = _workspace_path(path)
    manifest = _read_manifest(workspace)
    expected = {
        "backend": session.capabilities.backend,
        "context_id": session._backend.context_id,
        "context_fingerprint": session.config.fingerprint,
        "key_bundle_id": session._backend.key_bundle_id,
    }
    mismatches = [
        name for name, value in expected.items() if manifest.get(name) != value
    ]
    if mismatches:
        raise ArtifactError(
            "workspace is incompatible with this session: " + ", ".join(mismatches)
        )
    if manifest.get("contains_plaintext") is not False:
        raise ArtifactError("workspace must not contain plaintext")
    if manifest.get("contains_secret_key") is not False:
        raise ArtifactError("workspace must not contain a secret key")
    return manifest


def workspace_open_parameters(
    path: str | os.PathLike[str],
) -> tuple[Path, dict[str, Any], CKKSConfig]:
    workspace = _workspace_path(path)
    manifest = _read_manifest(workspace)
    if manifest.get("contains_plaintext") is not False:
        raise ArtifactError("workspace must not contain plaintext")
    if manifest.get("contains_secret_key") is not False:
        raise ArtifactError("workspace must not contain a secret key")
    config = _config_from_manifest(manifest)
    public_material = manifest.get("public_material")
    if not isinstance(public_material, dict):
        raise ArtifactError("workspace public material is missing")
    for name in MATERIAL_FILES:
        record = public_material.get(name)
        if not isinstance(record, dict):
            raise ArtifactError(f"workspace material record is missing: {name}")
        file_path = _workspace_member(workspace, record.get("file"))
        if not file_path.is_file() or _sha256(file_path) != record.get("sha256"):
            raise ArtifactError(f"workspace public material failed checksum: {name}")
    return workspace, manifest, config


def save_ciphertext(
    session: "HESession",
    value: EncryptedValue | ReleasedResult,
    path: str | os.PathLike[str],
    *,
    name: str,
) -> Path:
    if isinstance(value, ReleasedResult):
        if value._session_id != session._session_id:
            raise ArtifactError(
                "released result belongs to a different release session"
            )
        metadata = value.metadata
        if (
            metadata.context_id != session._backend.context_id
            or metadata.context_fingerprint != session.config.fingerprint
            or metadata.backend != session._backend.name
            or metadata.serialization_version
            != session.config.serialization_version
        ):
            raise ArtifactError(
                "released result is incompatible with this release session"
            )
        if metadata.key_bundle_id != value.recipient_id:
            raise ArtifactError("released result recipient identity is invalid")
        if metadata.logical_shape != () or metadata.valid_count != 1:
            raise ArtifactError("released result must be an encrypted scalar")
        if metadata.result_operation not in ALLOWED_RESULT_OPERATIONS:
            raise ArtifactError(
                "released result has no approved operation provenance"
            )
    else:
        session._owned(value)
    artifact_name = _artifact_name(name)
    workspace = initialize_workspace(session, path)
    manifest = validate_workspace(session, workspace)
    target = workspace / "ciphertexts" / f"{artifact_name}.bin"
    temporary = target.with_name(f".{target.name}.tmp")
    session._backend.serialize_ciphertext(value._handle, temporary)
    os.replace(temporary, target)
    checksum = _sha256(target)
    metadata = replace(value.metadata, checksum=checksum)
    ciphertexts = manifest.get("ciphertexts")
    if not isinstance(ciphertexts, dict):
        raise ArtifactError("workspace ciphertext index is invalid")
    ciphertexts[artifact_name] = {
        "file": f"ciphertexts/{target.name}",
        "kind": (
            "released_scalar"
            if isinstance(value, ReleasedResult)
            else "scalar"
            if isinstance(value, EncryptedScalar)
            else "vector"
        ),
        "metadata": asdict(metadata),
        "sha256": checksum,
    }
    if isinstance(value, ReleasedResult):
        ciphertexts[artifact_name]["recipient_id"] = value.recipient_id
    _write_manifest(workspace, manifest)
    return target


def load_ciphertext(
    session: "HESession",
    path: str | os.PathLike[str],
    *,
    name: str,
) -> EncryptedValue | ReleasedResult:
    artifact_name = _artifact_name(name)
    workspace = _workspace_path(path)
    manifest = validate_workspace(session, workspace)
    ciphertexts = manifest.get("ciphertexts")
    if not isinstance(ciphertexts, dict):
        raise ArtifactError("workspace ciphertext index is invalid")
    record = ciphertexts.get(artifact_name)
    if not isinstance(record, dict):
        raise ArtifactError(f"ciphertext artifact not found: {artifact_name}")
    target = _workspace_member(workspace, record.get("file"))
    checksum = record.get("sha256")
    if not target.is_file() or not isinstance(checksum, str):
        raise ArtifactError(f"ciphertext artifact is missing: {artifact_name}")
    if _sha256(target) != checksum:
        raise ArtifactError(f"ciphertext checksum failed: {artifact_name}")
    raw_metadata = record.get("metadata")
    if not isinstance(raw_metadata, dict):
        raise ArtifactError(f"ciphertext metadata is invalid: {artifact_name}")
    metadata_values = dict(raw_metadata)
    metadata_values["logical_shape"] = tuple(
        metadata_values.get("logical_shape", ())
    )
    try:
        metadata = CiphertextMetadata(**metadata_values)
    except (TypeError, ValueError) as error:
        raise ArtifactError(
            f"ciphertext metadata is invalid: {artifact_name}: {error}"
        ) from error
    if metadata.checksum != checksum:
        raise ArtifactError(f"ciphertext metadata checksum failed: {artifact_name}")
    handle = session._backend.deserialize_ciphertext(target)
    if record.get("kind") == "released_scalar":
        recipient_id = record.get("recipient_id")
        if not isinstance(recipient_id, str) or not recipient_id:
            raise ArtifactError(
                f"released-result recipient is invalid: {artifact_name}"
            )
        if metadata.key_bundle_id != recipient_id:
            raise ArtifactError(
                f"released-result key identity is invalid: {artifact_name}"
            )
        if metadata.logical_shape != () or metadata.valid_count != 1:
            raise ArtifactError(
                f"released result must be a scalar: {artifact_name}"
            )
        if metadata.result_operation not in ALLOWED_RESULT_OPERATIONS:
            raise ArtifactError(
                f"released-result operation is invalid: {artifact_name}"
            )
        return ReleasedResult(
            metadata, recipient_id, handle, session._session_id
        )
    if record.get("kind") == "scalar":
        return EncryptedScalar(metadata, handle, session._session_id)
    if record.get("kind") == "vector":
        return EncryptedVector(metadata, handle, session._session_id)
    raise ArtifactError(f"ciphertext kind is invalid: {artifact_name}")


def list_ciphertexts(path: str | os.PathLike[str]) -> tuple[str, ...]:
    workspace = _workspace_path(path)
    manifest = _read_manifest(workspace)
    ciphertexts = manifest.get("ciphertexts")
    if not isinstance(ciphertexts, dict):
        raise ArtifactError("workspace ciphertext index is invalid")
    return tuple(sorted(ciphertexts))
