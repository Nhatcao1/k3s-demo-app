"""Trusted plaintext demo for quick CPU OpenFHE correctness checks."""

from __future__ import annotations

import importlib
import threading
import time
from typing import Any, Sequence

from common.operations import needs_right_ciphertext, needs_valid_count
from openfhe_cpu.runtime import OpenFHECPU


def _clear_openfhe_process_state(openfhe_module: Any) -> None:
    """Release process-global contexts and evaluation-key registries."""
    for clear_name in ("ClearEvalMultKeys", "ClearEvalAutomorphismKeys"):
        clear = getattr(openfhe_module, clear_name, None)
        if clear is not None:
            clear()
    release = getattr(openfhe_module, "ReleaseAllContexts", None)
    if release is not None:
        release()


class OpenFHEDemoBackend:
    """Encrypt, evaluate, decrypt inside one demo-only service request."""

    backend_name = "cpu-openfhe-native-demo"
    _lock = threading.Lock()

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
        openfhe = importlib.import_module("openfhe")
        with self._lock:
            # OpenFHE keeps contexts and evaluation keys in process-global
            # registries. Clear stale entries before the request and always
            # release this request's entries afterward so chunked benchmarks
            # do not accumulate hundreds of contexts.
            _clear_openfhe_process_state(openfhe)
            started = time.perf_counter()
            total_started = started
            try:
                he = OpenFHECPU(openfhe)
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
                        # Cleanup happens after this value is captured and is
                        # deliberately excluded from benchmark measurements.
                        "total_seconds": time.perf_counter() - total_started,
                    },
                }
            finally:
                _clear_openfhe_process_state(openfhe)
