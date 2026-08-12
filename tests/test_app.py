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
    evaluate_bgv_demo_request,
    evaluate_demo_request,
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
        multiplication_keys: bytes | None,
        rotation_keys: bytes | None,
        valid_count: int | None,
    ) -> bytes:
        self.received = (
            operation,
            context,
            ciphertext_a,
            ciphertext_b,
            multiplication_keys,
            rotation_keys,
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


class FakeDemoEvaluator:
    backend_name = "cpu-openfhe-native-test"
    ready = True

    def evaluate(
        self,
        operation: str,
        values_a: list[float],
        values_b: list[float] | None,
    ) -> dict[str, object]:
        self.received = (operation, values_a, values_b)
        if operation == "sum":
            values = [sum(values_a)]
        elif operation == "mean":
            values = [sum(values_a) / len(values_a)]
        elif operation == "variance":
            mean = sum(values_a) / len(values_a)
            values = [
                sum((value - mean) ** 2 for value in values_a) / len(values_a)
            ]
        elif operation == "square":
            values = [value * value for value in values_a]
        else:
            assert values_b is not None
            values = [left + right for left, right in zip(values_a, values_b)]
        return {
            "values": values,
            "timings": {
                "context_keygen_seconds": 0.04,
                "encrypt_seconds": 0.03,
                "calculation_seconds": 0.02,
                "decrypt_seconds": 0.01,
                "total_seconds": 0.1,
            },
        }


class FakeBGVDemoEvaluator:
    backend_name = "cpu-openfhe-bgv-test"
    ready = True

    def evaluate_multiply(
        self, values_a: list[int], values_b: list[int]
    ) -> dict[str, object]:
        self.received = (values_a, values_b)
        return {
            "values": [left * right for left, right in zip(values_a, values_b)],
            "plaintext_modulus": 4_000_350_209,
            "timings": {
                "context_keygen_seconds": 0.04,
                "encrypt_seconds": 0.03,
                "calculation_seconds": 0.02,
                "decrypt_seconds": 0.01,
                "total_seconds": 0.1,
            },
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
    if operation in ("multiply", "square"):
        payload["evaluation_keys"] = encoded(b"mult-keys")
    if operation == "square":
        del payload["ciphertext_b"]
    return payload


class EvaluateRequestTests(unittest.TestCase):
    def test_add_decodes_inputs_and_encodes_result(self) -> None:
        evaluator = FakeEvaluator()
        result = evaluate_request(primitive_payload(), evaluator)
        self.assertEqual(
            evaluator.received,
            ("add", b"context", b"left", b"right", None, None, None),
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
            ("sum", b"context", b"values", None, None, b"sum-keys", 8192),
        )
        self.assertEqual(result["request_id"], "sum-8192")

    def test_square_is_unary_and_uses_multiplication_keys(self) -> None:
        evaluator = FakeEvaluator()
        evaluate_request(primitive_payload("square"), evaluator)
        self.assertEqual(
            evaluator.received,
            ("square", b"context", b"left", None, b"mult-keys", None, None),
        )

    def test_mean_uses_rotation_keys_and_valid_count(self) -> None:
        evaluator = FakeEvaluator()
        evaluate_request(
            {
                "operation": "mean",
                "context": encoded(b"context"),
                "ciphertext_a": encoded(b"values"),
                "evaluation_keys": encoded(b"rotation-keys"),
                "valid_count": 4,
            },
            evaluator,
        )
        self.assertEqual(
            evaluator.received,
            ("mean", b"context", b"values", None, None, b"rotation-keys", 4),
        )

    def test_variance_requires_both_key_bundles(self) -> None:
        evaluator = FakeEvaluator()
        evaluate_request(
            {
                "operation": "variance",
                "context": encoded(b"context"),
                "ciphertext_a": encoded(b"values"),
                "multiplication_keys": encoded(b"mult-keys"),
                "rotation_keys": encoded(b"rotation-keys"),
                "valid_count": 4,
            },
            evaluator,
        )
        self.assertEqual(
            evaluator.received,
            (
                "variance", b"context", b"values", None, b"mult-keys",
                b"rotation-keys", 4,
            ),
        )

    def test_variance_demo_is_population_variance(self) -> None:
        result = evaluate_demo_request(
            {"operation": "variance", "values_a": [1, 2, 3, 4]},
            FakeDemoEvaluator(),
        )
        self.assertEqual(result["values"], [1.25])
        self.assertEqual(result["evaluation_seconds"], 0.02)
        self.assertEqual(result["timings"]["encrypt_seconds"], 0.03)

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

    def test_bgv_demo_requires_integer_multiply(self) -> None:
        result = evaluate_bgv_demo_request(
            {
                "operation": "multiply",
                "values_a": [1, 2],
                "values_b": [1000000000, 1000000000],
            },
            FakeBGVDemoEvaluator(),
        )
        self.assertEqual(result["scheme"], "BGV")
        self.assertEqual(result["values"], [1000000000, 2000000000])
        self.assertEqual(result["evaluation_seconds"], 0.02)

    def test_bgv_demo_rejects_decimal_input(self) -> None:
        with self.assertRaisesRegex(RequestError, "only integers"):
            evaluate_bgv_demo_request(
                {
                    "operation": "multiply",
                    "values_a": [1.5],
                    "values_b": [2],
                },
                FakeBGVDemoEvaluator(),
            )


class HttpApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = create_server(
            host="127.0.0.1",
            port=0,
            evaluator=FakeEvaluator(),
            demo_evaluator=FakeDemoEvaluator(),
            demo_sum_evaluator=FakeDemoSumEvaluator(),
            bgv_demo_evaluator=FakeBGVDemoEvaluator(),
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
        self.assertEqual(
            payload["operations"],
            ["add", "subtract", "multiply", "square", "sum", "mean", "variance"],
        )
        self.assertEqual(payload["backend"], "test-backend")
        self.assertFalse(payload["secret_key_required_by_api"])
        self.assertIn("encrypt_seconds", payload["demo_timing_fields"])
        self.assertEqual(payload["demo_schemes"], ["CKKS", "BGV"])
        self.assertEqual(payload["bgv_demo_endpoint"], "/v1/demo/bgv/evaluate")

    def test_evaluate_endpoint(self) -> None:
        result = self.post(primitive_payload("subtract"))
        self.assertEqual(result["operation"], "subtract")
        self.assertEqual(base64.b64decode(result["ciphertext"]), b"encrypted-result")

    def test_demo_sum_endpoint(self) -> None:
        result = self.post({"values": [12, 7, 8, 9]}, "/v1/demo/sum")
        self.assertEqual(result["backend"], "cpu-openfhe-demo-test")
        self.assertEqual(result["values"], [36.0])

    def test_bgv_demo_endpoint(self) -> None:
        result = self.post(
            {
                "operation": "multiply",
                "values_a": [1, 2],
                "values_b": [10, 10],
            },
            "/v1/demo/bgv/evaluate",
        )
        self.assertEqual(result["scheme"], "BGV")
        self.assertEqual(result["values"], [10, 20])

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
