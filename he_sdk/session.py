"""Backend-neutral local HE session."""

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
from typing import Any, Sequence
import uuid

from he_sdk.backends import create_backend, create_backend_from_public_material
from he_sdk.backends.base import HEBackend
from he_sdk.capabilities import CapabilitySet
from he_sdk.ciphertext import (
    CiphertextMetadata,
    EncryptedScalar,
    EncryptedValue,
    EncryptedVector,
)
from he_sdk.config import CKKSConfig
from he_sdk.errors import (
    IncompatibleCiphertextError,
    ResultReleaseError,
    SecretKeyUnavailableError,
    SessionClosedError,
    UnsupportedOperationError,
)
from he_sdk.operations import OPERATION_CONTRACTS
from he_sdk.result_release import (
    ALLOWED_RESULT_OPERATIONS,
    RecipientPublicKey,
    ReleasedResult,
    ResultRecipient,
)


class HESession:
    """Own one trusted local context and its cryptographic keys."""

    def __init__(self, backend: HEBackend, config: CKKSConfig) -> None:
        self._backend = backend
        self.config = config
        self._session_id = uuid.uuid4().hex
        self._closed = False

    @classmethod
    def create(
        cls,
        *,
        backend: str = "openfhe",
        config: CKKSConfig | None = None,
    ) -> "HESession":
        selected = config or CKKSConfig.profile("ckks-balanced-v1")
        return cls(create_backend(backend, selected), selected)

    @classmethod
    def from_backend(
        cls, backend: HEBackend, config: CKKSConfig | None = None
    ) -> "HESession":
        """Construct a session around a compatible adapter or test backend."""
        return cls(backend, config or CKKSConfig.profile("ckks-balanced-v1"))

    @classmethod
    def open_workspace(
        cls,
        path: str | os.PathLike[str],
        *,
        execution_backend: str | None = None,
    ) -> "HESession":
        """Open a compute-only session from public persisted material.

        ``execution_backend`` normally defaults to the backend that created
        the workspace.  A compatible accelerator adapter can be selected
        explicitly; for example, FIDES consumes the OpenFHE binary workspace
        while preserving the artifact's original cryptographic identity.
        """
        from he_sdk.artifacts import workspace_open_parameters

        workspace, manifest, config = workspace_open_parameters(path)
        artifact_backend = str(manifest.get("backend", ""))
        backend = create_backend_from_public_material(
            execution_backend or artifact_backend,
            config,
            workspace / "material",
            context_id=str(manifest.get("context_id", "")),
            key_bundle_id=str(manifest.get("key_bundle_id", "")),
        )
        return cls(backend, config)

    @property
    def capabilities(self) -> CapabilitySet:
        return self._backend.capabilities

    def _require_open(self) -> None:
        if self._closed:
            raise SessionClosedError("HE session is closed")

    def _require_operation(self, operation: str) -> None:
        self._require_open()
        if not self.capabilities.supports(operation):
            raise UnsupportedOperationError(
                f"backend {self._backend.name!r} does not support {operation!r}"
            )

    def _metadata(
        self,
        *,
        valid_count: int,
        shape: tuple[int, ...],
        level: int,
    ) -> CiphertextMetadata:
        return CiphertextMetadata(
            context_id=self._backend.context_id,
            context_fingerprint=self.config.fingerprint,
            key_bundle_id=self._backend.key_bundle_id,
            scheme=self.config.scheme,
            backend=getattr(
                self._backend, "artifact_backend", self._backend.name
            ),
            engine_version=self._backend.engine_version,
            packing_layout="ckks-packed-contiguous-v1",
            valid_count=valid_count,
            logical_shape=shape,
            level=level,
            scale_bits=self.config.scaling_modulus_size,
            serialization_version=self.config.serialization_version,
        )

    def _owned(self, value: EncryptedValue) -> None:
        self._require_open()
        if not isinstance(value, (EncryptedVector, EncryptedScalar)):
            raise IncompatibleCiphertextError(
                "operation requires an SDK EncryptedVector or EncryptedScalar"
            )
        metadata = value.metadata
        problems: list[str] = []
        if value._session_id != self._session_id:
            problems.append("session")
        if metadata.context_id != self._backend.context_id:
            problems.append("context")
        if metadata.context_fingerprint != self.config.fingerprint:
            problems.append("configuration")
        if metadata.key_bundle_id != self._backend.key_bundle_id:
            problems.append("key bundle")
        artifact_backend = getattr(
            self._backend, "artifact_backend", self._backend.name
        )
        if metadata.backend != artifact_backend:
            problems.append("backend")
        if metadata.scheme != self.config.scheme:
            problems.append("scheme")
        if metadata.serialization_version != self.config.serialization_version:
            problems.append("serialization version")
        if problems:
            raise IncompatibleCiphertextError(
                "ciphertext is incompatible with this session: "
                + ", ".join(problems)
            )

    def _binary(
        self,
        operation: str,
        left: EncryptedVector,
        right: EncryptedVector,
        *,
        depth_cost: int,
    ) -> EncryptedVector:
        self._require_operation(operation)
        self._owned(left)
        self._owned(right)
        if left.metadata.logical_shape != right.metadata.logical_shape:
            raise IncompatibleCiphertextError(
                "binary operations require equal logical shapes"
            )
        if left.metadata.packing_layout != right.metadata.packing_layout:
            raise IncompatibleCiphertextError(
                "binary operations require equal packing layouts"
            )
        level = max(left.metadata.level, right.metadata.level) + depth_cost
        self._require_depth(level, operation)
        function = getattr(self._backend, operation)
        handle = function(left._handle, right._handle)
        metadata = replace(left.metadata, level=level, checksum=None)
        return EncryptedVector(metadata, handle, self._session_id)

    def _require_depth(self, level: int, operation: str) -> None:
        if level > self.config.multiplicative_depth:
            raise IncompatibleCiphertextError(
                f"{operation} requires level {level}, but profile allows "
                f"{self.config.multiplicative_depth}"
            )

    def encrypt(self, values: Sequence[float]) -> EncryptedVector:
        self._require_open()
        materialized = self.config.validate_values(values)
        handle = self._backend.encrypt(materialized)
        metadata = self._metadata(
            valid_count=len(materialized),
            shape=(len(materialized),),
            level=0,
        )
        return EncryptedVector(metadata, handle, self._session_id)

    def decrypt(self, value: EncryptedValue) -> list[float] | float:
        self._owned(value)
        if not getattr(self._backend, "has_secret_key", True):
            raise SecretKeyUnavailableError(
                "this compute-only session has no secret key"
            )
        length = (
            1
            if isinstance(value, EncryptedScalar)
            else value.metadata.valid_count
        )
        result = self._backend.decrypt(value._handle, length)
        if isinstance(value, EncryptedScalar):
            if not result:
                raise RuntimeError("backend returned an empty scalar plaintext")
            return float(result[0])
        return [float(item) for item in result]

    def add(
        self, left: EncryptedVector, right: EncryptedVector
    ) -> EncryptedVector:
        return self._binary(
            "add",
            left,
            right,
            depth_cost=OPERATION_CONTRACTS["add"].depth_cost,
        )

    def subtract(
        self, left: EncryptedVector, right: EncryptedVector
    ) -> EncryptedVector:
        return self._binary(
            "subtract",
            left,
            right,
            depth_cost=OPERATION_CONTRACTS["subtract"].depth_cost,
        )

    def multiply(
        self, left: EncryptedVector, right: EncryptedVector
    ) -> EncryptedVector:
        return self._binary(
            "multiply",
            left,
            right,
            depth_cost=OPERATION_CONTRACTS["multiply"].depth_cost,
        )

    def square(self, value: EncryptedVector) -> EncryptedVector:
        self._require_operation("square")
        self._owned(value)
        level = value.metadata.level + OPERATION_CONTRACTS["square"].depth_cost
        self._require_depth(level, "square")
        return EncryptedVector(
            replace(value.metadata, level=level, checksum=None),
            self._backend.square(value._handle),
            self._session_id,
        )

    def _reduction(
        self, operation: str, value: EncryptedVector, *, depth_cost: int
    ) -> EncryptedScalar:
        self._require_operation(operation)
        self._owned(value)
        level = value.metadata.level + depth_cost
        self._require_depth(level, operation)
        handle = getattr(self._backend, operation)(
            value._handle, value.metadata.valid_count
        )
        metadata = replace(
            value.metadata,
            logical_shape=(),
            valid_count=1,
            level=level,
            checksum=None,
            result_operation=operation,
        )
        return EncryptedScalar(metadata, handle, self._session_id)

    def sum(self, value: EncryptedVector) -> EncryptedScalar:
        return self._reduction(
            "sum", value, depth_cost=OPERATION_CONTRACTS["sum"].depth_cost
        )

    def mean(self, value: EncryptedVector) -> EncryptedScalar:
        return self._reduction(
            "mean", value, depth_cost=OPERATION_CONTRACTS["mean"].depth_cost
        )

    def variance(self, value: EncryptedVector) -> EncryptedScalar:
        return self._reduction(
            "variance",
            value,
            depth_cost=OPERATION_CONTRACTS["variance"].depth_cost,
        )

    def create_result_recipient(self) -> ResultRecipient:
        """Create an analyst key that is distinct from the data-owner key.

        The session only needs the shared public CKKS context to generate this
        independent key pair.  Keep the returned recipient on the analyst side
        and send only ``recipient.public_key`` (or its exported artifact) to
        the owner/release authority.
        """
        self._require_open()
        if not self.capabilities.supports_proxy_re_encryption:
            raise UnsupportedOperationError(
                f"backend {self._backend.name!r} does not support proxy "
                "re-encryption"
            )
        recipient_id, public_key, secret_key = (
            self._backend.create_result_recipient()
        )
        return ResultRecipient(
            recipient_id=recipient_id,
            context_id=self._backend.context_id,
            context_fingerprint=self.config.fingerprint,
            session_id=self._session_id,
            backend=self._backend.name,
            engine_version=self._backend.engine_version,
            serialization_version=self.config.serialization_version,
            public_key=public_key,
            secret_key=secret_key,
            decryptor=self._backend.decrypt_for_recipient,
            public_key_serializer=self._backend.serialize_public_key,
            ciphertext_deserializer=self._backend.deserialize_ciphertext,
        )

    def load_recipient_public_key(
        self, path: str | os.PathLike[str]
    ) -> RecipientPublicKey:
        """Load an analyst's public-only key artifact for result release."""
        self._require_open()
        from he_sdk.release_artifacts import load_recipient_public_key

        return load_recipient_public_key(self, path)

    def reencrypt_for_recipient(
        self,
        value: EncryptedScalar,
        recipient_public_key: RecipientPublicKey,
    ) -> ReleasedResult:
        """Re-encrypt one approved aggregate to an analyst public key.

        The owner secret key remains inside this session and the generated
        re-encryption key is consumed by the backend without being returned.
        """
        self._require_open()
        if not self.capabilities.supports_proxy_re_encryption:
            raise UnsupportedOperationError(
                f"backend {self._backend.name!r} does not support proxy "
                "re-encryption"
            )
        if not isinstance(value, EncryptedScalar):
            raise ResultReleaseError(
                "only aggregate scalar results can be released to an analyst"
            )
        self._owned(value)
        if not isinstance(recipient_public_key, RecipientPublicKey):
            raise ResultReleaseError(
                "release target must be a RecipientPublicKey"
            )
        expected = {
            "context_id": self._backend.context_id,
            "context_fingerprint": self.config.fingerprint,
            "backend": self._backend.name,
            "serialization_version": self.config.serialization_version,
        }
        mismatches = [
            field
            for field, wanted in expected.items()
            if getattr(recipient_public_key, field) != wanted
        ]
        if mismatches:
            raise IncompatibleCiphertextError(
                "analyst public key is incompatible with this session: "
                + ", ".join(mismatches)
            )
        operation = value.metadata.result_operation
        if operation not in ALLOWED_RESULT_OPERATIONS:
            raise ResultReleaseError(
                "only sum, mean, and variance results can be released"
            )
        handle = self._backend.reencrypt_for_recipient(
            value._handle, recipient_public_key._handle
        )
        metadata = replace(
            value.metadata,
            key_bundle_id=recipient_public_key.recipient_id,
            checksum=None,
        )
        return ReleasedResult(
            metadata,
            recipient_public_key.recipient_id,
            handle,
            self._session_id,
        )

    def release_result(
        self,
        value: EncryptedScalar,
        *,
        to: ResultRecipient,
    ) -> ReleasedResult:
        """Re-encrypt an approved aggregate scalar to one analyst key.

        PRE itself can re-encrypt any compatible ciphertext.  These checks are
        therefore a release-policy boundary, not a cryptographic restriction
        on the re-encryption key.  Do not give that native key to compute.
        """
        if not isinstance(to, ResultRecipient):
            raise ResultReleaseError("release target must be a ResultRecipient")
        if to._session_id != self._session_id:
            raise IncompatibleCiphertextError(
                "analyst recipient belongs to a different owner session"
            )
        return self.reencrypt_for_recipient(value, to.public_key)

    def save(
        self,
        value: EncryptedValue | ReleasedResult,
        workspace: str | os.PathLike[str],
        *,
        name: str,
    ) -> Path:
        """Persist one ciphertext plus secretless workspace material."""
        self._require_open()
        from he_sdk.artifacts import save_ciphertext

        return save_ciphertext(self, value, workspace, name=name)

    def load(
        self,
        workspace: str | os.PathLike[str],
        *,
        name: str,
    ) -> EncryptedValue | ReleasedResult:
        """Load one compatible ciphertext from an SDK workspace."""
        self._require_open()
        from he_sdk.artifacts import load_ciphertext

        return load_ciphertext(self, workspace, name=name)

    def close(self) -> None:
        if self._closed:
            return
        self._backend.close()
        self._closed = True

    def __enter__(self) -> "HESession":
        self._require_open()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()
