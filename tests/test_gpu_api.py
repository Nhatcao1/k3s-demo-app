from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from gpu.api.app import (
    FidesWorkerBackend,
    NativeDemoBackend,
    RequestError,
    create_server,
    evaluate_demo_request,
    evaluate_demo_sum_request,
    evaluate_request,
    fides_sum_rotation_indices,
    write_fides_context_metadata,
)


def encoded(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


class FakeGpuEvaluator:
    backend_name = "gpu-fides-test"
    serialization = "openfhe_binary_base64"
    ready = True

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
        self.received = (
            operation,
            context,
            public_key,
            ciphertext_a,
            ciphertext_b,
            evaluation_keys,
            valid_count,
        )
        return b"gpu-result"


class FakeNativeDemoEvaluator:
    backend_name = "gpu-fides-native-test"
    ready = True

    def evaluate(
        self,
        operation: str,
        values_a: list[float],
        values_b: list[float] | None,
    ) -> list[float]:
        self.received = (operation, values_a, values_b)
        if operation == "sum":
            return [sum(values_a)]
        assert values_b is not None
        if operation == "add":
            return [left + right for left, right in zip(values_a, values_b)]
        if operation == "subtract":
            return [left - right for left, right in zip(values_a, values_b)]
        return [left * right for left, right in zip(values_a, values_b)]

    def sum_many(self, values: list[float]) -> dict[str, object]:
        self.received_many = values
        return {
            "operation": "sum",
            "values": [sum(values)],
            "value_count": len(values),
            "batch_size": 8192,
            "chunks": 1,
            "timings": {"total_seconds": 0.2},
        }


def primitive_payload(operation: str = "add") -> dict[str, object]:
    payload: dict[str, object] = {
        "operation": operation,
        "context": encoded(b"context"),
        "public_key": encoded(b"public-key"),
        "ciphertext_a": encoded(b"left"),
        "ciphertext_b": encoded(b"right"),
    }
    if operation == "multiply":
        payload["evaluation_keys"] = encoded(b"mult-keys")
    return payload


class GpuContractTests(unittest.TestCase):
    def test_add_requires_and_passes_public_key(self) -> None:
        evaluator = FakeGpuEvaluator()
        response = evaluate_request(primitive_payload(), evaluator)
        self.assertEqual(
            evaluator.received,
            ("add", b"context", b"public-key", b"left", b"right", None, None),
        )
        self.assertEqual(base64.b64decode(response["ciphertext"]), b"gpu-result")

    def test_missing_public_key_is_rejected(self) -> None:
        payload = primitive_payload()
        del payload["public_key"]
        with self.assertRaisesRegex(RequestError, "public_key"):
            evaluate_request(payload, FakeGpuEvaluator())

    def test_secret_key_is_rejected(self) -> None:
        payload = primitive_payload()
        payload["secret_key"] = encoded(b"never-send-this")
        with self.assertRaisesRegex(RequestError, "unexpected fields"):
            evaluate_request(payload, FakeGpuEvaluator())

    def test_sum_uses_fides_rotation_keys(self) -> None:
        self.assertEqual(fides_sum_rotation_indices(8), [1, 2, 3, 4])
        self.assertEqual(
            fides_sum_rotation_indices(17), [1, 2, 3, 4, 8, 12, 16]
        )
        with tempfile.TemporaryDirectory() as directory:
            context_path = Path(directory) / "context.bin"
            write_fides_context_metadata(context_path, "sum", 17, 0)
            metadata = Path(str(context_path) + ".dev").read_text(encoding="utf-8")
        self.assertIn("RotationIndexes: { 1 2 3 4 8 12 16 }", metadata)
        self.assertIn("KeyDist: 1", metadata)

    def test_worker_adapter_stages_artifacts_and_reads_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            worker = Path(directory) / "fake-worker"
            worker.write_text(
                "#!/bin/sh\n"
                "set -eu\n"
                "output=\n"
                "while [ $# -gt 0 ]; do\n"
                "  if [ \"$1\" = --output ]; then output=$2; fi\n"
                "  shift 2\n"
                "done\n"
                "printf gpu-worker-result > \"$output\"\n",
                encoding="utf-8",
            )
            os.chmod(worker, 0o700)
            backend = FidesWorkerBackend(str(worker), device=0)
            result = backend.evaluate(
                "add", b"context", b"public", b"left", b"right", None, None
            )
        self.assertEqual(result, b"gpu-worker-result")

    def test_worker_failure_is_written_to_logs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            worker = Path(directory) / "fake-worker"
            worker.write_text(
                "#!/bin/sh\necho precise-worker-failure >&2\nexit 7\n",
                encoding="utf-8",
            )
            os.chmod(worker, 0o700)
            backend = FidesWorkerBackend(str(worker), device=0)
            with self.assertLogs("gpu.api.app", level="ERROR") as captured:
                with self.assertRaisesRegex(RequestError, "rejected"):
                    backend.evaluate(
                        "add", b"context", b"public", b"left", b"right", None, None
                    )
        self.assertIn("precise-worker-failure", "\n".join(captured.output))

    def test_native_demo_request_is_plaintext_but_executes_in_native_backend(self) -> None:
        evaluator = FakeNativeDemoEvaluator()
        response = evaluate_demo_request(
            {
                "operation": "add",
                "values_a": [12, 7, 8, 9],
                "values_b": [1, 2, 3, 4],
            },
            evaluator,
        )
        self.assertEqual(
            evaluator.received,
            ("add", [12.0, 7.0, 8.0, 9.0], [1.0, 2.0, 3.0, 4.0]),
        )
        self.assertEqual(response["values"], [13.0, 9.0, 11.0, 13.0])

    def test_native_demo_adapter_reads_cpp_json_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            worker = Path(directory) / "fake-demo-worker"
            worker.write_text(
                "#!/bin/sh\nprintf '%s\\n' 'GPU 0: Tesla T4'\nprintf '%s\\n' "
                "'{\"operation\":\"sum\",\"values\":[36.0]}'\n",
                encoding="utf-8",
            )
            os.chmod(worker, 0o700)
            backend = NativeDemoBackend(str(worker))
            result = backend.evaluate("sum", [12.0, 7.0, 8.0, 9.0], None)
        self.assertEqual(result, [36.0])

    def test_large_sum_request_uses_matching_contract(self) -> None:
        evaluator = FakeNativeDemoEvaluator()
        response = evaluate_demo_sum_request(
            {"values": [12, 7, 8, 9], "request_id": "gpu-sum"}, evaluator
        )
        self.assertEqual(evaluator.received_many, [12.0, 7.0, 8.0, 9.0])
        self.assertEqual(response["values"], [36.0])
        self.assertEqual(response["request_id"], "gpu-sum")

    def test_native_demo_large_sum_adapter_reads_timing_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            worker = Path(directory) / "fake-demo-worker"
            worker.write_text(
                "#!/bin/sh\nprintf '%s\\n' 'GPU 0: Tesla T4'\n"
                "printf '%s\\n' '{\"operation\":\"sum\",\"values\":[36.0],"
                "\"value_count\":4,\"batch_size\":8192,\"chunks\":1,"
                "\"timings\":{\"total_seconds\":0.2}}'\n",
                encoding="utf-8",
            )
            os.chmod(worker, 0o700)
            result = NativeDemoBackend(str(worker)).sum_many([12.0, 7.0, 8.0, 9.0])
        self.assertEqual(result["values"], [36.0])
        self.assertEqual(result["timings"]["total_seconds"], 0.2)


class GpuHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = create_server(
            "127.0.0.1", 0, FakeGpuEvaluator(), FakeNativeDemoEvaluator()
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_capabilities_describe_public_key_boundary(self) -> None:
        with urlopen(self.base_url + "/v1/capabilities", timeout=2) as response:
            payload = json.load(response)
        self.assertEqual(payload["backend"], "gpu-fides-test")
        self.assertTrue(payload["public_key_required_by_api"])
        self.assertFalse(payload["secret_key_required_by_api"])

    def test_http_rejects_secret_key(self) -> None:
        payload = primitive_payload()
        payload["secret_key"] = encoded(b"secret")
        request = Request(
            self.base_url + "/v1/evaluate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as caught:
            urlopen(request, timeout=2)
        self.assertEqual(caught.exception.code, 422)
        caught.exception.close()

    def test_native_demo_http_sum(self) -> None:
        request = Request(
            self.base_url + "/v1/demo/evaluate",
            data=json.dumps(
                {"operation": "sum", "values_a": [12, 7, 8, 9]}
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            payload = json.load(response)
        self.assertEqual(payload["backend"], "gpu-fides-native-test")
        self.assertEqual(payload["values"], [36.0])

    def test_large_sum_http_endpoint(self) -> None:
        request = Request(
            self.base_url + "/v1/demo/sum",
            data=json.dumps({"values": [12, 7, 8, 9]}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            payload = json.load(response)
        self.assertEqual(payload["backend"], "gpu-fides-native-test")
        self.assertEqual(payload["values"], [36.0])


if __name__ == "__main__":
    unittest.main()
