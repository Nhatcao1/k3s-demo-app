"""Secretless HTTP adapter for the separate FIDESlib GPU worker."""

from __future__ import annotations

import base64
import binascii
import ctypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import math
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from typing import Any, Protocol


OPERATIONS = ("add", "subtract", "multiply", "sum")
MAX_ARTIFACT_BYTES = int(os.getenv("MAX_ARTIFACT_BYTES", str(256 * 1024 * 1024)))
MAX_REQUEST_BYTES = int(os.getenv("MAX_REQUEST_BYTES", str(768 * 1024 * 1024)))
LOGGER = logging.getLogger(__name__)


class RequestError(ValueError):
    """The caller supplied an invalid or incompatible HE artifact."""


def check_gpu_runtime(worker: Path) -> int:
    """Fail startup with a useful log when the NVIDIA runtime is unavailable."""
    if not worker.is_file() or not os.access(worker, os.X_OK):
        raise RuntimeError(f"FIDESlib worker is not executable: {worker}")
    if not Path("/dev/nvidiactl").exists():
        raise RuntimeError("NVIDIA device /dev/nvidiactl is not available")

    try:
        cuda = ctypes.CDLL("libcuda.so.1")
    except OSError as error:
        raise RuntimeError("NVIDIA driver library libcuda.so.1 is unavailable") from error

    cuda.cuInit.argtypes = [ctypes.c_uint]
    cuda.cuInit.restype = ctypes.c_int
    status = cuda.cuInit(0)
    if status != 0:
        raise RuntimeError(f"CUDA driver initialization failed with code {status}")

    device_count = ctypes.c_int()
    cuda.cuDeviceGetCount.argtypes = [ctypes.POINTER(ctypes.c_int)]
    cuda.cuDeviceGetCount.restype = ctypes.c_int
    status = cuda.cuDeviceGetCount(ctypes.byref(device_count))
    if status != 0:
        raise RuntimeError(f"CUDA device discovery failed with code {status}")
    if device_count.value < 1:
        raise RuntimeError("CUDA initialized but reported no GPU devices")
    return device_count.value


class Evaluator(Protocol):
    backend_name: str
    serialization: str

    @property
    def ready(self) -> bool: ...

    def evaluate(
        self,
        operation: str,
        context: bytes,
        public_key: bytes,
        ciphertext_a: bytes,
        ciphertext_b: bytes | None,
        evaluation_keys: bytes | None,
        valid_count: int | None,
    ) -> bytes: ...


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


def fides_sum_rotation_indices(valid_count: int) -> list[int]:
    """Return the rotations used by FIDESlib Accumulate(..., bStep=4)."""
    indices: list[int] = []
    step = 1
    while step < valid_count:
        for multiplier in range(1, 4):
            index = multiplier * step
            if index < valid_count:
                indices.append(index)
        step *= 4
    return indices


def write_fides_context_metadata(
    context_path: Path,
    operation: str,
    valid_count: int | None,
    device: int,
) -> None:
    rotations = fides_sum_rotation_indices(valid_count or 0) if operation == "sum" else []
    rotation_text = " ".join(str(index) for index in rotations)
    (Path(str(context_path) + ".dev")).write_text(
        f"1 {{ {device} }}\n"
        "AutoLoadCiphertexts: 1\n"
        "AutoLoadPlaintexts: 0\n"
        f"RotationIndexes: {{ {rotation_text} }}\n"
        "KeyDist: 1\n"
        "BootstrapSlots: { }\n",
        encoding="utf-8",
    )


class FidesWorkerBackend:
    """Invoke the C++ worker once per request using private temporary files."""

    backend_name = "gpu-fideslib"
    serialization = "openfhe_binary_base64"
    _lock = threading.Lock()

    def __init__(self, worker: str | None = None, device: int | None = None) -> None:
        self.worker = Path(worker or os.getenv("HE_GPU_WORKER", "/opt/he-gpu-worker"))
        self.device = device if device is not None else int(os.getenv("FIDES_DEVICE", "0"))
        self.timeout = float(os.getenv("HE_GPU_WORKER_TIMEOUT_SECONDS", "600"))

    @property
    def ready(self) -> bool:
        return self.worker.is_file() and os.access(self.worker, os.X_OK) and Path(
            "/dev/nvidiactl"
        ).exists()

    def evaluate(
        self,
        operation: str,
        context: bytes,
        public_key: bytes,
        ciphertext_a: bytes,
        ciphertext_b: bytes | None,
        evaluation_keys: bytes | None,
        valid_count: int | None,
    ) -> bytes:
        with self._lock, tempfile.TemporaryDirectory(prefix="fides-evaluate-") as directory:
            root = Path(directory)
            paths = {
                "context": root / "context.bin",
                "public_key": root / "public-key.bin",
                "left": root / "ciphertext-a.bin",
                "right": root / "ciphertext-b.bin",
                "evaluation_keys": root / "evaluation-keys.bin",
                "output": root / "result.bin",
            }
            paths["context"].write_bytes(context)
            paths["public_key"].write_bytes(public_key)
            paths["left"].write_bytes(ciphertext_a)
            write_fides_context_metadata(
                paths["context"], operation, valid_count, self.device
            )

            command = [
                str(self.worker),
                "--operation", operation,
                "--context", str(paths["context"]),
                "--public-key", str(paths["public_key"]),
                "--left", str(paths["left"]),
                "--output", str(paths["output"]),
            ]
            if ciphertext_b is not None:
                paths["right"].write_bytes(ciphertext_b)
                command.extend(("--right", str(paths["right"])))
            if evaluation_keys is not None:
                paths["evaluation_keys"].write_bytes(evaluation_keys)
                command.extend(("--evaluation-keys", str(paths["evaluation_keys"])))
            if valid_count is not None:
                command.extend(("--valid-count", str(valid_count)))

            try:
                completed = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                LOGGER.exception("FIDESlib worker could not complete")
                raise RuntimeError("FIDESlib worker could not complete") from error
            if completed.returncode != 0:
                worker_error = (completed.stderr or "<no stderr>").strip()
                LOGGER.error(
                    "FIDESlib worker exited with code %s: %s",
                    completed.returncode,
                    worker_error[:8192],
                )
                raise RequestError("FIDESlib rejected the supplied HE artifacts")
            if not paths["output"].is_file() or paths["output"].stat().st_size == 0:
                LOGGER.error("FIDESlib worker exited successfully without an output artifact")
                raise RuntimeError("FIDESlib worker produced no result")
            return paths["output"].read_bytes()


class NativeDemoBackend:
    """Run an end-to-end FIDESlib operation in one native C++ process."""

    backend_name = "gpu-fideslib-native-demo"
    _lock = threading.Lock()

    def __init__(self, worker: str | None = None) -> None:
        self.worker = Path(
            worker or os.getenv("HE_GPU_DEMO_WORKER", "/opt/he-gpu-demo")
        )
        self.timeout = float(os.getenv("HE_GPU_DEMO_TIMEOUT_SECONDS", "600"))

    @property
    def ready(self) -> bool:
        return self.worker.is_file() and os.access(self.worker, os.X_OK) and Path(
            "/dev/nvidiactl"
        ).exists()

    def evaluate(
        self,
        operation: str,
        values_a: list[float],
        values_b: list[float] | None,
    ) -> list[float]:
        command = [
            str(self.worker),
            "--operation",
            operation,
            "--left",
            ",".join(format(value, ".17g") for value in values_a),
        ]
        if values_b is not None:
            command.extend(
                ("--right", ",".join(format(value, ".17g") for value in values_b))
            )

        try:
            with self._lock:
                completed = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                )
        except (OSError, subprocess.TimeoutExpired) as error:
            LOGGER.exception("native FIDESlib demo could not complete")
            raise RuntimeError("native FIDESlib demo could not complete") from error
        if completed.returncode != 0:
            worker_error = (completed.stderr or "<no stderr>").strip()
            LOGGER.error(
                "native FIDESlib demo exited with code %s: %s",
                completed.returncode,
                worker_error[:8192],
            )
            raise RequestError("native FIDESlib demo rejected the request")
        # FIDESlib prints CUDA device information to stdout before the demo's
        # JSON result. Read the final JSON object instead of requiring stdout
        # to contain JSON and nothing else.
        payload = None
        for line in reversed(completed.stdout.splitlines()):
            try:
                candidate = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                payload = candidate
                break
        if payload is None or "values" not in payload:
            LOGGER.error(
                "native FIDESlib demo returned no JSON result: %s",
                completed.stdout[-8192:],
            )
            raise RuntimeError("native FIDESlib demo returned invalid output")
        values = payload["values"]
        if not isinstance(values, list) or not all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in values
        ):
            raise RuntimeError("native FIDESlib demo returned invalid values")
        return [float(value) for value in values]


def _decode(payload: dict[str, Any], name: str) -> bytes:
    value = payload.get(name)
    if not isinstance(value, str) or not value:
        raise RequestError(f"{name} must be a non-empty base64 string")
    if len(value) > 4 * ((MAX_ARTIFACT_BYTES + 2) // 3):
        raise RequestError(f"{name} exceeds the artifact size limit")
    try:
        result = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as error:
        raise RequestError(f"{name} is not valid base64") from error
    if not result or len(result) > MAX_ARTIFACT_BYTES:
        raise RequestError(f"{name} has an invalid artifact size")
    return result


def evaluate_request(payload: Any, evaluator: Evaluator) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RequestError("request body must be a JSON object")
    allowed = {
        "operation", "context", "public_key", "ciphertext_a", "ciphertext_b",
        "evaluation_keys", "valid_count", "request_id",
    }
    unexpected = sorted(set(payload) - allowed)
    if unexpected:
        raise RequestError(f"unexpected fields: {', '.join(unexpected)}")
    operation = payload.get("operation")
    if operation not in OPERATIONS:
        raise RequestError(f"operation must be one of: {', '.join(OPERATIONS)}")

    request_id = payload.get("request_id")
    if request_id is not None and (
        not isinstance(request_id, str) or not request_id or len(request_id) > 128
    ):
        raise RequestError("request_id must be a non-empty string of at most 128 characters")

    context = _decode(payload, "context")
    public_key = _decode(payload, "public_key")
    ciphertext_a = _decode(payload, "ciphertext_a")
    ciphertext_b = None
    if operation != "sum":
        ciphertext_b = _decode(payload, "ciphertext_b")
    elif "ciphertext_b" in payload:
        raise RequestError("sum does not accept ciphertext_b")

    evaluation_keys = None
    if operation in ("multiply", "sum"):
        evaluation_keys = _decode(payload, "evaluation_keys")
    elif "evaluation_keys" in payload:
        raise RequestError(f"{operation} does not accept evaluation_keys")

    valid_count = payload.get("valid_count")
    if operation == "sum":
        if isinstance(valid_count, bool) or not isinstance(valid_count, int) or valid_count < 1:
            raise RequestError("valid_count must be a positive integer for sum")
    elif "valid_count" in payload:
        raise RequestError(f"{operation} does not accept valid_count")

    started = time.perf_counter()
    result = evaluator.evaluate(
        operation, context, public_key, ciphertext_a, ciphertext_b,
        evaluation_keys, valid_count,
    )
    response: dict[str, Any] = {
        "operation": operation,
        "backend": evaluator.backend_name,
        "ciphertext": base64.b64encode(result).decode("ascii"),
        "evaluation_seconds": time.perf_counter() - started,
    }
    if request_id is not None:
        response["request_id"] = request_id
    return response


def _demo_values(payload: dict[str, Any], name: str) -> list[float]:
    values = payload.get(name)
    if not isinstance(values, list) or not 1 <= len(values) <= 4096:
        raise RequestError(f"{name} must contain between 1 and 4096 numbers")
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
    if not isinstance(payload, dict):
        raise RequestError("request body must be a JSON object")
    allowed = {"operation", "values_a", "values_b", "request_id"}
    unexpected = sorted(set(payload) - allowed)
    if unexpected:
        raise RequestError(f"unexpected fields: {', '.join(unexpected)}")

    operation = payload.get("operation")
    if operation not in OPERATIONS:
        raise RequestError(f"operation must be one of: {', '.join(OPERATIONS)}")
    values_a = _demo_values(payload, "values_a")
    values_b = None
    if operation == "sum":
        if "values_b" in payload:
            raise RequestError("sum does not accept values_b")
    else:
        values_b = _demo_values(payload, "values_b")
        if len(values_a) != len(values_b):
            raise RequestError("values_a and values_b must have equal length")

    request_id = payload.get("request_id")
    if request_id is not None and (
        not isinstance(request_id, str) or not request_id or len(request_id) > 128
    ):
        raise RequestError("request_id must be a non-empty string of at most 128 characters")

    started = time.perf_counter()
    values = evaluator.evaluate(operation, values_a, values_b)
    response: dict[str, Any] = {
        "operation": operation,
        "backend": evaluator.backend_name,
        "values": values,
        "evaluation_seconds": time.perf_counter() - started,
        "demo_trust_model": "plaintext enters the GPU service",
    }
    if request_id is not None:
        response["request_id"] = request_id
    return response


def make_handler(
    evaluator: Evaluator, demo_evaluator: DemoEvaluator
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "he-fides-evaluator/0.1"

        def _send(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/healthz":
                self._send(200, {"status": "ok"})
            elif self.path == "/readyz":
                ready = evaluator.ready and demo_evaluator.ready
                self._send(
                    200 if ready else 503,
                    {"status": "ready" if ready else "not_ready"},
                )
            elif self.path == "/v1/capabilities":
                self._send(200, {
                    "operations": list(OPERATIONS),
                    "scheme": "CKKS",
                    "backend": evaluator.backend_name,
                    "serialization": evaluator.serialization,
                    "public_key_required_by_api": True,
                    "secret_key_required_by_api": False,
                    "native_demo_endpoint": "/v1/demo/evaluate",
                    "native_demo_input": "plaintext numeric arrays",
                })
            else:
                self._send(404, {"error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path not in ("/v1/evaluate", "/v1/demo/evaluate"):
                self._send(404, {"error": "not_found"})
                return
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
                self._send(415, {"error": "content_type_must_be_json"})
                return
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                self._send(400, {"error": "invalid_content_length"})
                return
            if length < 1 or length > MAX_REQUEST_BYTES:
                self._send(413, {"error": "request_size_not_allowed"})
                return
            try:
                payload = json.loads(self.rfile.read(length))
                response = (
                    evaluate_demo_request(payload, demo_evaluator)
                    if self.path == "/v1/demo/evaluate"
                    else evaluate_request(payload, evaluator)
                )
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._send(400, {"error": "invalid_json"})
            except RequestError as error:
                self._send(422, {"error": "invalid_request", "detail": str(error)})
            except Exception:
                LOGGER.exception("GPU evaluation failed")
                self._send(500, {"error": "evaluation_failed"})
            else:
                self._send(200, response)

    return Handler


def create_server(
    host: str = "0.0.0.0",
    port: int = 8080,
    evaluator: Evaluator | None = None,
    demo_evaluator: DemoEvaluator | None = None,
) -> ThreadingHTTPServer:
    selected = evaluator or FidesWorkerBackend()
    selected_demo = demo_evaluator or NativeDemoBackend()
    return ThreadingHTTPServer((host, port), make_handler(selected, selected_demo))


def main() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    evaluator = FidesWorkerBackend()
    demo_evaluator = NativeDemoBackend()
    try:
        device_count = check_gpu_runtime(evaluator.worker)
        if not demo_evaluator.worker.is_file() or not os.access(
            demo_evaluator.worker, os.X_OK
        ):
            raise RuntimeError(
                f"native FIDESlib demo is not executable: {demo_evaluator.worker}"
            )
    except Exception:
        LOGGER.exception("GPU runtime startup check failed")
        raise
    print(
        f"GPU runtime check passed with {device_count} device(s); "
        f"FIDESlib evaluator listening on {host}:{port}",
        flush=True,
    )
    create_server(host, port, evaluator, demo_evaluator).serve_forever()


if __name__ == "__main__":
    main()
