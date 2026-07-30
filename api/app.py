"""Small HTTP API for OpenFHE ciphertext + ciphertext evaluation."""

from __future__ import annotations

import base64
import binascii
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Any, Protocol
from http.server import BaseHTTPRequestHandler, HTTPServer


MAX_ARTIFACT_BYTES = int(os.getenv("MAX_ARTIFACT_BYTES", str(32 * 1024 * 1024)))
MAX_REQUEST_BYTES = int(os.getenv("MAX_REQUEST_BYTES", str(100 * 1024 * 1024)))


class RequestError(ValueError):
    """An error caused by an invalid API request."""


class CiphertextAdder(Protocol):
    @property
    def ready(self) -> bool:
        """Return whether the evaluator dependency is available."""

    def add(self, context: bytes, ciphertext_a: bytes, ciphertext_b: bytes) -> bytes:
        """Return the serialized homomorphic sum."""


class OpenFHECiphertextAdder:
    """File-backed adapter for OpenFHE-Python's binary serialization API."""

    _lock = threading.Lock()

    @property
    def ready(self) -> bool:
        try:
            import openfhe  # noqa: F401
        except (ImportError, OSError):
            return False
        return True

    def add(self, context: bytes, ciphertext_a: bytes, ciphertext_b: bytes) -> bytes:
        if not self.ready:
            raise RuntimeError("OpenFHE-Python is not installed")

        import openfhe

        # OpenFHE keeps a process-global context registry. One API worker and
        # this lock keep context release/deserialization/evaluation serialized.
        with self._lock, tempfile.TemporaryDirectory(prefix="he-add-") as directory:
            root = Path(directory)
            context_path = root / "context.bin"
            ciphertext_a_path = root / "ciphertext-a.bin"
            ciphertext_b_path = root / "ciphertext-b.bin"
            result_path = root / "result.bin"

            context_path.write_bytes(context)
            ciphertext_a_path.write_bytes(ciphertext_a)
            ciphertext_b_path.write_bytes(ciphertext_b)

            openfhe.ReleaseAllContexts()
            crypto_context, ok = openfhe.DeserializeCryptoContext(
                str(context_path), openfhe.BINARY
            )
            if not ok:
                raise RequestError("could not deserialize context")

            left, ok = openfhe.DeserializeCiphertext(
                str(ciphertext_a_path), openfhe.BINARY
            )
            if not ok:
                raise RequestError("could not deserialize ciphertext_a")

            right, ok = openfhe.DeserializeCiphertext(
                str(ciphertext_b_path), openfhe.BINARY
            )
            if not ok:
                raise RequestError("could not deserialize ciphertext_b")

            result = crypto_context.EvalAdd(left, right)
            if not openfhe.SerializeToFile(
                str(result_path), result, openfhe.BINARY
            ):
                raise RuntimeError("could not serialize result ciphertext")
            return result_path.read_bytes()


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


def evaluate_add_request(
    payload: Any,
    evaluator: CiphertextAdder,
) -> dict[str, str]:
    """Validate one request, evaluate it, and encode the ciphertext response."""
    if not isinstance(payload, dict):
        raise RequestError("request body must be a JSON object")

    allowed = {"context", "ciphertext_a", "ciphertext_b"}
    unexpected = sorted(set(payload) - allowed)
    if unexpected:
        raise RequestError(f"unexpected fields: {', '.join(unexpected)}")

    context = _decode_artifact(payload, "context")
    ciphertext_a = _decode_artifact(payload, "ciphertext_a")
    ciphertext_b = _decode_artifact(payload, "ciphertext_b")
    result = evaluator.add(context, ciphertext_a, ciphertext_b)
    return {"ciphertext": base64.b64encode(result).decode("ascii")}


def make_handler(evaluator: CiphertextAdder) -> type[BaseHTTPRequestHandler]:
    """Create a request handler bound to an evaluator."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "he-add-api/0.1"

        def log_message(self, message: str, *args: Any) -> None:
            # BaseHTTPRequestHandler logs method/path/status, never bodies.
            super().log_message(message, *args)

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            if self.path == "/healthz":
                self._send_json(200, {"status": "ok"})
            elif self.path == "/readyz":
                if evaluator.ready:
                    self._send_json(200, {"status": "ready"})
                else:
                    self._send_json(503, {"status": "not_ready"})
            elif self.path == "/v1/capabilities":
                self._send_json(
                    200,
                    {
                        "operations": ["ciphertext_add"],
                        "scheme": "CKKS",
                        "serialization": "openfhe_binary_base64",
                        "secret_key_required_by_api": False,
                    },
                )
            else:
                self._send_json(404, {"error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
            if self.path != "/v1/add":
                self._send_json(404, {"error": "not_found"})
                return

            content_type = self.headers.get("Content-Type", "")
            if content_type.split(";", 1)[0].strip() != "application/json":
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
                body = self.rfile.read(content_length)
                payload = json.loads(body)
                response = evaluate_add_request(payload, evaluator)
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._send_json(400, {"error": "invalid_json"})
            except RequestError as error:
                self._send_json(422, {"error": "invalid_artifact", "detail": str(error)})
            except Exception:
                # Do not return OpenFHE internals or serialized object details.
                self._send_json(500, {"error": "evaluation_failed"})
            else:
                self._send_json(200, response)

    return Handler


def create_server(
    host: str = "0.0.0.0",
    port: int = 8080,
    evaluator: CiphertextAdder | None = None,
) -> HTTPServer:
    """Create the single-worker HTTP server."""
    selected_evaluator = evaluator or OpenFHECiphertextAdder()
    return HTTPServer((host, port), make_handler(selected_evaluator))


def main() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    server = create_server(host=host, port=port)
    print(f"HE ciphertext-add API listening on {host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
