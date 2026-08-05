#!/usr/bin/env python3
"""Small HTTP correctness check for the native FIDESlib demo endpoint."""

from __future__ import annotations

import argparse
import json
import math
from urllib.request import Request, urlopen


CASES = (
    ("add", [12, 7, 8, 9], [1, 2, 3, 4], [13, 9, 11, 13]),
    ("subtract", [12, 7, 8, 9], [1, 2, 3, 4], [11, 5, 5, 5]),
    ("multiply", [12, 7, 8, 9], [1, 2, 3, 4], [12, 14, 24, 36]),
    ("sum", [12, 7, 8, 9], None, [36]),
)


def call(url: str, operation: str, left: list[int], right: list[int] | None) -> dict:
    payload: dict[str, object] = {"operation": operation, "values_a": left}
    if right is not None:
        payload["values_b"] = right
    request = Request(
        url.rstrip("/") + "/v1/demo/evaluate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=600) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:18080")
    args = parser.parse_args()

    failed = False
    for operation, left, right, expected in CASES:
        response = call(args.url, operation, left, right)
        actual = response.get("values")
        passed = (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(
                isinstance(value, (int, float))
                and math.isclose(float(value), wanted, rel_tol=1e-6, abs_tol=1e-6)
                for value, wanted in zip(actual, expected)
            )
        )
        failed = failed or not passed
        print(json.dumps({
            "operation": operation,
            "expected": expected,
            "actual": actual,
            "status": "PASS" if passed else "FAIL",
        }))

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
