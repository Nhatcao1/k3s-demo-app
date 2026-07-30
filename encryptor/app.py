"""Trusted service that encrypts vector pairs and decrypts evaluated results."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
import importlib
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time
from typing import Any, Protocol
import uuid


MAX_REQUEST_BYTES = int(os.getenv("MAX_REQUEST_BYTES", str(1024 * 1024)))
MAX_VECTOR_LENGTH = int(os.getenv("MAX_VECTOR_LENGTH", "64"))
MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", "32"))
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "900"))


class RequestError(ValueError):
    """An error caused by an invalid client request."""


class SessionCrypto(Protocol):
    @property
    def ready(self) -> bool:
        """Return whether encryption/decryption is available."""

    def encrypt_pair(
        self,
        left: list[float],
        right: list[float],
    ) -> tuple[str, dict[str, bytes]]:
        """Return a session ID and evaluator bundle."""

    def decrypt(self, session_id: str, ciphertext: bytes) -> list[float]:
        """Decrypt one result and consume its session."""


@dataclass
class CryptoSession:
    context: Any
    secret_key: Any
    vector_length: int
    expires_at: float


def validate_vectors(payload: Any) -> tuple[list[float], list[float]]:
    if not isinstance(payload, dict):
        raise RequestError("request body must be a JSON object")

    allowed = {"left", "right"}
    unexpected = sorted(set(payload) - allowed)
    if unexpected:
        raise RequestError(f"unexpected fields: {', '.join(unexpected)}")

    vectors: list[list[float]] = []
    for name in ("left", "right"):
        value = payload.get(name)
        if not isinstance(value, list) or not value:
            raise RequestError(f"{name} must be a non-empty numeric list")
        if len(value) > MAX_VECTOR_LENGTH:
            raise RequestError(f"{name} exceeds the vector length limit")
        try:
            numeric = [float(item) for item in value]
        except (TypeError, ValueError) as error:
            raise RequestError(f"{name} must contain only numbers") from error
        if not all(math.isfinite(item) for item in numeric):
            raise RequestError(f"{name} must contain only finite numbers")
        vectors.append(numeric)

    left, right = vectors
    if len(left) != len(right):
        raise RequestError("left and right must have the same length")
    return left, right


def decode_ciphertext(payload: Any) -> bytes:
    if not isinstance(payload, dict):
        raise RequestError("request body must be a JSON object")
    if set(payload) != {"ciphertext"}:
        raise RequestError("request must contain only ciphertext")
    encoded = payload["ciphertext"]
    if not isinstance(encoded, str) or not encoded:
        raise RequestError("ciphertext must be a non-empty base64 string")
    try:
        return base64.b64decode(encoded, validate=True)
    except ValueError as error:
        raise RequestError("ciphertext is not valid base64") from error


class OpenFHESessionCrypto:
    """In-memory trusted sessions backed by OpenFHE-Python."""

    def __init__(self) -> None:
        self._sessions: dict[str, CryptoSession] = {}
        self._lock = threading.Lock()

    @property
    def ready(self) -> bool:
        try:
            importlib.import_module("openfhe")
        except (ImportError, OSError):
            return False
        return True

    @staticmethod
    def _serialize(openfhe: Any, path: Path, value: Any) -> bytes:
        if not openfhe.SerializeToFile(str(path), value, openfhe.BINARY):
            raise RuntimeError(f"could not serialize {path.name}")
        return path.read_bytes()

    def _purge_expired(self, now: float) -> None:
        expired = [
            session_id
            for session_id, session in self._sessions.items()
            if session.expires_at <= now
        ]
        for session_id in expired:
            del self._sessions[session_id]

    def encrypt_pair(
        self,
        left: list[float],
        right: list[float],
    ) -> tuple[str, dict[str, bytes]]:
        if not self.ready:
            raise RuntimeError("OpenFHE-Python is not installed")

        import openfhe

        with self._lock:
            now = time.monotonic()
            self._purge_expired(now)
            if len(self._sessions) >= MAX_SESSIONS:
                raise RequestError("trusted session limit reached")

            batch_size = max(8, 1 << (len(left) - 1).bit_length())
            parameters = openfhe.CCParamsCKKSRNS()
            parameters.SetMultiplicativeDepth(1)
            parameters.SetScalingModSize(50)
            parameters.SetBatchSize(batch_size)

            context = openfhe.GenCryptoContext(parameters)
            context.Enable(openfhe.PKE)
            context.Enable(openfhe.KEYSWITCH)
            context.Enable(openfhe.LEVELEDSHE)
            key_pair = context.KeyGen()

            left_plaintext = context.MakeCKKSPackedPlaintext(left)
            right_plaintext = context.MakeCKKSPackedPlaintext(right)
            left_ciphertext = context.Encrypt(key_pair.publicKey, left_plaintext)
            right_ciphertext = context.Encrypt(key_pair.publicKey, right_plaintext)

            with tempfile.TemporaryDirectory(prefix="he-encryptor-") as directory:
                root = Path(directory)
                bundle = {
                    "context": self._serialize(
                        openfhe, root / "context.bin", context
                    ),
                    "ciphertext_a": self._serialize(
                        openfhe, root / "left.bin", left_ciphertext
                    ),
                    "ciphertext_b": self._serialize(
                        openfhe, root / "right.bin", right_ciphertext
                    ),
                }

            session_id = uuid.uuid4().hex
            self._sessions[session_id] = CryptoSession(
                context=context,
                secret_key=key_pair.secretKey,
                vector_length=len(left),
                expires_at=now + SESSION_TTL_SECONDS,
            )
            return session_id, bundle

    def decrypt(self, session_id: str, ciphertext: bytes) -> list[float]:
        if not self.ready:
            raise RuntimeError("OpenFHE-Python is not installed")

        import openfhe

        with self._lock:
            now = time.monotonic()
            self._purge_expired(now)
            session = self._sessions.get(session_id)
            if session is None:
                raise RequestError("unknown or expired session")

            with tempfile.TemporaryDirectory(prefix="he-decryptor-") as directory:
                path = Path(directory) / "result.bin"
                path.write_bytes(ciphertext)
                result, ok = openfhe.DeserializeCiphertext(
                    str(path), openfhe.BINARY
                )
                if not ok:
                    raise RequestError("could not deserialize result ciphertext")

            plaintext = session.context.Decrypt(session.secret_key, result)
            plaintext.SetLength(session.vector_length)
            values = [
                float(value) for value in plaintext.GetRealPackedValue()
            ]
            del self._sessions[session_id]
            return values


def make_handler(crypto: SessionCrypto) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "he-encryptor/0.1"

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> Any:
            try:
                content_length = int(self.headers.get("Content-Length", ""))
            except ValueError as error:
                raise RequestError("invalid Content-Length") from error
            if content_length < 1 or content_length > MAX_REQUEST_BYTES:
                raise RequestError("request size is not allowed")
            return json.loads(self.rfile.read(content_length))

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            if self.path == "/healthz":
                self._send_json(200, {"status": "ok"})
            elif self.path == "/readyz":
                status = 200 if crypto.ready else 503
                self._send_json(
                    status,
                    {"status": "ready" if crypto.ready else "not_ready"},
                )
            elif self.path == "/v1/capabilities":
                self._send_json(
                    200,
                    {
                        "operations": ["encrypt_pair", "decrypt_result"],
                        "scheme": "CKKS",
                        "trusted_service": True,
                        "secret_key_returned": False,
                        "session_ttl_seconds": SESSION_TTL_SECONDS,
                    },
                )
            else:
                self._send_json(404, {"error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != (
                "application/json"
            ):
                self._send_json(415, {"error": "content_type_must_be_json"})
                return

            try:
                payload = self._read_json()
                if self.path == "/v1/encrypt-pair":
                    left, right = validate_vectors(payload)
                    session_id, bundle = crypto.encrypt_pair(left, right)
                    self._send_json(
                        200,
                        {
                            "session_id": session_id,
                            "evaluation_bundle": {
                                name: base64.b64encode(value).decode("ascii")
                                for name, value in bundle.items()
                            },
                        },
                    )
                    return

                prefix = "/v1/sessions/"
                suffix = "/decrypt"
                if self.path.startswith(prefix) and self.path.endswith(suffix):
                    session_id = self.path[len(prefix) : -len(suffix)]
                    if not session_id:
                        raise RequestError("session ID is required")
                    ciphertext = decode_ciphertext(payload)
                    values = crypto.decrypt(session_id, ciphertext)
                    self._send_json(200, {"values": values})
                    return

                self._send_json(404, {"error": "not_found"})
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._send_json(400, {"error": "invalid_json"})
            except RequestError as error:
                self._send_json(422, {"error": "invalid_request", "detail": str(error)})
            except Exception:
                self._send_json(500, {"error": "crypto_operation_failed"})

    return Handler


def create_server(
    host: str = "0.0.0.0",
    port: int = 8080,
    crypto: SessionCrypto | None = None,
) -> HTTPServer:
    selected_crypto = crypto or OpenFHESessionCrypto()
    return HTTPServer((host, port), make_handler(selected_crypto))


def main() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    server = create_server(host=host, port=port)
    print(f"Trusted HE encryptor listening on {host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
