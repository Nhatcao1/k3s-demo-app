"""Demonstrate a composed HE calculation through the K3s gateway."""

from __future__ import annotations

import argparse
import json

from he_client import HEClient


INCOME = [120.0, 150.0, 180.0, 200.0]
EXPENSES = [80.0, 90.0, 110.0, 130.0]
ADJUSTMENT = [1.0, 0.9, 1.1, 1.0]
TOLERANCE = 1e-3


def expected_results() -> tuple[float, float]:
    adjusted_net = [
        (income - expense) * adjustment
        for income, expense, adjustment in zip(
            INCOME, EXPENSES, ADJUSTMENT, strict=True
        )
    ]
    total = sum(adjusted_net)
    return total, total / len(adjusted_net)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=None,
        help=(
            "HE gateway URL; defaults to HE_GATEWAY_URL or "
            "http://127.0.0.1:18082"
        ),
    )
    args = parser.parse_args()

    with HEClient(args.url, multiplicative_depth=3) as he:
        encrypted_income = he.encrypt(INCOME)
        encrypted_expenses = he.encrypt(EXPENSES)
        encrypted_adjustment = he.encrypt(ADJUSTMENT)

        encrypted_net = encrypted_income - encrypted_expenses
        encrypted_adjusted_net = encrypted_net * encrypted_adjustment
        encrypted_total = encrypted_adjusted_net.sum()
        encrypted_average = encrypted_adjusted_net.mean()

        actual_total = encrypted_total.decrypt()[0]
        actual_average = encrypted_average.decrypt()[0]

    expected_total, expected_average = expected_results()
    maximum_error = max(
        abs(actual_total - expected_total),
        abs(actual_average - expected_average),
    )
    status = "PASS" if maximum_error <= TOLERANCE else "FAIL"

    print(
        json.dumps(
            {
                "calculation": (
                    "adjusted_net = (income - expenses) * adjustment"
                ),
                "encrypted_operations": [
                    "subtract",
                    "multiply",
                    "sum",
                    "mean",
                ],
                "total": actual_total,
                "average": actual_average,
                "expected_total": expected_total,
                "expected_average": expected_average,
                "maximum_absolute_error": maximum_error,
                "openfhe_required_on_caller": False,
                "status": status,
            },
            indent=2,
        )
    )

    if status != "PASS":
        raise RuntimeError(
            f"maximum error {maximum_error} exceeds tolerance {TOLERANCE}"
        )


if __name__ == "__main__":
    main()
