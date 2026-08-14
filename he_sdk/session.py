"""Backend-neutral local HE session."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Sequence
import uuid

from he_sdk.backends import create_backend
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
    SessionClosedError,
    UnsupportedOperationError,
)
from he_sdk.operations import OPERATION_CONTRACTS


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
            backend=self._backend.name,
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
        if metadata.backend != self._backend.name:
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
