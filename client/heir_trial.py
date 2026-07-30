"""Run one real HEIR-compiled CKKS function through the K3s gateway."""

from __future__ import annotations

import argparse
import json

from he_client import HEClient


INCOME = [120.0, 150.0, 180.0, 200.0]
EXPENSES = [80.0, 90.0, 110.0, 130.0]
ADJUSTMENT = [1.0, 0.9, 1.1, 1.0]
TOLERANCE = 1e-3


def expected_total() -> float:
    return sum(
        (income - expense) * adjustment
        for income, expense, adjustment in zip(
            INCOME,
            EXPENSES,
            ADJUSTMENT,
            strict=True,
        )
    )


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

    with HEClient(args.url, timeout=600.0) as he:
        result = he.adjusted_net_total(
            INCOME,
            EXPENSES,
            ADJUSTMENT,
        )

    expected = expected_total()
    actual = float(result["result"])
    absolute_error = abs(actual - expected)
    status = "PASS" if absolute_error <= TOLERANCE else "FAIL"
    output = {
        **result,
        "calculation": "SUM((income - expenses) * adjustment)",
        "expected": expected,
        "absolute_error": absolute_error,
        "tolerance": TOLERANCE,
        "status": status,
        "openfhe_or_heir_required_on_caller": False,
    }
    print(json.dumps(output, indent=2))

    if status != "PASS":
        raise RuntimeError(
            f"HEIR result error {absolute_error} exceeds {TOLERANCE}"
        )


if __name__ == "__main__":
    main()
