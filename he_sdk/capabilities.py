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

    def supports(self, operation: str) -> bool:
        return operation in self.operations
