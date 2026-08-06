"""CLI entry point used by the Kubernetes demo Jobs."""

from __future__ import annotations

import argparse
import base64
from decimal import Decimal
import json
import os
from typing import Any

from .artifacts import (
    CONTEXT,
    KPI_CIPHERTEXT,
    KPI_RESULT_CIPHERTEXT,
    MULTIPLICATION_EVALUATION_KEYS,
    SALARY_CIPHERTEXT,
    SUM_CIPHERTEXT,
    SUM_EVALUATION_KEYS,
    WRAPPED_SECRET_KEY,
    unwrap_secret_key,
)
from .config import DemoInputs, parse_session_id, parse_wrap_key
from .crypto import (
    create_initial_artifacts,
    decrypt_result,
    evaluate_multiply,
    evaluate_sum,
)
from .database import SessionStore


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, separators=(",", ":"), sort_keys=True), flush=True)


def initialize(inputs: DemoInputs, store: SessionStore) -> None:
    expected_sum = Decimal(sum(inputs.salaries))
    expected_kpi_amount = expected_sum * inputs.kpi
    artifacts = create_initial_artifacts(
        inputs.salaries,
        float(inputs.kpi) if inputs.scheme == "ckks" else inputs.kpi_scaled,
        inputs.wrap_key,
        inputs.session_id,
        inputs.scheme,
        inputs.bgv_plaintext_modulus,
    )
    store.create_session(
        inputs.session_id,
        inputs.scheme,
        len(inputs.salaries),
        inputs.kpi_scale,
        expected_sum,
        expected_kpi_amount,
        artifacts,
    )
    _print(
        {
            "command": "initialize",
            "session_id": inputs.session_id,
            "scheme": inputs.scheme,
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


def verify_session(inputs: DemoInputs, store: SessionStore, stage: str) -> None:
    result_artifact = (
        SUM_CIPHERTEXT if stage == "sum" else KPI_RESULT_CIPHERTEXT
    )
    artifacts = store.verification_artifacts(
        inputs.session_id, result_artifact
    )
    expected_sum, expected_kpi_amount = store.expected_values(inputs.session_id)
    expected_value = expected_sum if stage == "sum" else expected_kpi_amount
    observed = decrypt_result(
        artifacts,
        result_artifact,
        inputs.wrap_key,
        inputs.session_id,
        inputs.scheme,
    )
    if inputs.scheme == "bgv":
        encoded_expected = (
            int(expected_value)
            if stage == "sum"
            else int(expected_value * inputs.kpi_scale)
        )
        passed = int(observed) == encoded_expected
        decrypted_value = (
            Decimal(int(observed))
            if stage == "sum"
            else Decimal(int(observed)) / Decimal(inputs.kpi_scale)
        )
    else:
        expected_float = float(expected_value)
        passed = abs(float(observed) - expected_float) <= (
            max(1.0, abs(expected_float)) * inputs.tolerance
        )
        decrypted_value = Decimal(str(float(observed)))
    absolute_error = abs(decrypted_value - expected_value)
    store.record_verification(
        inputs.session_id, stage, decrypted_value, absolute_error, passed
    )
    _print(
        {
            "command": f"verify-{stage}",
            "session_id": inputs.session_id,
            "scheme": inputs.scheme,
            "status": "PASS" if passed else "FAIL",
            "absolute_error": str(absolute_error),
            "tolerance": inputs.tolerance,
            "decrypted_value_logged": False,
        }
    )
    if not passed:
        raise SystemExit(1)


def show_secret_key(session_id: str, wrapping_key: bytes, store: SessionStore) -> None:
    """Print the raw serialized key only for the explicit lab command."""
    wrapped = store.artifacts(session_id, (WRAPPED_SECRET_KEY,))[WRAPPED_SECRET_KEY]
    secret_key = unwrap_secret_key(wrapped, wrapping_key, session_id)
    _print(
        {
            "command": "show-secret-key",
            "session_id": session_id,
            "secret_key_base64": base64.b64encode(secret_key).decode("ascii"),
            "warning": "lab-only raw secret key",
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "initialize",
            "sum",
            "multiply",
            "verify-sum",
            "verify-kpi",
            "inspect",
            "show-secret-key",
        ),
    )
    parser.add_argument("--unsafe", action="store_true")
    args = parser.parse_args()
    store = SessionStore()
    session_id = parse_session_id(os.environ)
    if args.command == "inspect":
        _print(store.inspect(session_id))
        return
    if args.command == "show-secret-key":
        if not args.unsafe:
            parser.error("show-secret-key requires --unsafe")
        show_secret_key(session_id, parse_wrap_key(os.environ), store)
        return
    if args.command == "sum":
        sum_session(session_id, store)
        return
    if args.command == "multiply":
        multiply_session(session_id, store)
        return

    # Only the trusted initialize and verification Jobs receive the Kubernetes
    # Secret containing plaintext demo inputs and the wrapping key.
    inputs = DemoInputs.from_environment()
    if args.command == "initialize":
        initialize(inputs, store)
    elif args.command == "verify-sum":
        verify_session(inputs, store, "sum")
    else:
        verify_session(inputs, store, "kpi")


if __name__ == "__main__":
    main()
