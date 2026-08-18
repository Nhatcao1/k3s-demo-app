"""SDK-owned ciphertext types and chunk compatibility metadata.

Chunking is deliberately hidden behind :class:`EncryptedVector`.  Application
code handles one logical vector while the SDK keeps one independently
serializable ciphertext handle per complete CKKS chunk.  Native handles remain
private so backend-specific OpenFHE/FIDESlib objects never leak into the public
contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CiphertextMetadata:
    """Compatibility fields shared by every chunk in one logical value."""

    context_id: str
    context_fingerprint: str
    key_bundle_id: str
    scheme: str
    backend: str
    engine_version: str
    packing_layout: str
    # For a vector this is the logical total across all chunks.  For a scalar
    # it remains one.  Per-chunk counts live in CiphertextChunkMetadata.
    valid_count: int
    logical_shape: tuple[int, ...]
    level: int
    scale_bits: int
    serialization_version: str
    checksum: str | None = None
    chunk_size: int = 0
    chunk_count: int = 1
    # This is an assertion supplied by the data owner.  When strong alignment
    # is required it should be a digest of stable ordered record identifiers.
    alignment_id: str | None = None


@dataclass(frozen=True)
class CiphertextChunkMetadata:
    """Public, backend-neutral description of one ciphertext chunk."""

    index: int
    offset: int
    valid_count: int
    level: int
    scale_bits: int
    checksum: str | None = None


@dataclass(frozen=True, repr=False)
class CiphertextChunk:
    """Internal pairing of safe chunk metadata and an opaque native handle."""

    metadata: CiphertextChunkMetadata
    _handle: Any = field(repr=False, compare=False)

    def __repr__(self) -> str:
        return (
            "CiphertextChunk("
            f"index={self.metadata.index}, "
            f"offset={self.metadata.offset}, "
            f"valid_count={self.metadata.valid_count}, "
            f"level={self.metadata.level})"
        )


@dataclass(frozen=True, repr=False)
class EncryptedVector:
    """Opaque logical vector backed by one or more ciphertext chunks."""

    metadata: CiphertextMetadata
    _chunks: tuple[CiphertextChunk, ...] = field(repr=False, compare=False)
    _session_id: str = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        # These checks make corrupted or incorrectly reassembled chunk sets
        # fail before any HE operation pairs the wrong ciphertexts.
        if not self._chunks:
            raise ValueError("encrypted vector requires at least one chunk")
        if self.metadata.chunk_count != len(self._chunks):
            raise ValueError("encrypted vector chunk_count does not match chunks")
        if self.metadata.chunk_size < 1:
            raise ValueError("encrypted vector chunk_size must be positive")
        expected_offset = 0
        levels: set[int] = set()
        scales: set[int] = set()
        for expected_index, chunk in enumerate(self._chunks):
            item = chunk.metadata
            if item.index != expected_index:
                raise ValueError("encrypted vector chunk indices must be contiguous")
            if item.offset != expected_offset:
                raise ValueError("encrypted vector chunk offsets must be contiguous")
            if not 1 <= item.valid_count <= self.metadata.chunk_size:
                raise ValueError("encrypted vector chunk valid_count is invalid")
            if expected_index < len(self._chunks) - 1 and (
                item.valid_count != self.metadata.chunk_size
            ):
                raise ValueError("only the final ciphertext chunk may be partial")
            expected_offset += item.valid_count
            levels.add(item.level)
            scales.add(item.scale_bits)
        if expected_offset != self.metadata.valid_count:
            raise ValueError("encrypted vector chunks do not match total count")
        if self.metadata.logical_shape != (self.metadata.valid_count,):
            raise ValueError("encrypted vector logical shape is invalid")
        if levels != {self.metadata.level}:
            raise ValueError("all ciphertext chunks must have the vector level")
        if scales != {self.metadata.scale_bits}:
            raise ValueError("all ciphertext chunks must have the vector scale")

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    @property
    def chunks(self) -> tuple[CiphertextChunkMetadata, ...]:
        """Expose safe metadata, never backend-native ciphertext handles."""
        return tuple(chunk.metadata for chunk in self._chunks)

    def __repr__(self) -> str:
        return (
            "EncryptedVector("
            f"backend={self.metadata.backend!r}, "
            f"shape={self.metadata.logical_shape!r}, "
            f"chunks={self.chunk_count}, "
            f"context={self.metadata.context_id[:8]!r}, "
            f"level={self.metadata.level})"
        )


@dataclass(frozen=True, repr=False)
class EncryptedScalar:
    """Opaque ciphertext whose first packed slot is the logical result."""

    metadata: CiphertextMetadata
    _handle: Any = field(repr=False, compare=False)
    _session_id: str = field(repr=False, compare=False)

    def __repr__(self) -> str:
        return (
            "EncryptedScalar("
            f"backend={self.metadata.backend!r}, "
            f"context={self.metadata.context_id[:8]!r}, "
            f"level={self.metadata.level})"
        )


EncryptedValue = EncryptedVector | EncryptedScalar
