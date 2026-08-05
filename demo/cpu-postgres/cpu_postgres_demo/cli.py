"""CLI entry point used by the Kubernetes demo Jobs."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from .artifacts import (
    CONTEXT,
    KPI_CIPHERTEXT,
    KPI_RESULT_CIPHERTEXT,
    MULTIPLICATION_EVALUATION_KEYS,
    SALARY_CIPHERTEXT,
    SUM_CIPHERTEXT,
    SUM_EVALUATION_KEYS,
)
from .config import DemoInputs, parse_session_id
from .crypto import (
    create_initial_artifacts,
    decrypt_final_result,
    evaluate_multiply,
    evaluate_sum,
)
from .database import SessionStore


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, separators=(",", ":"), sort_keys=True), flush=True)


def initialize(inputs: DemoInputs, store: SessionStore) -> None:
    artifacts = create_initial_artifacts(
        inputs.salaries, inputs.kpi, inputs.wrap_key, inputs.session_id
    )
    store.create_session(inputs.session_id, len(inputs.salaries), artifacts)
    _print(
        {
            "command": "initialize",
            "session_id": inputs.session_id,
            "status": "INITIALIZED",
            "salary_count": len(inputs.salaries),
            "plaintext_logged": False,
            "raw_secret_key_stored": False,
        }
    )


def sum_session(session_id: str, store: SessionStore) -> None:
    result = store.compute_operation(
        session_id=session_id,
        operation="sum",
        required_status="INITIALIZED",
        completed_status="SUMMED",
        required_artifacts=(CONTEXT, SALARY_CIPHERTEXT, SUM_EVALUATION_KEYS),
        output_artifact=SUM_CIPHERTEXT,
        compute=lambda artifacts, count: evaluate_sum(artifacts, count),
    )
    _print(
        {
            "command": "sum",
            "session_id": session_id,
            "status": "SUMMED",
            "ciphertext_bytes": len(result.payload),
            "reused": result.reused,
        }
    )


def multiply_session(session_id: str, store: SessionStore) -> None:
    result = store.compute_operation(
        session_id=session_id,
        operation="multiply",
        required_status="SUMMED",
        completed_status="MULTIPLIED",
        required_artifacts=(
            CONTEXT,
            SUM_CIPHERTEXT,
            KPI_CIPHERTEXT,
            MULTIPLICATION_EVALUATION_KEYS,
        ),
        output_artifact=KPI_RESULT_CIPHERTEXT,
        compute=lambda artifacts, _count: evaluate_multiply(artifacts),
    )
    _print(
        {
            "command": "multiply",
            "session_id": session_id,
            "status": "MULTIPLIED",
            "ciphertext_bytes": len(result.payload),
            "reused": result.reused,
        }
    )


def verify_session(inputs: DemoInputs, store: SessionStore) -> None:
    artifacts = store.verification_artifacts(inputs.session_id)
    observed = decrypt_final_result(artifacts, inputs.wrap_key, inputs.session_id)
    expected = sum(inputs.salaries) * inputs.kpi
    absolute_error = abs(observed - expected)
    passed = absolute_error <= inputs.tolerance
    if passed:
        store.mark_verified(inputs.session_id)
    _print(
        {
            "command": "verify",
            "session_id": inputs.session_id,
            "status": "PASS" if passed else "FAIL",
            "absolute_error": absolute_error,
            "tolerance": inputs.tolerance,
            "decrypted_value_logged": False,
        }
    )
    if not passed:
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("initialize", "sum", "multiply", "verify", "inspect")
    )
    args = parser.parse_args()
    store = SessionStore()
    session_id = parse_session_id(os.environ)
    if args.command == "inspect":
        _print(store.inspect(session_id))
        return
    if args.command == "sum":
        sum_session(session_id, store)
        return
    if args.command == "multiply":
        multiply_session(session_id, store)
        return

    # Only the trusted initialize and verify Jobs receive the Kubernetes
    # Secret containing plaintext demo inputs and the wrapping key.
    inputs = DemoInputs.from_environment()
    if args.command == "initialize":
        initialize(inputs, store)
    else:
        verify_session(inputs, store)


if __name__ == "__main__":
    main()
