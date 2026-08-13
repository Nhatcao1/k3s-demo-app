"""Trusted integer BGV multiplication and SUM demo for CPU OpenFHE."""

from __future__ import annotations

import importlib
import threading
import time
from typing import Any, Sequence

from backends.openfhe_demo import _clear_openfhe_process_state


# Prime congruent to 1 modulo 32768, allowing packed BGV slots at ring
# dimension 16384. Its centered signed range is +/-100,000,022,528, covering
# positive SUM targets through 100 billion without modular wraparound.
PLAINTEXT_MODULUS = 200_000_045_057
MULTIPLICATIVE_DEPTH = 1
RING_DIMENSION = 16_384
BATCH_SIZE = 8_192


class OpenFHEBGVDemoBackend:
    """Encrypt integer vectors, evaluate once, decrypt inside a demo request."""

    backend_name = "cpu-openfhe-bgv-native-demo"
    _lock = threading.Lock()

    @property
    def ready(self) -> bool:
        try:
            importlib.import_module("openfhe")
        except (ImportError, OSError):
            return False
        return True

    def evaluate_multiply(
        self,
        values_a: Sequence[int],
        values_b: Sequence[int],
    ) -> dict[str, Any]:
        if not 1 <= len(values_a) <= BATCH_SIZE or len(values_a) != len(values_b):
            raise ValueError("BGV vectors must have equal length in [1, 8192]")
        return self._evaluate("multiply", values_a, values_b)

    def evaluate_sum(self, values: Sequence[int]) -> dict[str, Any]:
        if not 1 <= len(values) <= BATCH_SIZE:
            raise ValueError("BGV SUM vector length must be in [1, 8192]")
        return self._evaluate("sum", values)

    def _evaluate(
        self,
        operation: str,
        values_a: Sequence[int],
        values_b: Sequence[int] | None = None,
    ) -> dict[str, Any]:
        openfhe = importlib.import_module("openfhe")
        with self._lock:
            _clear_openfhe_process_state(openfhe)
            total_started = time.perf_counter()
            try:
                started = time.perf_counter()
                parameters = openfhe.CCParamsBGVRNS()
                parameters.SetPlaintextModulus(PLAINTEXT_MODULUS)
                parameters.SetMultiplicativeDepth(MULTIPLICATIVE_DEPTH)
                parameters.SetSecurityLevel(openfhe.HEStd_128_classic)
                parameters.SetRingDim(RING_DIMENSION)
                parameters.SetBatchSize(BATCH_SIZE)
                context = openfhe.GenCryptoContext(parameters)
                for feature in (
                    openfhe.PKE,
                    openfhe.KEYSWITCH,
                    openfhe.LEVELEDSHE,
                    openfhe.ADVANCEDSHE,
                ):
                    context.Enable(feature)
                keys = context.KeyGen()
                if operation == "multiply":
                    context.EvalMultKeyGen(keys.secretKey)
                else:
                    context.EvalSumKeyGen(keys.secretKey)
                context_keygen_seconds = time.perf_counter() - started

                started = time.perf_counter()
                left_plaintext = context.MakePackedPlaintext(list(values_a))
                left = context.Encrypt(keys.publicKey, left_plaintext)
                right = None
                if values_b is not None:
                    right_plaintext = context.MakePackedPlaintext(list(values_b))
                    right = context.Encrypt(keys.publicKey, right_plaintext)
                encrypt_seconds = time.perf_counter() - started

                started = time.perf_counter()
                encrypted = (
                    context.EvalMult(left, right)
                    if operation == "multiply"
                    else context.EvalSum(left, len(values_a))
                )
                calculation_seconds = time.perf_counter() - started

                started = time.perf_counter()
                plaintext = context.Decrypt(keys.secretKey, encrypted)
                output_length = len(values_a) if operation == "multiply" else 1
                plaintext.SetLength(output_length)
                values = [
                    int(value)
                    for value in plaintext.GetPackedValue()[:output_length]
                ]
                decrypt_seconds = time.perf_counter() - started
                return {
                    "values": values,
                    "plaintext_modulus": PLAINTEXT_MODULUS,
                    "timings": {
                        "context_keygen_seconds": context_keygen_seconds,
                        "encrypt_seconds": encrypt_seconds,
                        "calculation_seconds": calculation_seconds,
                        "decrypt_seconds": decrypt_seconds,
                        "total_seconds": time.perf_counter() - total_started,
                    },
                }
            finally:
                _clear_openfhe_process_state(openfhe)
