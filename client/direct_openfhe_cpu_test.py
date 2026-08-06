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
    he = OpenFHECPU()
    left = he.encrypt(LEFT)
    right = he.encrypt(RIGHT)

    cases = {
        "add": (
            he.add(left, right),
            [a + b for a, b in zip(LEFT, RIGHT)],
            len(LEFT),
        ),
        "subtract": (
            he.subtract(left, right),
            [a - b for a, b in zip(LEFT, RIGHT)],
            len(LEFT),
        ),
        "multiply": (
            he.multiply(left, right),
            [a * b for a, b in zip(LEFT, RIGHT)],
            len(LEFT),
        ),
        "square": (
            he.square(left),
            [value * value for value in LEFT],
            len(LEFT),
        ),
        "sum": (
            he.sum(left, len(LEFT)),
            [sum(LEFT)],
            1,
        ),
        "mean": (
            he.mean(left, len(LEFT)),
            [sum(LEFT) / len(LEFT)],
            1,
        ),
    }

    for name, (encrypted, expected, output_length) in cases.items():
        observed = he.decrypt(encrypted, output_length)
        check(name, observed, expected)


if __name__ == "__main__":
    main()
