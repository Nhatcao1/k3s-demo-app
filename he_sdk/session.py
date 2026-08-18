"""Backend-neutral local HE session with transparent ciphertext chunking."""

from __future__ import annotations

from dataclasses import replace
import csv
from itertools import islice
import os
from pathlib import Path
import re
from typing import Any, Iterable, Iterator
import uuid

from he_sdk.backends import create_backend, create_backend_from_public_material
from he_sdk.backends.base import HEBackend
from he_sdk.capabilities import CapabilitySet
from he_sdk.ciphertext import (
    CiphertextChunk,
    CiphertextChunkMetadata,
    CiphertextMetadata,
    EncryptedScalar,
    EncryptedValue,
    EncryptedVector,
)
from he_sdk.config import CKKSConfig
from he_sdk.errors import (
    IncompatibleCiphertextError,
    InsufficientLevelError,
    SecretKeyUnavailableError,
    SessionClosedError,
    UnsupportedOperationError,
)
from he_sdk.operations import OPERATION_CONTRACTS


ALIGNMENT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class HESession:
    """Own one trusted local context and its cryptographic keys.

    A session presents a single-vector API.  Internally it splits logical input
    into complete ciphertext chunks, keeps their ordering metadata, and maps or
    reduces operations without exposing chunk management to notebook code.
    """

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
    def open_workspace(cls, path: str | os.PathLike[str]) -> "HESession":
        """Open a compute-only session from public persisted material."""
        from he_sdk.artifacts import workspace_open_parameters

        workspace, manifest, config = workspace_open_parameters(path)
        backend = create_backend_from_public_material(
            str(manifest.get("backend", "")),
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

    @staticmethod
    def _alignment_id(value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not ALIGNMENT_PATTERN.fullmatch(value):
            raise ValueError(
                "alignment_id must be 1-128 safe identifier characters"
            )
        return value

    def _metadata(
        self,
        *,
        valid_count: int,
        shape: tuple[int, ...],
        level: int,
        chunk_size: int,
        chunk_count: int,
        alignment_id: str | None,
    ) -> CiphertextMetadata:
        return CiphertextMetadata(
            context_id=self._backend.context_id,
            context_fingerprint=self.config.fingerprint,
            key_bundle_id=self._backend.key_bundle_id,
            scheme=self.config.scheme,
            backend=self._backend.name,
            engine_version=self._backend.engine_version,
            # Chunking does not change the packing inside each ciphertext;
            # chunk_size/chunk_count describe the logical multi-CT layout.
            packing_layout="ckks-packed-contiguous-v1",
            valid_count=valid_count,
            logical_shape=shape,
            level=level,
            scale_bits=self.config.scaling_modulus_size,
            serialization_version=self.config.serialization_version,
            chunk_size=chunk_size,
            chunk_count=chunk_count,
            alignment_id=alignment_id,
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

    def _require_depth(self, level: int, operation: str) -> None:
        if level > self.config.multiplicative_depth:
            raise InsufficientLevelError(
                f"{operation} requires level {level}, but profile allows "
                f"{self.config.multiplicative_depth}"
            )

    def encrypt(
        self,
        values: Iterable[float],
        *,
        chunk_size: int | None = None,
        alignment_id: str | None = None,
    ) -> EncryptedVector:
        """Encrypt any finite iterable as one automatically chunked vector.

        ``chunk_size`` defaults to the profile batch size.  Passing a smaller
        value is useful for tests; a larger value is rejected before the
        backend sees it.  The iterator is consumed one chunk at a time, so a
        file reader does not need to materialize the complete plaintext.
        """
        return self.encrypt_iter(
            values,
            chunk_size=chunk_size,
            alignment_id=alignment_id,
        )

    def encrypt_iter(
        self,
        values: Iterable[float],
        *,
        chunk_size: int | None = None,
        alignment_id: str | None = None,
    ) -> EncryptedVector:
        self._require_open()
        if isinstance(values, (str, bytes)):
            raise ValueError("values must be a non-empty numeric iterable")
        selected_size = self.config.batch_size if chunk_size is None else chunk_size
        if not isinstance(selected_size, int) or not (
            1 <= selected_size <= self.config.batch_size
        ):
            raise ValueError(
                f"chunk_size must be in [1, {self.config.batch_size}]"
            )
        selected_alignment = self._alignment_id(alignment_id)
        try:
            iterator = iter(values)
        except TypeError as error:
            raise ValueError("values must be a non-empty numeric iterable") from error

        chunks: list[CiphertextChunk] = []
        offset = 0
        while True:
            raw_chunk = list(islice(iterator, selected_size))
            if not raw_chunk:
                break
            # Validation remains per chunk so streaming inputs stay bounded in
            # memory while preserving the same numeric contract as SDK 0.4.
            materialized = self.config.validate_values(raw_chunk)
            chunk_metadata = CiphertextChunkMetadata(
                index=len(chunks),
                offset=offset,
                valid_count=len(materialized),
                level=0,
                scale_bits=self.config.scaling_modulus_size,
            )
            chunks.append(
                CiphertextChunk(
                    chunk_metadata,
                    self._backend.encrypt(materialized),
                )
            )
            offset += len(materialized)

        if not chunks:
            raise ValueError("values must be a non-empty numeric iterable")
        metadata = self._metadata(
            valid_count=offset,
            shape=(offset,),
            level=0,
            chunk_size=selected_size,
            chunk_count=len(chunks),
            alignment_id=selected_alignment,
        )
        return EncryptedVector(metadata, tuple(chunks), self._session_id)

    def encrypt_csv(
        self,
        path: str | os.PathLike[str],
        *,
        column: str | int,
        chunk_size: int | None = None,
        alignment_id: str | None = None,
        delimiter: str = ",",
        encoding: str = "utf-8",
        has_header: bool = True,
    ) -> EncryptedVector:
        """Stream one numeric CSV column into a chunked encrypted vector."""
        source = Path(path)

        def values() -> Iterator[float]:
            with source.open("r", encoding=encoding, newline="") as handle:
                if isinstance(column, str):
                    reader = csv.DictReader(handle, delimiter=delimiter)
                    if reader.fieldnames is None or column not in reader.fieldnames:
                        raise ValueError(f"CSV column not found: {column!r}")
                    for row_number, row in enumerate(reader, start=2):
                        try:
                            yield float(row[column])
                        except (TypeError, ValueError) as error:
                            raise ValueError(
                                f"CSV row {row_number} column {column!r} is not numeric"
                            ) from error
                    return
                if not isinstance(column, int) or column < 0:
                    raise ValueError("CSV column must be a name or non-negative index")
                reader = csv.reader(handle, delimiter=delimiter)
                if has_header:
                    next(reader, None)
                for row_number, row in enumerate(
                    reader, start=2 if has_header else 1
                ):
                    try:
                        yield float(row[column])
                    except (IndexError, ValueError) as error:
                        raise ValueError(
                            f"CSV row {row_number} column {column} is missing "
                            "or not numeric"
                        ) from error

        return self.encrypt_iter(
            values(),
            chunk_size=chunk_size,
            alignment_id=alignment_id,
        )

    def decrypt(self, value: EncryptedValue) -> list[float] | float:
        self._owned(value)
        if not getattr(self._backend, "has_secret_key", True):
            raise SecretKeyUnavailableError(
                "this compute-only session has no secret key"
            )
        if isinstance(value, EncryptedScalar):
            result = self._backend.decrypt(value._handle, 1)
            if not result:
                raise RuntimeError("backend returned an empty scalar plaintext")
            return float(result[0])

        plaintext: list[float] = []
        for chunk in value._chunks:
            plaintext.extend(
                float(item)
                for item in self._backend.decrypt(
                    chunk._handle, chunk.metadata.valid_count
                )
            )
        if len(plaintext) != value.metadata.valid_count:
            raise RuntimeError("backend returned an invalid chunked plaintext length")
        return plaintext

    def _same_layout(self, left: EncryptedVector, right: EncryptedVector) -> None:
        if left.metadata.logical_shape != right.metadata.logical_shape:
            raise IncompatibleCiphertextError(
                "binary operations require equal logical shapes"
            )
        if left.metadata.packing_layout != right.metadata.packing_layout:
            raise IncompatibleCiphertextError(
                "binary operations require equal packing layouts"
            )
        if left.metadata.chunk_size != right.metadata.chunk_size or (
            left.metadata.chunk_count != right.metadata.chunk_count
        ):
            raise IncompatibleCiphertextError(
                "binary operations require equal ciphertext chunk layouts"
            )
        if left.metadata.alignment_id != right.metadata.alignment_id:
            raise IncompatibleCiphertextError(
                "binary operations require equal alignment identifiers"
            )
        left_counts = tuple(item.metadata.valid_count for item in left._chunks)
        right_counts = tuple(item.metadata.valid_count for item in right._chunks)
        if left_counts != right_counts:
            raise IncompatibleCiphertextError(
                "binary operations require equal per-chunk valid counts"
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
        self._same_layout(left, right)
        output_level = max(left.metadata.level, right.metadata.level) + depth_cost
        self._require_depth(output_level, operation)
        function = getattr(self._backend, operation)
        chunks: list[CiphertextChunk] = []
        for left_chunk, right_chunk in zip(left._chunks, right._chunks):
            item = replace(
                left_chunk.metadata,
                level=output_level,
                checksum=None,
            )
            chunks.append(
                CiphertextChunk(
                    item,
                    function(left_chunk._handle, right_chunk._handle),
                )
            )
        metadata = replace(left.metadata, level=output_level, checksum=None)
        return EncryptedVector(metadata, tuple(chunks), self._session_id)

    def add(self, left: EncryptedVector, right: EncryptedVector) -> EncryptedVector:
        return self._binary(
            "add", left, right, depth_cost=OPERATION_CONTRACTS["add"].depth_cost
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
        output_level = value.metadata.level + OPERATION_CONTRACTS["square"].depth_cost
        self._require_depth(output_level, "square")
        chunks = tuple(
            CiphertextChunk(
                replace(chunk.metadata, level=output_level, checksum=None),
                self._backend.square(chunk._handle),
            )
            for chunk in value._chunks
        )
        return EncryptedVector(
            replace(value.metadata, level=output_level, checksum=None),
            chunks,
            self._session_id,
        )

    def _sum_chunk_handles(self, value: EncryptedVector) -> Any:
        partials = [
            self._backend.sum(chunk._handle, chunk.metadata.valid_count)
            for chunk in value._chunks
        ]
        result = partials[0]
        for partial in partials[1:]:
            result = self._backend.add(result, partial)
        return result

    def _scale_handle(self, encrypted: Any, factor: float) -> Any:
        # The public constant is encrypted with the session public key.  This
        # keeps chunk reduction backend-neutral today; a future multiply_plain
        # backend primitive may replace it as a performance optimization.
        constant = self._backend.encrypt([float(factor)])
        return self._backend.multiply(encrypted, constant)

    def _scalar_metadata(
        self, value: EncryptedVector, *, level: int
    ) -> CiphertextMetadata:
        return replace(
            value.metadata,
            logical_shape=(),
            valid_count=1,
            level=level,
            checksum=None,
            chunk_size=1,
            chunk_count=1,
        )

    def sum(self, value: EncryptedVector) -> EncryptedScalar:
        self._require_operation("sum")
        self._owned(value)
        output_level = value.metadata.level + OPERATION_CONTRACTS["sum"].depth_cost
        self._require_depth(output_level, "sum")
        return EncryptedScalar(
            self._scalar_metadata(value, level=output_level),
            self._sum_chunk_handles(value),
            self._session_id,
        )

    def mean(self, value: EncryptedVector) -> EncryptedScalar:
        self._require_operation("mean")
        self._owned(value)
        output_level = value.metadata.level + OPERATION_CONTRACTS["mean"].depth_cost
        self._require_depth(output_level, "mean")
        if value.chunk_count == 1:
            handle = self._backend.mean(
                value._chunks[0]._handle,
                value._chunks[0].metadata.valid_count,
            )
        else:
            handle = self._scale_handle(
                self._sum_chunk_handles(value),
                1.0 / value.metadata.valid_count,
            )
        return EncryptedScalar(
            self._scalar_metadata(value, level=output_level),
            handle,
            self._session_id,
        )

    def variance(self, value: EncryptedVector) -> EncryptedScalar:
        self._require_operation("variance")
        self._owned(value)
        output_level = (
            value.metadata.level + OPERATION_CONTRACTS["variance"].depth_cost
        )
        self._require_depth(output_level, "variance")
        if value.chunk_count == 1:
            handle = self._backend.variance(
                value._chunks[0]._handle,
                value._chunks[0].metadata.valid_count,
            )
        else:
            # Population variance across all chunks: E[x^2] - E[x]^2.  All
            # intermediate values remain ciphertexts and only the public count
            # is used as a scaling constant.
            encrypted_sum = self._sum_chunk_handles(value)
            squared_chunks = [
                self._backend.square(chunk._handle) for chunk in value._chunks
            ]
            squared_partials = [
                self._backend.sum(squared, chunk.metadata.valid_count)
                for squared, chunk in zip(squared_chunks, value._chunks)
            ]
            encrypted_square_sum = squared_partials[0]
            for partial in squared_partials[1:]:
                encrypted_square_sum = self._backend.add(
                    encrypted_square_sum, partial
                )
            inverse_count = 1.0 / value.metadata.valid_count
            encrypted_mean = self._scale_handle(encrypted_sum, inverse_count)
            encrypted_second_moment = self._scale_handle(
                encrypted_square_sum, inverse_count
            )
            handle = self._backend.subtract(
                encrypted_second_moment,
                self._backend.square(encrypted_mean),
            )
        return EncryptedScalar(
            self._scalar_metadata(value, level=output_level),
            handle,
            self._session_id,
        )

    def save(
        self,
        value: EncryptedValue,
        workspace: str | os.PathLike[str],
        *,
        name: str,
    ) -> Path:
        """Persist one logical value plus secretless workspace material."""
        self._require_open()
        from he_sdk.artifacts import save_ciphertext

        return save_ciphertext(self, value, workspace, name=name)

    def load(
        self,
        workspace: str | os.PathLike[str],
        *,
        name: str,
    ) -> EncryptedValue:
        """Load one compatible scalar or chunked logical vector."""
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
