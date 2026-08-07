#!/usr/bin/env python3
"""Small direct CPU trial using the configured OpenFHE function layer."""

from __future__ import annotations

from openfhe_cpu import OpenFHECPU


LEFT = [1.25, -2.0, 3.5, 4.0]
RIGHT = [0.75, 5.0, -1.5, 2.0]
ABSOLUTE_TOLERANCE = 1e-3


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
    expected = {
        "add": [a + b for a, b in zip(LEFT, RIGHT)],
        "subtract": [a - b for a, b in zip(LEFT, RIGHT)],
        "multiply": [a * b for a, b in zip(LEFT, RIGHT)],
        "square": [value * value for value in LEFT],
        "sum": [sum(LEFT)],
        "mean": [sum(LEFT) / len(LEFT)],
        "variance": [
            sum(
                (value - sum(LEFT) / len(LEFT)) ** 2
                for value in LEFT
            ) / len(LEFT)
        ],
    }

    for name in expected:
        # A ciphertext belongs to the context selected for this operation.
        # Recreate context and keys instead of silently using a max-depth
        # profile for every test.
        he = OpenFHECPU(name)
        left = he.encrypt(LEFT)
        if name in ("add", "subtract", "multiply"):
            right = he.encrypt(RIGHT)
            encrypted = getattr(he, name)(left, right)
        elif name == "square":
            encrypted = he.square(left)
        else:
            encrypted = getattr(he, name)(left, len(LEFT))
        output_length = 1 if name in ("sum", "mean", "variance") else len(LEFT)
        observed = he.decrypt(encrypted, output_length)
        check(name, observed, expected[name])


if __name__ == "__main__":
    main()
