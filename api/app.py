"""Thin secretless HTTP API for a ciphertext evaluator backend."""

from __future__ import annotations

import base64
import binascii
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import math
import os
import time
from typing import Any, Protocol

from backends.openfhe_python import OpenFHEBackendError, OpenFHEPythonBackend
from backends.openfhe_demo import OpenFHEDemoBackend
from backends.openfhe_demo_sum import OpenFHEDemoSumBackend
from common.operations import (
    OPERATIONS,
    needs_multiplication_keys,
    needs_right_ciphertext,
    needs_rotation_keys,
    needs_valid_count,
    validate_operation,
)


# This module owns HTTP transport and validation only. Keep OpenFHE function
# calls in backends/openfhe_python.py so the API contract remains easy to test
# without installing OpenFHE.
MAX_ARTIFACT_BYTES = int(os.getenv("MAX_ARTIFACT_BYTES", str(32 * 1024 * 1024)))
MAX_REQUEST_BYTES = int(os.getenv("MAX_REQUEST_BYTES", str(100 * 1024 * 1024)))
MAX_DEMO_SUM_VALUES = int(os.getenv("MAX_DEMO_SUM_VALUES", "1000000"))
MAX_DEMO_VALUES = int(os.getenv("MAX_DEMO_VALUES", "4096"))


class RequestError(ValueError):
    """An error caused by an invalid API request."""


class CiphertextEvaluator(Protocol):
    backend_name: str
    serialization: str

    @property
    def ready(self) -> bool:
        """Return whether the evaluator is available."""

    def evaluate(
        self,
        operation: str,
        context: bytes,
        ciphertext_a: bytes,
        ciphertext_b: bytes | None,
        multiplication_keys: bytes | None,
        rotation_keys: bytes | None,
        valid_count: int | None,
    ) -> bytes:
        """Return one serialized result ciphertext."""


class DemoSumEvaluator(Protocol):
    backend_name: str

    @property
    def ready(self) -> bool: ...

    def sum_values(self, values: list[float]) -> dict[str, Any]: ...


class DemoEvaluator(Protocol):
    backend_name: str

    @property
    def ready(self) -> bool: ...

    def evaluate(
        self,
        operation: str,
        values_a: list[float],
        values_b: list[float] | None,
    ) -> list[float]: ...


def _decode_artifact(payload: dict[str, Any], name: str) -> bytes:
    value = payload.get(name)
    if not isinstance(value, str) or not value:
        raise RequestError(f"{name} must be a non-empty base64 string")
    maximum_encoded_length = 4 * ((MAX_ARTIFACT_BYTES + 2) // 3)
    if len(value) > maximum_encoded_length:
        raise RequestError(f"{name} exceeds the artifact size limit")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as error:
        raise RequestError(f"{name} is not valid base64") from error
    if not decoded:
        raise RequestError(f"{name} decodes to an empty artifact")
    if len(decoded) > MAX_ARTIFACT_BYTES:
        raise RequestError(f"{name} exceeds the artifact size limit")
    return decoded


def evaluate_request(
    payload: Any,
    evaluator: CiphertextEvaluator,
) -> dict[str, Any]:
    """Validate encrypted inputs, call the backend, and encode its response.

    Plaintext and secret keys are intentionally absent from the accepted
    request fields. Add new function-specific request rules in
    common/operations.py and here before exposing a new backend method.
    """
    if not isinstance(payload, dict):
        raise RequestError("request body must be a JSON object")
    allowed = {
        "operation",
        "context",
        "ciphertext_a",
        "ciphertext_b",
        "evaluation_keys",
        "multiplication_keys",
        "rotation_keys",
        "valid_count",
        "request_id",
    }
    unexpected = sorted(set(payload) - allowed)
    if unexpected:
        raise RequestError(f"unexpected fields: {', '.join(unexpected)}")

    try:
        operation = validate_operation(payload.get("operation"))
    except ValueError as error:
        raise RequestError(str(error)) from error

    request_id = payload.get("request_id")
    if request_id is not None and (
        not isinstance(request_id, str) or not request_id or len(request_id) > 128
    ):
        raise RequestError(
            "request_id must be a non-empty string of at most 128 characters"
        )

    context = _decode_artifact(payload, "context")
    ciphertext_a = _decode_artifact(payload, "ciphertext_a")

    ciphertext_b = None
    if needs_right_ciphertext(operation):
        ciphertext_b = _decode_artifact(payload, "ciphertext_b")
    elif "ciphertext_b" in payload:
        raise RequestError(f"{operation} does not accept ciphertext_b")

    key_fields = {
        name for name in (
            "evaluation_keys", "multiplication_keys", "rotation_keys"
        ) if name in payload
    }
    multiplication_keys = None
    rotation_keys = None
    if operation == "variance":
        if "evaluation_keys" in key_fields:
            raise RequestError(
                "variance requires separate multiplication_keys and rotation_keys"
            )
        multiplication_keys = _decode_artifact(payload, "multiplication_keys")
        rotation_keys = _decode_artifact(payload, "rotation_keys")
    elif needs_multiplication_keys(operation):
        if key_fields == {"evaluation_keys"}:
            multiplication_keys = _decode_artifact(payload, "evaluation_keys")
        elif key_fields == {"multiplication_keys"}:
            multiplication_keys = _decode_artifact(payload, "multiplication_keys")
        else:
            raise RequestError(
                f"{operation} requires exactly one of evaluation_keys or "
                "multiplication_keys"
            )
    elif needs_rotation_keys(operation):
        if key_fields == {"evaluation_keys"}:
            rotation_keys = _decode_artifact(payload, "evaluation_keys")
        elif key_fields == {"rotation_keys"}:
            rotation_keys = _decode_artifact(payload, "rotation_keys")
        else:
            raise RequestError(
                f"{operation} requires exactly one of evaluation_keys or rotation_keys"
            )
    elif key_fields:
        raise RequestError(f"{operation} does not accept evaluation keys")

    valid_count = payload.get("valid_count")
    if needs_valid_count(operation):
        if (
            isinstance(valid_count, bool)
            or not isinstance(valid_count, int)
            or valid_count < 1
        ):
            raise RequestError(
                f"valid_count must be a positive integer for {operation}"
            )
    elif "valid_count" in payload:
        raise RequestError(f"{operation} does not accept valid_count")

    # This timer covers the complete backend boundary, including OpenFHE
    # deserialization, evaluation, and result serialization.
    started = time.perf_counter()
    try:
        result = evaluator.evaluate(
            operation,
            context,
            ciphertext_a,
            ciphertext_b,
            multiplication_keys,
            rotation_keys,
            valid_count,
        )
    except OpenFHEBackendError as error:
        raise RequestError(str(error)) from error

    response: dict[str, Any] = {
        "operation": operation,
        "backend": evaluator.backend_name,
        "ciphertext": base64.b64encode(result).decode("ascii"),
        "evaluation_seconds": time.perf_counter() - started,
    }
    if request_id is not None:
        response["request_id"] = request_id
    return response


def evaluate_demo_sum_request(
    payload: Any, evaluator: DemoSumEvaluator
) -> dict[str, Any]:
    """Run the trusted plaintext benchmark path, separate from /v1/evaluate."""
    if not isinstance(payload, dict):
        raise RequestError("request body must be a JSON object")
    unexpected = sorted(set(payload) - {"values", "request_id"})
    if unexpected:
        raise RequestError(f"unexpected fields: {', '.join(unexpected)}")
    values = payload.get("values")
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_DEMO_SUM_VALUES:
        raise RequestError(
            f"values must contain between 1 and {MAX_DEMO_SUM_VALUES} numbers"
        )
    materialized: list[float] = []
    for value in values:
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
        ):
            raise RequestError("values must contain only finite numbers")
        materialized.append(float(value))
    request_id = payload.get("request_id")
    if request_id is not None and (
        not isinstance(request_id, str) or not request_id or len(request_id) > 128
    ):
        raise RequestError("request_id must be a non-empty string of at most 128 characters")
    response = evaluator.sum_values(materialized)
    response["backend"] = evaluator.backend_name
    response["demo_trust_model"] = "plaintext enters the CPU service"
    if request_id is not None:
        response["request_id"] = request_id
    return response


def _demo_values(payload: dict[str, Any], name: str) -> list[float]:
    values = payload.get(name)
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_DEMO_VALUES:
        raise RequestError(
            f"{name} must contain between 1 and {MAX_DEMO_VALUES} numbers"
        )
    result: list[float] = []
    for value in values:
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
        ):
            raise RequestError(f"{name} must contain only finite numbers")
        result.append(float(value))
    return result


def evaluate_demo_request(
    payload: Any, evaluator: DemoEvaluator
) -> dict[str, Any]:
    """Run one plaintext-in demo through real OpenFHE encryption and HE math."""
    if not isinstance(payload, dict):
        raise RequestError("request body must be a JSON object")
    unexpected = sorted(
        set(payload) - {"operation", "values_a", "values_b", "request_id"}
    )
    if unexpected:
        raise RequestError(f"unexpected fields: {', '.join(unexpected)}")
    try:
        operation = validate_operation(payload.get("operation"))
    except ValueError as error:
        raise RequestError(str(error)) from error
    values_a = _demo_values(payload, "values_a")
    values_b = None
    if needs_right_ciphertext(operation):
        values_b = _demo_values(payload, "values_b")
        if len(values_a) != len(values_b):
            raise RequestError("values_a and values_b must have equal length")
    elif "values_b" in payload:
        raise RequestError(f"{operation} does not accept values_b")
    request_id = payload.get("request_id")
    if request_id is not None and (
        not isinstance(request_id, str) or not request_id or len(request_id) > 128
    ):
        raise RequestError(
            "request_id must be a non-empty string of at most 128 characters"
        )
    started = time.perf_counter()
    values = evaluator.evaluate(operation, values_a, values_b)
    response: dict[str, Any] = {
        "operation": operation,
        "backend": evaluator.backend_name,
        "values": values,
        "evaluation_seconds": time.perf_counter() - started,
        "demo_trust_model": "plaintext enters the CPU service",
    }
    if request_id is not None:
        response["request_id"] = request_id
    return response


def make_handler(
    evaluator: CiphertextEvaluator,
    demo_evaluator: DemoEvaluator,
    demo_sum_evaluator: DemoSumEvaluator,
) -> type[BaseHTTPRequestHandler]:
    """Create a request handler bound to one evaluator."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "he-evaluator/0.2"

        def log_message(self, message: str, *args: Any) -> None:
            # The standard log contains method/path/status, never request bodies.
            super().log_message(message, *args)

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/healthz":
                self._send_json(200, {"status": "ok"})
            elif self.path == "/readyz":
                ready = (
                    evaluator.ready and demo_evaluator.ready
                    and demo_sum_evaluator.ready
                )
                status = 200 if ready else 503
                self._send_json(
                    status,
                    {"status": "ready" if ready else "not_ready"},
                )
            elif self.path == "/v1/capabilities":
                self._send_json(
                    200,
                    {
                        "operations": list(OPERATIONS),
                        "scheme": "CKKS",
                        "backend": evaluator.backend_name,
                        "serialization": evaluator.serialization,
                        "secret_key_required_by_api": False,
                        "key_contract": {
                            "variance": ["multiplication_keys", "rotation_keys"],
                            "legacy_single_key_field": "evaluation_keys",
                        },
                        "not_implemented": {
                            "compare": "requires CKKS/FHEW scheme switching",
                            "max": "requires CKKS/FHEW scheme switching",
                            "rolling_mean": "window boundary semantics not fixed",
                        },
                        "demo_sum_endpoint": "/v1/demo/sum",
                        "native_demo_endpoint": "/v1/demo/evaluate",
                        "native_demo_operations": list(OPERATIONS),
                        "demo_sum_input": "plaintext numeric array",
                    },
                )
            else:
                self._send_json(404, {"error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path not in (
                "/v1/evaluate", "/v1/demo/evaluate", "/v1/demo/sum"
            ):
                self._send_json(404, {"error": "not_found"})
                return
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip()
            if content_type != "application/json":
                self._send_json(415, {"error": "content_type_must_be_json"})
                return
            try:
                content_length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                self._send_json(400, {"error": "invalid_content_length"})
                return
            if content_length < 1 or content_length > MAX_REQUEST_BYTES:
                self._send_json(413, {"error": "request_size_not_allowed"})
                return
            try:
                payload = json.loads(self.rfile.read(content_length))
                if self.path == "/v1/demo/sum":
                    response = evaluate_demo_sum_request(payload, demo_sum_evaluator)
                elif self.path == "/v1/demo/evaluate":
                    response = evaluate_demo_request(payload, demo_evaluator)
                else:
                    response = evaluate_request(payload, evaluator)
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._send_json(400, {"error": "invalid_json"})
            except RequestError as error:
                self._send_json(422, {"error": "invalid_request", "detail": str(error)})
            except Exception:
                self._send_json(500, {"error": "evaluation_failed"})
            else:
                self._send_json(200, response)

    return Handler


def create_server(
    host: str = "0.0.0.0",
    port: int = 8080,
    evaluator: CiphertextEvaluator | None = None,
    demo_evaluator: DemoEvaluator | None = None,
    demo_sum_evaluator: DemoSumEvaluator | None = None,
) -> HTTPServer:
    selected = evaluator or OpenFHEPythonBackend()
    selected_demo = demo_evaluator or OpenFHEDemoBackend()
    selected_demo_sum = demo_sum_evaluator or OpenFHEDemoSumBackend()
    return HTTPServer(
        (host, port), make_handler(selected, selected_demo, selected_demo_sum)
    )


def main() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    server = create_server(host=host, port=port)
    print(f"OpenFHE ciphertext evaluator listening on {host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
