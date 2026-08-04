#!/usr/bin/env python3
"""Small direct CPU trial for the four OpenFHE backend functions."""

from __future__ import annotations

import openfhe

from backends.openfhe_python import OpenFHEPythonBackend


LEFT = [1.25, -2.0, 3.5, 4.0]
RIGHT = [0.75, 5.0, -1.5, 2.0]
ABSOLUTE_TOLERANCE = 1e-3


def decrypt(
    context: object,
    secret_key: object,
    encrypted: object,
    length: int,
) -> list[float]:
    plaintext = context.Decrypt(secret_key, encrypted)
    plaintext.SetLength(length)
    return [
        float(value)
        for value in plaintext.GetRealPackedValue()[:length]
    ]


def check(name: str, observed: list[float], expected: list[float]) -> None:
    maximum_error = max(
        abs(actual - wanted)
        for actual, wanted in zip(observed, expected)
    )
    if maximum_error > ABSOLUTE_TOLERANCE:
        raise RuntimeError(f"{name} failed: max error {maximum_error}")
    print(
        f"PASS {name:8s} result={observed} "
        f"max_error={maximum_error:.3g}"
    )


def main() -> None:
    # These are simple trial defaults, not an optimized production profile.
    parameters = openfhe.CCParamsCKKSRNS()
    parameters.SetMultiplicativeDepth(1)
    parameters.SetScalingModSize(50)
    parameters.SetBatchSize(8)

    context = openfhe.GenCryptoContext(parameters)
    for feature in (
        openfhe.PKE,
        openfhe.KEYSWITCH,
        openfhe.LEVELEDSHE,
        openfhe.ADVANCEDSHE,
    ):
        context.Enable(feature)

    keys = context.KeyGen()
    context.EvalMultKeyGen(keys.secretKey)
    context.EvalSumKeyGen(keys.secretKey)

    left = context.Encrypt(
        keys.publicKey,
        context.MakeCKKSPackedPlaintext(LEFT),
    )
    right = context.Encrypt(
        keys.publicKey,
        context.MakeCKKSPackedPlaintext(RIGHT),
    )
    backend = OpenFHEPythonBackend()

    cases = {
        "add": (
            backend.add(context, left, right),
            [a + b for a, b in zip(LEFT, RIGHT)],
            len(LEFT),
        ),
        "subtract": (
            backend.subtract(context, left, right),
            [a - b for a, b in zip(LEFT, RIGHT)],
            len(LEFT),
        ),
        "multiply": (
            backend.multiply(context, left, right),
            [a * b for a, b in zip(LEFT, RIGHT)],
            len(LEFT),
        ),
        "sum": (
            backend.sum(context, left, len(LEFT)),
            [sum(LEFT)],
            1,
        ),
    }

    for name, (encrypted, expected, output_length) in cases.items():
        observed = decrypt(
            context,
            keys.secretKey,
            encrypted,
            output_length,
        )
        check(name, observed, expected)


if __name__ == "__main__":
    main()
