"""Versioned filesystem workspace for public HE material and ciphertexts.

Workspace v2 stores one manifest record for a logical value and one binary per
ciphertext chunk.  The loader retains read/write support for v1 single-
ciphertext workspaces so the chunking development branch can interoperate with
artifacts produced by the stable SDK 0.4 release.
"""

from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, TYPE_CHECKING

from he_sdk.ciphertext import (
    CiphertextChunk,
    CiphertextChunkMetadata,
    CiphertextMetadata,
    EncryptedScalar,
    EncryptedValue,
    EncryptedVector,
)
from he_sdk.config import CKKSConfig
from he_sdk.errors import ArtifactError

if TYPE_CHECKING:
    from he_sdk.session import HESession


FORMAT_VERSION = "he-sdk-workspace-v2"
LEGACY_FORMAT_VERSION = "he-sdk-workspace-v1"
SUPPORTED_FORMAT_VERSIONS = (LEGACY_FORMAT_VERSION, FORMAT_VERSION)
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
    if manifest.get("format_version") not in SUPPORTED_FORMAT_VERSIONS:
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


def _legacy_save(
    session: "HESession",
    value: EncryptedValue,
    workspace: Path,
    manifest: dict[str, Any],
    artifact_name: str,
) -> Path:
    if isinstance(value, EncryptedVector):
        if value.chunk_count != 1:
            raise ArtifactError(
                "chunked ciphertext requires a workspace-v2 directory"
            )
        handle = value._chunks[0]._handle
    else:
        handle = value._handle
    target = workspace / "ciphertexts" / f"{artifact_name}.bin"
    temporary = target.with_name(f".{target.name}.tmp")
    session._backend.serialize_ciphertext(handle, temporary)
    os.replace(temporary, target)
    checksum = _sha256(target)
    metadata = replace(value.metadata, checksum=checksum)
    # Stable SDK 0.4 does not know the v2 chunk fields.  Omitting them keeps a
    # v1 workspace writable by this branch and readable by the stable wheel.
    legacy_metadata = asdict(metadata)
    for field_name in ("chunk_size", "chunk_count", "alignment_id"):
        legacy_metadata.pop(field_name, None)
    ciphertexts = manifest.get("ciphertexts")
    if not isinstance(ciphertexts, dict):
        raise ArtifactError("workspace ciphertext index is invalid")
    ciphertexts[artifact_name] = {
        "file": f"ciphertexts/{target.name}",
        "kind": "scalar" if isinstance(value, EncryptedScalar) else "vector",
        "metadata": legacy_metadata,
        "sha256": checksum,
    }
    _write_manifest(workspace, manifest)
    return target


def save_ciphertext(
    session: "HESession",
    value: EncryptedValue,
    path: str | os.PathLike[str],
    *,
    name: str,
) -> Path:
    session._owned(value)
    artifact_name = _artifact_name(name)
    workspace = initialize_workspace(session, path)
    manifest = validate_workspace(session, workspace)
    if manifest.get("format_version") == LEGACY_FORMAT_VERSION:
        return _legacy_save(session, value, workspace, manifest, artifact_name)

    if isinstance(value, EncryptedVector):
        source_chunks = tuple(
            (chunk.metadata, chunk._handle) for chunk in value._chunks
        )
        kind = "vector"
    else:
        source_chunks = (
            (
                CiphertextChunkMetadata(
                    index=0,
                    offset=0,
                    valid_count=1,
                    level=value.metadata.level,
                    scale_bits=value.metadata.scale_bits,
                ),
                value._handle,
            ),
        )
        kind = "scalar"

    # Serialize every chunk first and publish the manifest only after all files
    # have their checksums.  A crash may leave an unreferenced file, but never a
    # manifest that declares a partially written logical vector.
    records: list[dict[str, Any]] = []
    targets: list[Path] = []
    temporaries: list[Path] = []
    try:
        for chunk_metadata, handle in source_chunks:
            suffix = (
                f".part-{chunk_metadata.index:06d}.bin"
                if kind == "vector"
                else ".bin"
            )
            target = workspace / "ciphertexts" / f"{artifact_name}{suffix}"
            temporary = target.with_name(f".{target.name}.tmp")
            session._backend.serialize_ciphertext(handle, temporary)
            os.replace(temporary, target)
            checksum = _sha256(target)
            records.append(
                {
                    "file": f"ciphertexts/{target.name}",
                    "metadata": asdict(
                        replace(chunk_metadata, checksum=checksum)
                    ),
                    "sha256": checksum,
                }
            )
            targets.append(target)
            temporaries.append(temporary)
    except BaseException:
        for temporary in temporaries:
            temporary.unlink(missing_ok=True)
        raise

    ciphertexts = manifest.get("ciphertexts")
    if not isinstance(ciphertexts, dict):
        raise ArtifactError("workspace ciphertext index is invalid")
    ciphertexts[artifact_name] = {
        "kind": kind,
        "metadata": asdict(value.metadata),
        "chunks": records,
    }
    _write_manifest(workspace, manifest)
    return targets[0]


def _metadata(raw: object, *, artifact_name: str) -> CiphertextMetadata:
    if not isinstance(raw, dict):
        raise ArtifactError(f"ciphertext metadata is invalid: {artifact_name}")
    values = dict(raw)
    values["logical_shape"] = tuple(values.get("logical_shape", ()))
    try:
        return CiphertextMetadata(**values)
    except (TypeError, ValueError) as error:
        raise ArtifactError(
            f"ciphertext metadata is invalid: {artifact_name}: {error}"
        ) from error


def _legacy_load(
    session: "HESession",
    workspace: Path,
    record: dict[str, Any],
    artifact_name: str,
) -> EncryptedValue:
    target = _workspace_member(workspace, record.get("file"))
    checksum = record.get("sha256")
    if not target.is_file() or not isinstance(checksum, str):
        raise ArtifactError(f"ciphertext artifact is missing: {artifact_name}")
    if _sha256(target) != checksum:
        raise ArtifactError(f"ciphertext artifact checksum failed: {artifact_name}")
    metadata = _metadata(record.get("metadata"), artifact_name=artifact_name)
    if metadata.checksum != checksum:
        raise ArtifactError(f"ciphertext metadata checksum failed: {artifact_name}")
    handle = session._backend.deserialize_ciphertext(target)
    if record.get("kind") == "scalar":
        return EncryptedScalar(metadata, handle, session._session_id)
    if record.get("kind") == "vector":
        upgraded = replace(
            metadata,
            chunk_size=metadata.valid_count,
            chunk_count=1,
        )
        chunk = CiphertextChunk(
            CiphertextChunkMetadata(
                index=0,
                offset=0,
                valid_count=metadata.valid_count,
                level=metadata.level,
                scale_bits=metadata.scale_bits,
                checksum=checksum,
            ),
            handle,
        )
        return EncryptedVector(upgraded, (chunk,), session._session_id)
    raise ArtifactError(f"ciphertext kind is invalid: {artifact_name}")


def load_ciphertext(
    session: "HESession",
    path: str | os.PathLike[str],
    *,
    name: str,
) -> EncryptedValue:
    artifact_name = _artifact_name(name)
    workspace = _workspace_path(path)
    manifest = validate_workspace(session, workspace)
    ciphertexts = manifest.get("ciphertexts")
    if not isinstance(ciphertexts, dict):
        raise ArtifactError("workspace ciphertext index is invalid")
    record = ciphertexts.get(artifact_name)
    if not isinstance(record, dict):
        raise ArtifactError(f"ciphertext artifact not found: {artifact_name}")
    if manifest.get("format_version") == LEGACY_FORMAT_VERSION:
        return _legacy_load(session, workspace, record, artifact_name)

    metadata = _metadata(record.get("metadata"), artifact_name=artifact_name)
    raw_chunks = record.get("chunks")
    if not isinstance(raw_chunks, list) or not raw_chunks:
        raise ArtifactError(f"ciphertext chunks are missing: {artifact_name}")
    chunks: list[CiphertextChunk] = []
    for raw_chunk in raw_chunks:
        if not isinstance(raw_chunk, dict):
            raise ArtifactError(f"ciphertext chunk is invalid: {artifact_name}")
        target = _workspace_member(workspace, raw_chunk.get("file"))
        checksum = raw_chunk.get("sha256")
        if not target.is_file() or not isinstance(checksum, str):
            raise ArtifactError(f"ciphertext chunk is missing: {artifact_name}")
        if _sha256(target) != checksum:
            raise ArtifactError(f"ciphertext chunk checksum failed: {artifact_name}")
        raw_chunk_metadata = raw_chunk.get("metadata")
        if not isinstance(raw_chunk_metadata, dict):
            raise ArtifactError(
                f"ciphertext chunk metadata is invalid: {artifact_name}"
            )
        try:
            chunk_metadata = CiphertextChunkMetadata(**raw_chunk_metadata)
        except (TypeError, ValueError) as error:
            raise ArtifactError(
                f"ciphertext chunk metadata is invalid: {artifact_name}: {error}"
            ) from error
        if chunk_metadata.checksum != checksum:
            raise ArtifactError(
                f"ciphertext chunk metadata checksum failed: {artifact_name}"
            )
        chunks.append(
            CiphertextChunk(
                chunk_metadata,
                session._backend.deserialize_ciphertext(target),
            )
        )

    kind = record.get("kind")
    if kind == "scalar":
        chunk_metadata = chunks[0].metadata if len(chunks) == 1 else None
        if (
            chunk_metadata is None
            or metadata.valid_count != 1
            or metadata.chunk_count != 1
            or metadata.chunk_size != 1
            or chunk_metadata.index != 0
            or chunk_metadata.offset != 0
            or chunk_metadata.valid_count != 1
            or chunk_metadata.level != metadata.level
            or chunk_metadata.scale_bits != metadata.scale_bits
        ):
            raise ArtifactError(f"encrypted scalar chunk layout is invalid: {name}")
        return EncryptedScalar(metadata, chunks[0]._handle, session._session_id)
    if kind == "vector":
        try:
            return EncryptedVector(metadata, tuple(chunks), session._session_id)
        except ValueError as error:
            raise ArtifactError(
                f"ciphertext chunk layout is invalid: {artifact_name}: {error}"
            ) from error
    raise ArtifactError(f"ciphertext kind is invalid: {artifact_name}")


def list_ciphertexts(path: str | os.PathLike[str]) -> tuple[str, ...]:
    workspace = _workspace_path(path)
    manifest = _read_manifest(workspace)
    ciphertexts = manifest.get("ciphertexts")
    if not isinstance(ciphertexts, dict):
        raise ArtifactError("workspace ciphertext index is invalid")
    return tuple(sorted(ciphertexts))
