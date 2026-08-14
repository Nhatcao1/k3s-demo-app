"""Executable correctness smoke test for an installed local SDK wheel."""

from __future__ import annotations

import json
import math
import os

from he_sdk.session import HESession


LEFT = [1.25, -2.0, 3.5, 4.0]
RIGHT = [0.75, 5.0, -1.5, 2.0]
ABSOLUTE_TOLERANCE = 1e-3
RELATIVE_TOLERANCE = 1e-3


def _maximum_error(observed: list[float], expected: list[float]) -> float:
    if len(observed) != len(expected):
        raise RuntimeError(
            f"result length {len(observed)} does not match {len(expected)}"
        )
    return max(
        abs(actual - wanted)
        for actual, wanted in zip(observed, expected, strict=True)
    )


def run(backend: str = "openfhe") -> dict[str, object]:
    """Run all SDK-v1 functions and return a machine-readable result."""
    mean = sum(LEFT) / len(LEFT)
    cases: dict[str, tuple[list[float] | float, list[float]]] = {}

    with HESession.create(backend=backend) as he:
        left = he.encrypt(LEFT)
        right = he.encrypt(RIGHT)
        cases = {
            "add": (
                he.decrypt(he.add(left, right)),
                [a + b for a, b in zip(LEFT, RIGHT, strict=True)],
            ),
            "subtract": (
                he.decrypt(he.subtract(left, right)),
                [a - b for a, b in zip(LEFT, RIGHT, strict=True)],
            ),
            "multiply": (
                he.decrypt(he.multiply(left, right)),
                [a * b for a, b in zip(LEFT, RIGHT, strict=True)],
            ),
            "square": (
                he.decrypt(he.square(left)),
                [value * value for value in LEFT],
            ),
            "sum": (he.decrypt(he.sum(left)), [sum(LEFT)]),
            "mean": (he.decrypt(he.mean(left)), [mean]),
            "variance": (
                he.decrypt(he.variance(left)),
                [sum((value - mean) ** 2 for value in LEFT) / len(LEFT)],
            ),
        }

    maximum_errors: dict[str, float] = {}
    decrypted_results: dict[str, list[float]] = {}
    for name, (observed, expected) in cases.items():
        observed_values = observed if isinstance(observed, list) else [observed]
        decrypted_results[name] = [float(value) for value in observed_values]
        maximum_errors[name] = _maximum_error(observed_values, expected)
        for actual, wanted in zip(observed_values, expected, strict=True):
            if not math.isclose(
                actual,
                wanted,
                rel_tol=RELATIVE_TOLERANCE,
                abs_tol=ABSOLUTE_TOLERANCE,
            ):
                raise RuntimeError(
                    f"{name} failed: observed {actual}, expected {wanted}"
                )

    return {
        "status": "PASS",
        "backend": backend,
        "operations": list(cases),
        "decrypted_results": decrypted_results,
        "maximum_absolute_error": maximum_errors,
    }


def main() -> None:
    backend = os.getenv("HE_SDK_BACKEND", "openfhe")
    print("SDK_SMOKE_RESULT=" + json.dumps(run(backend), sort_keys=True))


if __name__ == "__main__":
    main()
