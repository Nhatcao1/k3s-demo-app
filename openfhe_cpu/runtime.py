"""Operation-specific trial profiles and direct CPU OpenFHE functions.

This is the layer below the evaluator backend and HTTP API. Keep the trial
configuration here so clients do not repeat CKKS setup and key generation.
Tune these values only after the correctness benchmarks are complete.
"""

from __future__ import annotations

import importlib
import math
from dataclasses import dataclass
from typing import Any, Sequence


# Values that are shared by every current CKKS operation profile.
FIRST_MOD_SIZE = 60
RING_DIMENSION = 16384
BATCH_SIZE = 8192


@dataclass(frozen=True)
class HEParameterProfile:
    """Reviewable CPU CKKS policy for exactly one exposed operation."""

    operation: str
    operation_depth: int
    context_depth: int
    scaling_mod_size: int
    needs_multiplication_keys: bool
    needs_rotation_keys: bool


# These remain correctness-first trial values. Context depth is at least one
# because OpenFHE still needs a usable CKKS modulus chain for depth-zero
# operations. Variance receives one spare level and a larger scaling modulus
# while its level/scale behavior is being validated on the deployment server.
OPERATION_PROFILES: dict[str, HEParameterProfile] = {
    "add": HEParameterProfile("add", 0, 1, 45, False, False),
    "subtract": HEParameterProfile("subtract", 0, 1, 45, False, False),
    "multiply": HEParameterProfile("multiply", 1, 1, 50, True, False),
    "square": HEParameterProfile("square", 1, 1, 50, True, False),
    "sum": HEParameterProfile("sum", 0, 1, 45, False, True),
    "mean": HEParameterProfile("mean", 1, 1, 50, False, True),
    "variance": HEParameterProfile("variance", 2, 3, 55, True, True),
}


def get_operation_profile(operation: str) -> HEParameterProfile:
    """Return the explicit profile or reject an unsupported operation."""
    try:
        return OPERATION_PROFILES[operation]
    except KeyError as error:
        supported = ", ".join(OPERATION_PROFILES)
        raise ValueError(
            f"operation must be one of: {supported}"
        ) from error


def create_operation_context_and_keys(
    openfhe_module: Any, operation: str
) -> tuple[Any, Any]:
    """Create one operation-specific CKKS context and minimum key bundle.

    The trusted client owns the secret key. The evaluator API never sees it.
    Profiles are selected before encryption because ciphertexts and evaluation
    keys cannot be moved between incompatible CKKS contexts.
    """
    of = openfhe_module
    profile = get_operation_profile(operation)
    parameters = of.CCParamsCKKSRNS()
    parameters.SetMultiplicativeDepth(profile.context_depth)
    parameters.SetFirstModSize(FIRST_MOD_SIZE)
    parameters.SetScalingModSize(profile.scaling_mod_size)
    parameters.SetScalingTechnique(of.FLEXIBLEAUTO)
    parameters.SetSecurityLevel(of.HEStd_128_classic)
    parameters.SetRingDim(RING_DIMENSION)
    parameters.SetBatchSize(BATCH_SIZE)

    context = of.GenCryptoContext(parameters)
    for feature in (
        of.PKE,
        of.KEYSWITCH,
        of.LEVELEDSHE,
        of.ADVANCEDSHE,
    ):
        context.Enable(feature)

    keys = context.KeyGen()
    if profile.needs_multiplication_keys:
        context.EvalMultKeyGen(keys.secretKey)
    if profile.needs_rotation_keys:
        context.EvalSumKeyGen(keys.secretKey)
    return context, keys


def create_sum_context_and_keys(openfhe_module: Any) -> tuple[Any, Any]:
    """Create the SUM profile used by the large-vector comparison endpoint.

    Keep this named wrapper because the dedicated SUM backend intentionally
    has a narrower interface than the generic demo evaluator.
    """
    return create_operation_context_and_keys(openfhe_module, "sum")


def add(context: Any, left: Any, right: Any) -> Any:
    return context.EvalAdd(left, right)


def subtract(context: Any, left: Any, right: Any) -> Any:
    return context.EvalSub(left, right)


def multiply(context: Any, left: Any, right: Any) -> Any:
    return context.EvalMult(left, right)


def square(context: Any, encrypted: Any) -> Any:
    return context.EvalSquare(encrypted)


def sum_slots(context: Any, encrypted: Any, valid_count: int) -> Any:
    return context.EvalSum(encrypted, valid_count)


def mean_slots(context: Any, encrypted: Any, valid_count: int) -> Any:
    encrypted_sum = sum_slots(context, encrypted, valid_count)
    return context.EvalMult(encrypted_sum, 1.0 / valid_count)


def variance_slots(context: Any, encrypted: Any, valid_count: int) -> Any:
    """Return encrypted population variance: E[x^2] - E[x]^2."""
    inverse_count = 1.0 / valid_count
    encrypted_sum = context.EvalSum(encrypted, valid_count)
    encrypted_square = context.EvalSquare(encrypted)
    encrypted_square_sum = context.EvalSum(encrypted_square, valid_count)
    encrypted_mean = context.EvalMult(encrypted_sum, inverse_count)
    encrypted_second_moment = context.EvalMult(
        encrypted_square_sum, inverse_count
    )
    return context.EvalSub(
        encrypted_second_moment,
        context.EvalSquare(encrypted_mean),
    )


class OpenFHECPU:
    """Trusted direct client bound to one operation profile.

    This class owns a secret key and therefore belongs only in a trusted
    client or direct test. The deployed evaluator does not construct it.
    """

    def __init__(
        self, operation: str, openfhe_module: Any | None = None
    ) -> None:
        of = openfhe_module or importlib.import_module("openfhe")
        self.operation = operation
        self.profile = get_operation_profile(operation)
        self._context, self._keys = create_operation_context_and_keys(
            of, operation
        )

    def _require_operation(self, operation: str) -> None:
        if operation != self.operation:
            raise ValueError(
                f"this context uses the {self.operation} profile, not {operation}"
            )

    @staticmethod
    def _values(values: Sequence[float]) -> list[float]:
        materialized = [float(value) for value in values]
        if not 1 <= len(materialized) <= BATCH_SIZE:
            raise ValueError(f"value count must be in [1, {BATCH_SIZE}]")
        if not all(math.isfinite(value) for value in materialized):
            raise ValueError("values must not contain NaN or infinity")
        return materialized

    def encrypt(self, values: Sequence[float]) -> Any:
        materialized = self._values(values)
        plaintext = self._context.MakeCKKSPackedPlaintext(materialized)
        return self._context.Encrypt(self._keys.publicKey, plaintext)

    def decrypt(self, encrypted: Any, length: int) -> list[float]:
        if not 1 <= length <= BATCH_SIZE:
            raise ValueError(f"output length must be in [1, {BATCH_SIZE}]")
        plaintext = self._context.Decrypt(
            self._keys.secretKey,
            encrypted,
        )
        plaintext.SetLength(length)
        return [
            float(value)
            for value in plaintext.GetRealPackedValue()[:length]
        ]

    def add(self, left: Any, right: Any) -> Any:
        self._require_operation("add")
        return add(self._context, left, right)

    def subtract(self, left: Any, right: Any) -> Any:
        self._require_operation("subtract")
        return subtract(self._context, left, right)

    def multiply(self, left: Any, right: Any) -> Any:
        self._require_operation("multiply")
        return multiply(self._context, left, right)

    def square(self, encrypted: Any) -> Any:
        self._require_operation("square")
        return square(self._context, encrypted)

    def sum(self, encrypted: Any, valid_count: int) -> Any:
        self._require_operation("sum")
        if not 1 <= valid_count <= BATCH_SIZE:
            raise ValueError(f"valid_count must be in [1, {BATCH_SIZE}]")
        return sum_slots(self._context, encrypted, valid_count)

    def mean(self, encrypted: Any, valid_count: int) -> Any:
        self._require_operation("mean")
        if not 1 <= valid_count <= BATCH_SIZE:
            raise ValueError(f"valid_count must be in [1, {BATCH_SIZE}]")
        return mean_slots(self._context, encrypted, valid_count)

    def variance(self, encrypted: Any, valid_count: int) -> Any:
        self._require_operation("variance")
        if not 1 <= valid_count <= BATCH_SIZE:
            raise ValueError(f"valid_count must be in [1, {BATCH_SIZE}]")
        return variance_slots(self._context, encrypted, valid_count)
