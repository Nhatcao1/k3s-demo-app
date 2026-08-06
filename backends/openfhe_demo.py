"""Trusted plaintext demo for quick CPU OpenFHE correctness checks."""

from __future__ import annotations

import importlib
from typing import Sequence

from common.operations import needs_right_ciphertext, needs_valid_count
from openfhe_cpu.runtime import OpenFHECPU


class OpenFHEDemoBackend:
    """Encrypt, evaluate, decrypt inside one demo-only service request."""

    backend_name = "cpu-openfhe-native-demo"

    @property
    def ready(self) -> bool:
        try:
            importlib.import_module("openfhe")
        except (ImportError, OSError):
            return False
        return True

    def evaluate(
        self,
        operation: str,
        values_a: Sequence[float],
        values_b: Sequence[float] | None,
    ) -> list[float]:
        he = OpenFHECPU()
        left = he.encrypt(values_a)
        if needs_valid_count(operation):
            encrypted = getattr(he, operation)(left, len(values_a))
            return he.decrypt(encrypted, 1)
        if operation == "square":
            return he.decrypt(he.square(left), len(values_a))
        if not needs_right_ciphertext(operation) or values_b is None:
            raise ValueError(f"invalid demo inputs for {operation}")
        right = he.encrypt(values_b)
        encrypted = getattr(he, operation)(left, right)
        return he.decrypt(encrypted, len(values_a))
