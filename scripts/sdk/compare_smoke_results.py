"""Compare decrypted SDK smoke outputs produced by isolated backend jobs."""

from __future__ import annotations

import json
import math
from pathlib import Path
import sys
from typing import Any


PREFIX = "SDK_SMOKE_RESULT="
ABSOLUTE_TOLERANCE = 2e-3
RELATIVE_TOLERANCE = 2e-3


def load_result(path: str) -> dict[str, Any]:
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.startswith(PREFIX):
            value = json.loads(line[len(PREFIX):])
            if not isinstance(value, dict):
                break
            return value
    raise RuntimeError(f"{path} contains no {PREFIX} JSON result")


def compare(reference: dict[str, Any], candidate: dict[str, Any]) -> None:
    if reference.get("status") != "PASS" or candidate.get("status") != "PASS":
        raise RuntimeError("both backend smoke tests must report PASS")
    if reference.get("operations") != candidate.get("operations"):
        raise RuntimeError("backend operation lists differ")

    reference_results = reference.get("decrypted_results")
    candidate_results = candidate.get("decrypted_results")
    if not isinstance(reference_results, dict) or not isinstance(
        candidate_results, dict
    ):
        raise RuntimeError("smoke output is missing decrypted_results")

    for operation in reference["operations"]:
        expected = reference_results.get(operation)
        observed = candidate_results.get(operation)
        if not isinstance(expected, list) or not isinstance(observed, list):
            raise RuntimeError(f"{operation} result must be a list")
        if len(expected) != len(observed):
            raise RuntimeError(f"{operation} result lengths differ")
        for index, (wanted, actual) in enumerate(zip(expected, observed, strict=True)):
            if not math.isclose(
                float(actual),
                float(wanted),
                rel_tol=RELATIVE_TOLERANCE,
                abs_tol=ABSOLUTE_TOLERANCE,
            ):
                raise RuntimeError(
                    f"{operation}[{index}] differs: OpenFHE={wanted}, "
                    f"FIDES={actual}"
                )


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(
            "usage: compare_smoke_results.py OPENFHE_RESULT FIDES_RESULT"
        )
    reference = load_result(sys.argv[1])
    candidate = load_result(sys.argv[2])
    compare(reference, candidate)
    print(
        "SDK_BACKEND_EQUIVALENCE=PASS "
        f"reference={reference.get('backend')} "
        f"candidate={candidate.get('backend')}"
    )


if __name__ == "__main__":
    main()
