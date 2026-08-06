from __future__ import annotations

import base64
import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from api.app import (
    RequestError,
    create_server,
    evaluate_demo_sum_request,
    evaluate_request,
)
class FakeEvaluator:
    backend_name = "test-backend"
    serialization = "test-bytes-base64"
    ready = True

    def evaluate(
        self,
        operation: str,
        context: bytes,
        ciphertext_a: bytes,
        ciphertext_b: bytes | None,
        evaluation_keys: bytes | None,
        valid_count: int | None,
    ) -> bytes:
        self.received = (
            operation,
            context,
            ciphertext_a,
            ciphertext_b,
            evaluation_keys,
            valid_count,
        )
        return b"encrypted-result"


class FakeDemoSumEvaluator:
    backend_name = "cpu-openfhe-demo-test"
    ready = True

    def sum_values(self, values: list[float]) -> dict[str, object]:
        self.received = values
        return {
            "operation": "sum",
            "values": [sum(values)],
            "value_count": len(values),
            "batch_size": 8192,
            "chunks": 1,
            "timings": {"total_seconds": 0.1},
        }


def encoded(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def primitive_payload(operation: str = "add") -> dict[str, object]:
    payload: dict[str, object] = {
        "operation": operation,
        "context": encoded(b"context"),
        "ciphertext_a": encoded(b"left"),
        "ciphertext_b": encoded(b"right"),
    }
    if operation == "multiply":
        payload["evaluation_keys"] = encoded(b"mult-keys")
    return payload


class EvaluateRequestTests(unittest.TestCase):
    def test_add_decodes_inputs_and_encodes_result(self) -> None:
        evaluator = FakeEvaluator()
        result = evaluate_request(primitive_payload(), evaluator)
        self.assertEqual(
            evaluator.received,
            ("add", b"context", b"left", b"right", None, None),
        )
        self.assertEqual(base64.b64decode(result["ciphertext"]), b"encrypted-result")
        self.assertEqual(result["backend"], "test-backend")

    def test_multiply_requires_evaluation_keys(self) -> None:
        payload = primitive_payload("multiply")
        del payload["evaluation_keys"]
        with self.assertRaisesRegex(RequestError, "evaluation_keys"):
            evaluate_request(payload, FakeEvaluator())

    def test_sum_uses_keys_and_valid_count(self) -> None:
        evaluator = FakeEvaluator()
        result = evaluate_request(
            {
                "operation": "sum",
                "context": encoded(b"context"),
                "ciphertext_a": encoded(b"values"),
                "evaluation_keys": encoded(b"sum-keys"),
                "valid_count": 8192,
                "request_id": "sum-8192",
            },
            evaluator,
        )
        self.assertEqual(
            evaluator.received,
            ("sum", b"context", b"values", None, b"sum-keys", 8192),
        )
        self.assertEqual(result["request_id"], "sum-8192")

    def test_rejects_secret_key(self) -> None:
        payload = primitive_payload()
        payload["secret_key"] = encoded(b"must-not-be-accepted")
        with self.assertRaisesRegex(RequestError, "unexpected fields"):
            evaluate_request(payload, FakeEvaluator())

    def test_demo_sum_has_matching_benchmark_contract(self) -> None:
        evaluator = FakeDemoSumEvaluator()
        result = evaluate_demo_sum_request(
            {"values": [12, 7, 8, 9], "request_id": "cpu-sum"}, evaluator
        )
        self.assertEqual(evaluator.received, [12.0, 7.0, 8.0, 9.0])
        self.assertEqual(result["values"], [36.0])
        self.assertEqual(result["request_id"], "cpu-sum")


class HttpApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = create_server(
            host="127.0.0.1",
            port=0,
            evaluator=FakeEvaluator(),
            demo_sum_evaluator=FakeDemoSumEvaluator(),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def get_json(self, path: str) -> tuple[int, dict[str, object]]:
        with urlopen(self.base_url + path, timeout=2) as response:
            return response.status, json.load(response)

    def post(
        self, payload: dict[str, object], path: str = "/v1/evaluate"
    ) -> dict[str, object]:
        request = Request(
            self.base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            return json.load(response)

    def test_health_ready_and_capabilities(self) -> None:
        self.assertEqual(self.get_json("/healthz")[0], 200)
        self.assertEqual(self.get_json("/readyz")[0], 200)
        status, payload = self.get_json("/v1/capabilities")
        self.assertEqual(status, 200)
        self.assertEqual(payload["operations"], ["add", "subtract", "multiply", "sum"])
        self.assertEqual(payload["backend"], "test-backend")
        self.assertFalse(payload["secret_key_required_by_api"])

    def test_evaluate_endpoint(self) -> None:
        result = self.post(primitive_payload("subtract"))
        self.assertEqual(result["operation"], "subtract")
        self.assertEqual(base64.b64decode(result["ciphertext"]), b"encrypted-result")

    def test_demo_sum_endpoint(self) -> None:
        result = self.post({"values": [12, 7, 8, 9]}, "/v1/demo/sum")
        self.assertEqual(result["backend"], "cpu-openfhe-demo-test")
        self.assertEqual(result["values"], [36.0])

    def test_rejects_secret_key_field(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
