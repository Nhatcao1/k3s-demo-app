"""Exercise arithmetic, SUM, and MEAN through one trusted HE gateway."""

from __future__ import annotations

import argparse
import json

from he_client import HEClient


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:18082",
        help="Trusted HE gateway base URL",
    )
    parser.add_argument("--left", nargs="+", type=float, default=[1, 2, 3, 4])
    parser.add_argument(
        "--right", nargs="+", type=float, default=[10, 20, 30, 40]
    )
    parser.add_argument("--depth", type=int, default=3)
    args = parser.parse_args()

    with HEClient(args.url, multiplicative_depth=args.depth) as he:
        left = he.encrypt(args.left)
        right = he.encrypt(args.right)
        difference = left - right
        multiplied = (left + right) * right
        actual_difference = difference.decrypt()
        actual_multiplied = multiplied.decrypt()
        actual_sum = difference.sum().decrypt()[0]
        actual_mean = difference.mean().decrypt()[0]

    expected_difference = [
        left_value - right_value
        for left_value, right_value in zip(
            args.left, args.right, strict=True
        )
    ]
    expected_multiplied = [
        (left_value + right_value) * right_value
        for left_value, right_value in zip(
            args.left, args.right, strict=True
        )
    ]
    expected_sum = sum(expected_difference)
    expected_mean = expected_sum / len(expected_difference)
    errors = [
        abs(got - want)
        for got, want in zip(
            actual_difference, expected_difference, strict=True
        )
    ] + [
        abs(got - want)
        for got, want in zip(
            actual_multiplied, expected_multiplied, strict=True
        )
    ] + [
        abs(actual_sum - expected_sum),
        abs(actual_mean - expected_mean),
    ]
    maximum_error = max(errors)
    status = "PASS" if maximum_error <= 1e-4 else "FAIL"
    if status != "PASS":
        raise RuntimeError(
            f"maximum error {maximum_error} exceeds tolerance 1e-4"
        )
    print(
        json.dumps(
            {
                "operations": [
                    "subtract",
                    "add",
                    "multiply",
                    "sum",
                    "mean",
                ],
                "difference": actual_difference,
                "multiplied": actual_multiplied,
                "sum": actual_sum,
                "mean": actual_mean,
                "maximum_absolute_error": maximum_error,
                "status": status,
                "openfhe_required_on_caller": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
