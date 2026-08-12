"""Trusted integer BGV multiplication demo for CPU OpenFHE."""

from __future__ import annotations

import importlib
import threading
import time
from typing import Any, Sequence

from backends.openfhe_demo import _clear_openfhe_process_state


# Prime congruent to 1 modulo 32768, allowing packed BGV slots at ring
# dimension 16384. Its centered signed range is +/-2,000,175,104, which covers
# the default benchmark through 2 x 1,000,000,000 without modular wraparound.
PLAINTEXT_MODULUS = 4_000_350_209
MULTIPLICATIVE_DEPTH = 1
RING_DIMENSION = 16_384
BATCH_SIZE = 8_192


class OpenFHEBGVDemoBackend:
    """Encrypt integer vectors, multiply once, decrypt inside a demo request."""

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
                ):
                    context.Enable(feature)
                keys = context.KeyGen()
                context.EvalMultKeyGen(keys.secretKey)
                context_keygen_seconds = time.perf_counter() - started

                started = time.perf_counter()
                left_plaintext = context.MakePackedPlaintext(list(values_a))
                right_plaintext = context.MakePackedPlaintext(list(values_b))
                left = context.Encrypt(keys.publicKey, left_plaintext)
                right = context.Encrypt(keys.publicKey, right_plaintext)
                encrypt_seconds = time.perf_counter() - started

                started = time.perf_counter()
                encrypted = context.EvalMult(left, right)
                calculation_seconds = time.perf_counter() - started

                started = time.perf_counter()
                plaintext = context.Decrypt(keys.secretKey, encrypted)
                plaintext.SetLength(len(values_a))
                values = [
                    int(value)
                    for value in plaintext.GetPackedValue()[: len(values_a)]
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
