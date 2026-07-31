"""Trusted HTTP gateway for composable OpenFHE vector arithmetic."""

from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
import importlib
import json
import math
import os
import threading
import time
from typing import Any, Protocol
import uuid

from gateway.heir_adjusted_net import (
    HEIR_TRIAL_WIDTH,
    HeirAdjustedNetTrial,
    HeirUnavailableError,
)


MAX_REQUEST_BYTES = int(os.getenv("MAX_REQUEST_BYTES", str(1024 * 1024)))
MAX_VECTOR_LENGTH = int(os.getenv("MAX_VECTOR_LENGTH", "64"))
MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", "32"))
MAX_CIPHERTEXTS_PER_SESSION = int(
    os.getenv("MAX_CIPHERTEXTS_PER_SESSION", "128")
)
MAX_MULTIPLICATIVE_DEPTH = int(os.getenv("MAX_MULTIPLICATIVE_DEPTH", "8"))
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "900"))
DEFAULT_MULTIPLICATIVE_DEPTH = 3
BINARY_OPERATIONS = ("add", "subtract", "multiply")
UNARY_OPERATIONS = ("square",)
REDUCTION_OPERATIONS = ("sum", "mean")
OPERATIONS = BINARY_OPERATIONS + UNARY_OPERATIONS + REDUCTION_OPERATIONS
COMPOSITE_OPERATIONS = (
    "variance_components",
    "covariance_components",
    "correlation_components",
    "weighted_sum",
    "risk_score",
)


class RequestError(ValueError):
    """An error caused by an invalid client request."""


class GatewayCrypto(Protocol):
    @property
    def ready(self) -> bool:
        """Return whether gateway cryptography is available."""

    def create_session(
        self, values: list[float], multiplicative_depth: int
    ) -> tuple[str, str]:
        """Create a session and return its first ciphertext ID."""

    def encrypt(self, session_id: str, values: list[float]) -> str:
        """Encrypt values in an existing session."""

    def evaluate(
        self,
        session_id: str,
        operation: str,
        left_id: str,
        right: str | PublicOperand | None,
    ) -> str:
        """Evaluate an operation and return a new ciphertext ID."""

    def decrypt(self, session_id: str, ciphertext_id: str) -> list[float]:
        """Decrypt one ciphertext without consuming the session."""

    def delete_session(self, session_id: str) -> None:
        """Delete a session and all of its ciphertexts."""


class HeirTrial(Protocol):
    @property
    def available(self) -> bool:
        """Return whether the isolated HEIR runtime can be loaded."""

    def evaluate(
        self,
        income: list[float],
        expenses: list[float],
        adjustment: list[float],
    ) -> dict[str, Any]:
        """Run the fixed adjusted-net HEIR program."""


@dataclass
class StoredCiphertext:
    value: Any
    logical_length: int


@dataclass(frozen=True)
class PublicOperand:
    kind: str
    values: tuple[float, ...]


@dataclass
class GatewaySession:
    context: Any
    public_key: Any
    secret_key: Any
    vector_length: int
    ciphertexts: dict[str, StoredCiphertext]
    expires_at: float


def validate_values(payload: Any) -> list[float]:
    if not isinstance(payload, list) or not payload:
        raise RequestError("values must be a non-empty numeric list")
    if len(payload) > MAX_VECTOR_LENGTH:
        raise RequestError("values exceed the vector length limit")
    try:
        values = [float(item) for item in payload]
    except (TypeError, ValueError) as error:
        raise RequestError("values must contain only numbers") from error
    if not all(math.isfinite(item) for item in values):
        raise RequestError("values must contain only finite numbers")
    return values


def validate_depth(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RequestError("multiplicative_depth must be an integer")
    if value < 1 or value > MAX_MULTIPLICATIVE_DEPTH:
        raise RequestError(
            f"multiplicative_depth must be between 1 and "
            f"{MAX_MULTIPLICATIVE_DEPTH}"
        )
    return value


def require_object(payload: Any, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RequestError("request body must be a JSON object")
    unexpected = sorted(set(payload) - allowed)
    if unexpected:
        raise RequestError(f"unexpected fields: {', '.join(unexpected)}")
    return payload


def validate_public_operand(payload: Any) -> PublicOperand:
    if not isinstance(payload, dict):
        raise RequestError(
            "right must be a ciphertext ID or public operand"
        )
    kind = payload.get("kind")
    if kind == "public_vector":
        body = require_object(payload, {"kind", "values"})
        return PublicOperand(
            kind=kind,
            values=tuple(validate_values(body.get("values"))),
        )
    if kind == "public_scalar":
        body = require_object(payload, {"kind", "value"})
        value = body.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise RequestError("public scalar must be a finite number")
        number = float(value)
        if not math.isfinite(number):
            raise RequestError("public scalar must be a finite number")
        return PublicOperand(kind=kind, values=(number,))
    raise RequestError(
        "public operand kind must be public_vector or public_scalar"
    )


class OpenFHEGatewayCrypto:
    """In-memory trusted gateway backed by OpenFHE-Python."""

    def __init__(self) -> None:
        self._sessions: dict[str, GatewaySession] = {}
        self._lock = threading.Lock()

    @property
    def ready(self) -> bool:
        try:
            importlib.import_module("openfhe")
        except (ImportError, OSError):
            return False
        return True

    def _purge_expired(self, now: float) -> None:
        expired = [
            session_id
            for session_id, session in self._sessions.items()
            if session.expires_at <= now
        ]
        for session_id in expired:
            del self._sessions[session_id]

    def _session(self, session_id: str, now: float) -> GatewaySession:
        self._purge_expired(now)
        session = self._sessions.get(session_id)
        if session is None:
            raise RequestError("unknown or expired session")
        session.expires_at = now + SESSION_TTL_SECONDS
        return session

    @staticmethod
    def _ciphertext(
        session: GatewaySession, ciphertext_id: str
    ) -> StoredCiphertext:
        ciphertext = session.ciphertexts.get(ciphertext_id)
        if ciphertext is None:
            raise RequestError("unknown ciphertext")
        return ciphertext

    @staticmethod
    def _store(
        session: GatewaySession, ciphertext: Any, logical_length: int
    ) -> str:
        if len(session.ciphertexts) >= MAX_CIPHERTEXTS_PER_SESSION:
            raise RequestError("ciphertext limit reached for this session")
        ciphertext_id = uuid.uuid4().hex
        session.ciphertexts[ciphertext_id] = StoredCiphertext(
            value=ciphertext,
            logical_length=logical_length,
        )
        return ciphertext_id

    def create_session(
        self, values: list[float], multiplicative_depth: int
    ) -> tuple[str, str]:
        if not self.ready:
            raise RuntimeError("OpenFHE-Python is not installed")

        import openfhe

        with self._lock:
            now = time.monotonic()
            self._purge_expired(now)
            if len(self._sessions) >= MAX_SESSIONS:
                raise RequestError("trusted session limit reached")

            batch_size = max(8, 1 << (len(values) - 1).bit_length())
            parameters = openfhe.CCParamsCKKSRNS()
            parameters.SetMultiplicativeDepth(multiplicative_depth)
            parameters.SetScalingModSize(50)
            parameters.SetBatchSize(batch_size)

            context = openfhe.GenCryptoContext(parameters)
            context.Enable(openfhe.PKE)
            context.Enable(openfhe.KEYSWITCH)
            context.Enable(openfhe.LEVELEDSHE)
            context.Enable(openfhe.ADVANCEDSHE)
            key_pair = context.KeyGen()
            context.EvalMultKeyGen(key_pair.secretKey)
            context.EvalSumKeyGen(key_pair.secretKey)

            plaintext = context.MakeCKKSPackedPlaintext(values)
            ciphertext = context.Encrypt(key_pair.publicKey, plaintext)
            ciphertext_id = uuid.uuid4().hex
            session_id = uuid.uuid4().hex
            self._sessions[session_id] = GatewaySession(
                context=context,
                public_key=key_pair.publicKey,
                secret_key=key_pair.secretKey,
                vector_length=len(values),
                ciphertexts={
                    ciphertext_id: StoredCiphertext(
                        value=ciphertext,
                        logical_length=len(values),
                    )
                },
                expires_at=now + SESSION_TTL_SECONDS,
            )
            return session_id, ciphertext_id

    def encrypt(self, session_id: str, values: list[float]) -> str:
        with self._lock:
            session = self._session(session_id, time.monotonic())
            if len(values) != session.vector_length:
                raise RequestError(
                    "values must match the session vector length"
                )
            plaintext = session.context.MakeCKKSPackedPlaintext(values)
            ciphertext = session.context.Encrypt(
                session.public_key,
                plaintext,
            )
            return self._store(session, ciphertext, len(values))

    def evaluate(
        self,
        session_id: str,
        operation: str,
        left_id: str,
        right: str | PublicOperand | None,
    ) -> str:
        with self._lock:
            session = self._session(session_id, time.monotonic())
            left = self._ciphertext(session, left_id)
            if operation in BINARY_OPERATIONS:
                if right is None:
                    raise RequestError(
                        f"{operation} requires a right operand"
                    )
                if isinstance(right, str):
                    stored_right = self._ciphertext(session, right)
                    if left.logical_length != stored_right.logical_length:
                        raise RequestError(
                            "binary ciphertexts must have the same "
                            "logical length"
                        )
                    right_value = stored_right.value
                else:
                    if right.kind == "public_vector":
                        if len(right.values) != left.logical_length:
                            raise RequestError(
                                "public vector must match ciphertext "
                                "logical length"
                            )
                        right_value = (
                            session.context.MakeCKKSPackedPlaintext(
                                list(right.values),
                                1,
                                left.value.GetLevel(),
                            )
                        )
                    else:
                        right_value = right.values[0]
                if operation == "add":
                    result = session.context.EvalAdd(
                        left.value, right_value
                    )
                elif operation == "subtract":
                    result = session.context.EvalSub(
                        left.value, right_value
                    )
                else:
                    result = session.context.EvalMult(
                        left.value, right_value
                    )
                logical_length = left.logical_length
            elif operation in UNARY_OPERATIONS:
                if right is not None:
                    raise RequestError(
                        f"{operation} accepts only one ciphertext"
                    )
                result = session.context.EvalSquare(left.value)
                logical_length = left.logical_length
            elif operation in REDUCTION_OPERATIONS:
                if right is not None:
                    raise RequestError(
                        f"{operation} accepts only one ciphertext"
                    )
                result = session.context.EvalSum(
                    left.value, left.logical_length
                )
                if operation == "mean":
                    result = session.context.EvalMult(
                        result, 1.0 / left.logical_length
                    )
                logical_length = 1
            else:
                raise RequestError(f"unsupported operation: {operation}")
            return self._store(session, result, logical_length)

    def decrypt(self, session_id: str, ciphertext_id: str) -> list[float]:
        with self._lock:
            session = self._session(session_id, time.monotonic())
            ciphertext = self._ciphertext(session, ciphertext_id)
            plaintext = session.context.Decrypt(
                session.secret_key, ciphertext.value
            )
            plaintext.SetLength(ciphertext.logical_length)
            return [
                float(value) for value in plaintext.GetRealPackedValue()
            ]

    def delete_session(self, session_id: str) -> None:
        with self._lock:
            if self._sessions.pop(session_id, None) is None:
                raise RequestError("unknown or expired session")


def make_handler(
    crypto: GatewayCrypto,
    heir_trial: HeirTrial | None = None,
) -> type[BaseHTTPRequestHandler]:
    selected_heir_trial = heir_trial or HeirAdjustedNetTrial()

    class Handler(BaseHTTPRequestHandler):
        server_version = "he-gateway/0.1"

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

        @staticmethod
        def _session_route(path: str) -> tuple[str, str] | None:
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[:2] == ["v1", "sessions"]:
                return parts[2], parts[3]
            return None

        def do_GET(self) -> None:  # noqa: N802
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
                        "operations": list(OPERATIONS),
                        "public_operands": [
                            "public_vector",
                            "public_scalar",
                        ],
                        "composite_operations": list(
                            COMPOSITE_OPERATIONS
                        ),
                        "scheme": "CKKS",
                        "client_openfhe_required": False,
                        "trusted_gateway": True,
                        "session_ttl_seconds": SESSION_TTL_SECONDS,
                        "heir": {
                            "available": selected_heir_trial.available,
                            "programs": ["adjusted_net_total"],
                            "trial_width": HEIR_TRIAL_WIDTH,
                        },
                    },
                )
            else:
                self._send_json(404, {"error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != (
                "application/json"
            ):
                self._send_json(415, {"error": "content_type_must_be_json"})
                return

            try:
                payload = self._read_json()
                if self.path == "/v1/heir/adjusted-net":
                    body = require_object(
                        payload,
                        {"income", "expenses", "adjustment"},
                    )
                    income = validate_values(body.get("income"))
                    expenses = validate_values(body.get("expenses"))
                    adjustment = validate_values(body.get("adjustment"))
                    if not (
                        len(income)
                        == len(expenses)
                        == len(adjustment)
                        == HEIR_TRIAL_WIDTH
                    ):
                        raise RequestError(
                            f"HEIR adjusted-net inputs must contain exactly "
                            f"{HEIR_TRIAL_WIDTH} values"
                        )
                    try:
                        heir_result = selected_heir_trial.evaluate(
                            income,
                            expenses,
                            adjustment,
                        )
                    except HeirUnavailableError:
                        raise
                    except Exception as error:
                        self._send_json(
                            500,
                            {
                                "error": "heir_trial_failed",
                                "detail": str(error),
                            },
                        )
                        return
                    self._send_json(200, heir_result)
                    return

                if self.path == "/v1/sessions":
                    body = require_object(
                        payload, {"values", "multiplicative_depth"}
                    )
                    values = validate_values(body.get("values"))
                    depth = validate_depth(
                        body.get(
                            "multiplicative_depth",
                            DEFAULT_MULTIPLICATIVE_DEPTH,
                        )
                    )
                    session_id, ciphertext_id = crypto.create_session(
                        values, depth
                    )
                    self._send_json(
                        201,
                        {
                            "session_id": session_id,
                            "ciphertext_id": ciphertext_id,
                        },
                    )
                    return

                route = self._session_route(self.path)
                if route is None:
                    self._send_json(404, {"error": "not_found"})
                    return
                session_id, action = route

                if action == "ciphertexts":
                    body = require_object(payload, {"values"})
                    ciphertext_id = crypto.encrypt(
                        session_id, validate_values(body.get("values"))
                    )
                elif action == "evaluate":
                    body = require_object(
                        payload, {"operation", "left", "right"}
                    )
                    operation = body.get("operation")
                    left = body.get("left")
                    right = body.get("right")
                    if operation not in OPERATIONS:
                        raise RequestError("unsupported operation")
                    if not isinstance(left, str) or not left:
                        raise RequestError("left must be a ciphertext ID")
                    if operation in BINARY_OPERATIONS:
                        if isinstance(right, str):
                            if not right:
                                raise RequestError(
                                    "right must be a ciphertext ID "
                                    "or public operand"
                                )
                        else:
                            right = validate_public_operand(right)
                    elif right is not None:
                        raise RequestError(
                            f"{operation} accepts only one ciphertext"
                        )
                    ciphertext_id = crypto.evaluate(
                        session_id, operation, left, right
                    )
                elif action == "decrypt":
                    body = require_object(payload, {"ciphertext_id"})
                    ciphertext_id = body.get("ciphertext_id")
                    if not isinstance(ciphertext_id, str) or not ciphertext_id:
                        raise RequestError(
                            "ciphertext_id must be a ciphertext ID"
                        )
                    self._send_json(
                        200,
                        {
                            "values": crypto.decrypt(
                                session_id, ciphertext_id
                            )
                        },
                    )
                    return
                else:
                    self._send_json(404, {"error": "not_found"})
                    return

                self._send_json(200, {"ciphertext_id": ciphertext_id})
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._send_json(400, {"error": "invalid_json"})
            except RequestError as error:
                self._send_json(
                    422,
                    {"error": "invalid_request", "detail": str(error)},
                )
            except HeirUnavailableError as error:
                self._send_json(
                    503,
                    {"error": "heir_unavailable", "detail": str(error)},
                )
            except Exception:
                self._send_json(500, {"error": "crypto_operation_failed"})

        def do_DELETE(self) -> None:  # noqa: N802
            parts = self.path.strip("/").split("/")
            if len(parts) != 3 or parts[:2] != ["v1", "sessions"]:
                self._send_json(404, {"error": "not_found"})
                return
            try:
                crypto.delete_session(parts[2])
            except RequestError as error:
                self._send_json(
                    422,
                    {"error": "invalid_request", "detail": str(error)},
                )
            else:
                self.send_response(204)
                self.end_headers()

    return Handler


def create_server(
    host: str = "0.0.0.0",
    port: int = 8080,
    crypto: GatewayCrypto | None = None,
    heir_trial: HeirTrial | None = None,
) -> HTTPServer:
    selected_crypto = crypto or OpenFHEGatewayCrypto()
    return HTTPServer(
        (host, port),
        make_handler(selected_crypto, heir_trial),
    )


def main() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    server = create_server(host=host, port=port)
    print(f"Trusted HE gateway listening on {host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
