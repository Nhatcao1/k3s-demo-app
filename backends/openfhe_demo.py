"""Trusted plaintext demo for quick CPU OpenFHE correctness checks."""

from __future__ import annotations

import importlib
import time
from typing import Any, Sequence

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
    ) -> dict[str, Any]:
        total_started = time.perf_counter()
        started = time.perf_counter()
        he = OpenFHECPU()
        context_keygen_seconds = time.perf_counter() - started

        started = time.perf_counter()
        left = he.encrypt(values_a)
        encrypt_seconds = time.perf_counter() - started

        if needs_valid_count(operation):
            started = time.perf_counter()
            encrypted = getattr(he, operation)(left, len(values_a))
            calculation_seconds = time.perf_counter() - started
            output_length = 1
        elif operation == "square":
            started = time.perf_counter()
            encrypted = he.square(left)
            calculation_seconds = time.perf_counter() - started
            output_length = len(values_a)
        else:
            if not needs_right_ciphertext(operation) or values_b is None:
                raise ValueError(f"invalid demo inputs for {operation}")
            started = time.perf_counter()
            right = he.encrypt(values_b)
            encrypt_seconds += time.perf_counter() - started
            started = time.perf_counter()
            encrypted = getattr(he, operation)(left, right)
            calculation_seconds = time.perf_counter() - started
            output_length = len(values_a)

        started = time.perf_counter()
        values = he.decrypt(encrypted, output_length)
        decrypt_seconds = time.perf_counter() - started
        return {
            "values": values,
            "timings": {
                "context_keygen_seconds": context_keygen_seconds,
                "encrypt_seconds": encrypt_seconds,
                "calculation_seconds": calculation_seconds,
                "decrypt_seconds": decrypt_seconds,
                "total_seconds": time.perf_counter() - total_started,
            },
        }
