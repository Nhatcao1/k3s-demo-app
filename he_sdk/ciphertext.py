"""SDK-owned ciphertext types and compatibility metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CiphertextMetadata:
    context_id: str
    context_fingerprint: str
    key_bundle_id: str
    scheme: str
    backend: str
    engine_version: str
    packing_layout: str
    valid_count: int
    logical_shape: tuple[int, ...]
    level: int
    scale_bits: int
    serialization_version: str
    checksum: str | None = None
    # Set only for SDK reductions.  The result-release boundary uses this
    # provenance marker to allow aggregate scalars and reject input vectors.
    # It is an application policy marker, not a cryptographic proof.
    result_operation: str | None = None


@dataclass(frozen=True, repr=False)
class EncryptedVector:
    """Opaque local ciphertext containing a packed logical vector."""

    metadata: CiphertextMetadata
    _handle: Any = field(repr=False, compare=False)
    _session_id: str = field(repr=False, compare=False)

    def __repr__(self) -> str:
        return (
            "EncryptedVector("
            f"backend={self.metadata.backend!r}, "
            f"shape={self.metadata.logical_shape!r}, "
            f"context={self.metadata.context_id[:8]!r}, "
            f"level={self.metadata.level})"
        )


@dataclass(frozen=True, repr=False)
class EncryptedScalar:
    """Opaque local ciphertext whose first packed slot is the result."""

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
