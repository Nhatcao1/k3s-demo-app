"""Trusted end-to-end OpenFHE SUM used only by the comparison benchmark."""

from __future__ import annotations

import importlib
import math
import threading
import time
from typing import Any, Sequence

from openfhe_cpu.runtime import BATCH_SIZE, create_sum_context_and_keys


MAX_VALUES = 1_000_000


class OpenFHEDemoSumBackend:
    """Encrypt chunks, sum them homomorphically, then decrypt once."""

    backend_name = "cpu-openfhe-demo-sum"
    _lock = threading.Lock()

    def __init__(self, openfhe_module: Any | None = None) -> None:
        self._openfhe_module = openfhe_module

    @property
    def ready(self) -> bool:
        try:
            self._openfhe_module or importlib.import_module("openfhe")
        except (ImportError, OSError):
            return False
        return True

    def sum_values(self, values: Sequence[float]) -> dict[str, Any]:
        materialized = [float(value) for value in values]
        if not 1 <= len(materialized) <= MAX_VALUES:
            raise ValueError(f"value count must be in [1, {MAX_VALUES}]")
        if not all(math.isfinite(value) for value in materialized):
            raise ValueError("values must contain only finite numbers")

        of = self._openfhe_module or importlib.import_module("openfhe")
        with self._lock:
            total_started = time.perf_counter()
            started = time.perf_counter()
            context, keys = create_sum_context_and_keys(of)
            context_keygen_seconds = time.perf_counter() - started

            encrypted_total = None
            encrypt_seconds = 0.0
            sum_seconds = 0.0
            combine_seconds = 0.0
            chunks = 0
            for offset in range(0, len(materialized), BATCH_SIZE):
                chunk = materialized[offset : offset + BATCH_SIZE]
                started = time.perf_counter()
                plaintext = context.MakeCKKSPackedPlaintext(chunk)
                encrypted = context.Encrypt(keys.publicKey, plaintext)
                encrypt_seconds += time.perf_counter() - started

                started = time.perf_counter()
                encrypted_sum = context.EvalSum(encrypted, len(chunk))
                sum_seconds += time.perf_counter() - started

                if encrypted_total is None:
                    encrypted_total = encrypted_sum
                else:
                    started = time.perf_counter()
                    encrypted_total = context.EvalAdd(encrypted_total, encrypted_sum)
                    combine_seconds += time.perf_counter() - started
                chunks += 1

            started = time.perf_counter()
            plaintext_total = context.Decrypt(keys.secretKey, encrypted_total)
            plaintext_total.SetLength(1)
            result = float(plaintext_total.GetRealPackedValue()[0])
            decrypt_seconds = time.perf_counter() - started
            total_seconds = time.perf_counter() - total_started

        return {
            "operation": "sum",
            "values": [result],
            "value_count": len(materialized),
            "batch_size": BATCH_SIZE,
            "chunks": chunks,
            "timings": {
                "context_keygen_seconds": context_keygen_seconds,
                "encrypt_seconds": encrypt_seconds,
                "sum_seconds": sum_seconds,
                "combine_seconds": combine_seconds,
                "decrypt_seconds": decrypt_seconds,
                "total_seconds": total_seconds,
            },
        }
