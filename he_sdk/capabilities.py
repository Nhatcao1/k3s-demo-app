"""Backend capability declarations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CapabilitySet:
    backend: str
    schemes: tuple[str, ...]
    operations: tuple[str, ...]
    supports_bootstrap: bool = False
    supports_serialization: bool = False
    # Chunk orchestration lives in the core SDK and maps to the existing
    # backend primitives; it does not require a backend-native batch object.
    supports_chunking: bool = True
    supports_streaming_input: bool = True

    def supports(self, operation: str) -> bool:
        return operation in self.operations
