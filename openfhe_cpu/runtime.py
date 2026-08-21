"""Fixed trial configuration and direct CPU OpenFHE functions.

This is the layer below the evaluator backend and HTTP API. Keep the trial
configuration here so clients do not repeat CKKS setup and key generation.
Tune these values only after the correctness benchmarks are complete.
"""

from __future__ import annotations

import importlib
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Sequence


# Version-1 trial defaults. These are deliberately explicit, but not claimed
# to be optimal for every future workload.
MULTIPLICATIVE_DEPTH = 3
FIRST_MOD_SIZE = 60
SCALING_MOD_SIZE = 50
RING_DIMENSION = 16384
BATCH_SIZE = 8192


def create_trial_context_and_keys(openfhe_module: Any) -> tuple[Any, Any]:
    """Create the shared trial CKKS context and client-owned key pair.

    This is intentionally one place for the current trial parameters. The
    trusted client owns the returned secret key; the evaluator API never sees
    it. These defaults are for functional development, not final tuning.
    """
    of = openfhe_module
    parameters = of.CCParamsCKKSRNS()
    parameters.SetMultiplicativeDepth(MULTIPLICATIVE_DEPTH)
    parameters.SetFirstModSize(FIRST_MOD_SIZE)
    parameters.SetScalingModSize(SCALING_MOD_SIZE)
    parameters.SetScalingTechnique(of.FLEXIBLEAUTO)
    parameters.SetSecurityLevel(of.HEStd_128_classic)
    parameters.SetRingDim(RING_DIMENSION)
    parameters.SetBatchSize(BATCH_SIZE)
    # OpenFHE 1.5 changed the PRE default from INDCPA to NOT_SET.  Select the
    # trial mode explicitly so ReKeyGen/ReEncrypt receive valid parameters.
    parameters.SetPREMode(of.INDCPA)

    context = of.GenCryptoContext(parameters)
    for feature in (
        of.PKE,
        of.KEYSWITCH,
        of.LEVELEDSHE,
        of.ADVANCEDSHE,
        # PRE is needed only at the trusted result-release boundary.  Enabling
        # it does not give the compute worker a secret or re-encryption key.
        of.PRE,
    ):
        context.Enable(feature)

    keys = context.KeyGen()
    # Multiplication/relinearization material for EvalMult.
    context.EvalMultKeyGen(keys.secretKey)
    # Rotation material for packed-slot EvalSum.
    context.EvalSumKeyGen(keys.secretKey)
    return context, keys


def create_sum_context_and_keys(openfhe_module: Any) -> tuple[Any, Any]:
    """Create the fixed trial context with only the keys required by SUM.

    The benchmark uses this narrower setup so CPU and GPU both generate one
    context, one key pair, and rotation keys per complete request.
    """
    of = openfhe_module
    parameters = of.CCParamsCKKSRNS()
    parameters.SetMultiplicativeDepth(MULTIPLICATIVE_DEPTH)
    parameters.SetFirstModSize(FIRST_MOD_SIZE)
    parameters.SetScalingModSize(SCALING_MOD_SIZE)
    parameters.SetScalingTechnique(of.FLEXIBLEAUTO)
    parameters.SetSecurityLevel(of.HEStd_128_classic)
    parameters.SetRingDim(RING_DIMENSION)
    parameters.SetBatchSize(BATCH_SIZE)

    context = of.GenCryptoContext(parameters)
    for feature in (of.PKE, of.KEYSWITCH, of.LEVELEDSHE, of.ADVANCEDSHE):
        context.Enable(feature)
    keys = context.KeyGen()
    context.EvalSumKeyGen(keys.secretKey)
    return context, keys


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
    """Trusted direct client with configured context, keys, and functions.

    This class owns a secret key and therefore belongs only in a trusted
    client or direct test. The deployed evaluator does not construct it.
    """

    def __init__(self, openfhe_module: Any | None = None) -> None:
        of = openfhe_module or importlib.import_module("openfhe")
        self._openfhe = of
        self._context, self._keys = create_trial_context_and_keys(of)

    @classmethod
    def from_public_material(
        cls, openfhe_module: Any, directory: Path
    ) -> "OpenFHECPU":
        """Load a compute-only runtime without a secret key."""
        of = openfhe_module
        context, ok = of.DeserializeCryptoContext(
            str(directory / "context.bin"), of.BINARY
        )
        if not ok:
            raise RuntimeError("could not deserialize OpenFHE context")
        public_key, ok = of.DeserializePublicKey(
            str(directory / "public-key.bin"), of.BINARY
        )
        if not ok:
            raise RuntimeError("could not deserialize OpenFHE public key")
        if not context.DeserializeEvalMultKey(
            str(directory / "multiplication-keys.bin"), of.BINARY
        ):
            raise RuntimeError("could not deserialize multiplication keys")
        if not context.DeserializeEvalAutomorphismKey(
            str(directory / "rotation-keys.bin"), of.BINARY
        ):
            raise RuntimeError("could not deserialize rotation keys")

        runtime = cls.__new__(cls)
        runtime._openfhe = of
        runtime._context = context
        runtime._keys = SimpleNamespace(
            publicKey=public_key,
            secretKey=None,
        )
        return runtime

    @property
    def has_secret_key(self) -> bool:
        return self._keys.secretKey is not None

    def export_public_material(self, directory: Path) -> None:
        """Write only material safe for a secretless compute process."""
        directory.mkdir(parents=True, exist_ok=True)
        of = self._openfhe
        if not of.SerializeToFile(
            str(directory / "context.bin"), self._context, of.BINARY
        ):
            raise RuntimeError("could not serialize OpenFHE context")
        if not of.SerializeToFile(
            str(directory / "public-key.bin"),
            self._keys.publicKey,
            of.BINARY,
        ):
            raise RuntimeError("could not serialize OpenFHE public key")
        if not self._context.SerializeEvalMultKey(
            str(directory / "multiplication-keys.bin"), of.BINARY
        ):
            raise RuntimeError("could not serialize multiplication keys")
        if not self._context.SerializeEvalAutomorphismKey(
            str(directory / "rotation-keys.bin"), of.BINARY
        ):
            raise RuntimeError("could not serialize rotation keys")

    def serialize_ciphertext(self, encrypted: Any, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not self._openfhe.SerializeToFile(
            str(path), encrypted, self._openfhe.BINARY
        ):
            raise RuntimeError(f"could not serialize ciphertext {path.name}")

    def deserialize_ciphertext(self, path: Path) -> Any:
        encrypted, ok = self._openfhe.DeserializeCiphertext(
            str(path), self._openfhe.BINARY
        )
        if not ok:
            raise RuntimeError(f"could not deserialize ciphertext {path.name}")
        return encrypted

    def serialize_public_key(self, public_key: Any, path: Path) -> None:
        """Serialize an analyst public key; this never writes secret material."""
        path.parent.mkdir(parents=True, exist_ok=True)
        if not self._openfhe.SerializeToFile(
            str(path), public_key, self._openfhe.BINARY
        ):
            raise RuntimeError(f"could not serialize public key {path.name}")

    def deserialize_public_key(self, path: Path) -> Any:
        public_key, ok = self._openfhe.DeserializePublicKey(
            str(path), self._openfhe.BINARY
        )
        if not ok:
            raise RuntimeError(f"could not deserialize public key {path.name}")
        return public_key

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
        if self._keys.secretKey is None:
            raise RuntimeError("secret key is not available in this runtime")
        plaintext = self._context.Decrypt(
            self._keys.secretKey,
            encrypted,
        )
        plaintext.SetLength(length)
        return [
            float(value)
            for value in plaintext.GetRealPackedValue()[:length]
        ]

    def create_result_recipient(self) -> tuple[Any, Any]:
        """Create an analyst key pair under the existing CKKS context.

        The analyst secret key differs from ``self._keys.secretKey``.  It
        cannot decrypt owner ciphertexts; only a ciphertext transformed by
        ReEncrypt with a matching owner-to-analyst re-key can be decrypted.
        """
        # KeyGen needs the shared context, not the owner's secret.  This lets
        # an analyst create its independent recipient key pair from a
        # secretless workspace and export only the public half to releaser.
        recipient_keys = self._context.KeyGen()
        if not recipient_keys.good():
            raise RuntimeError("could not generate analyst PRE key pair")
        return recipient_keys.publicKey, recipient_keys.secretKey

    def reencrypt_for_recipient(
        self, encrypted: Any, recipient_public_key: Any
    ) -> Any:
        """Re-encrypt one approved result; never expose the generated re-key.

        A PRE re-key is not tied to sum/mean/variance.  Keeping generation and
        use inside this release method prevents the compute plane from using
        it to transform input ciphertexts for the analyst.
        """
        if self._keys.secretKey is None:
            raise RuntimeError("owner secret key is required for PRE release")
        re_encryption_key = self._context.ReKeyGen(
            self._keys.secretKey,
            recipient_public_key,
        )
        # IND-CPA PRE uses the two-argument overload.  Passing the optional
        # public key selects an HRA-oriented path and caused native polynomial
        # parameter mismatches with this CKKS context.
        return self._context.ReEncrypt(encrypted, re_encryption_key)

    def decrypt_with_key(
        self, encrypted: Any, secret_key: Any, length: int
    ) -> list[float]:
        """Decrypt with an explicitly supplied recipient key, not owner key."""
        if not 1 <= length <= BATCH_SIZE:
            raise ValueError(f"output length must be in [1, {BATCH_SIZE}]")
        plaintext = self._context.Decrypt(secret_key, encrypted)
        plaintext.SetLength(length)
        return [
            float(value)
            for value in plaintext.GetRealPackedValue()[:length]
        ]

    def add(self, left: Any, right: Any) -> Any:
        return add(self._context, left, right)

    def subtract(self, left: Any, right: Any) -> Any:
        return subtract(self._context, left, right)

    def multiply(self, left: Any, right: Any) -> Any:
        return multiply(self._context, left, right)

    def square(self, encrypted: Any) -> Any:
        return square(self._context, encrypted)

    def sum(self, encrypted: Any, valid_count: int) -> Any:
        if not 1 <= valid_count <= BATCH_SIZE:
            raise ValueError(f"valid_count must be in [1, {BATCH_SIZE}]")
        return sum_slots(self._context, encrypted, valid_count)

    def mean(self, encrypted: Any, valid_count: int) -> Any:
        if not 1 <= valid_count <= BATCH_SIZE:
            raise ValueError(f"valid_count must be in [1, {BATCH_SIZE}]")
        return mean_slots(self._context, encrypted, valid_count)

    def variance(self, encrypted: Any, valid_count: int) -> Any:
        if not 1 <= valid_count <= BATCH_SIZE:
            raise ValueError(f"valid_count must be in [1, {BATCH_SIZE}]")
        return variance_slots(self._context, encrypted, valid_count)
