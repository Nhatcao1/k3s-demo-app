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
    evaluate_demo_request,
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
        plaintext_b: float | tuple[float, ...] | None,
        multiplication_keys: bytes | None,
        rotation_keys: bytes | None,
        valid_count: int | None,
    ) -> bytes:
        self.received = (
            operation,
            context,
            ciphertext_a,
            ciphertext_b,
            plaintext_b,
            multiplication_keys,
            rotation_keys,
            valid_count,
        )
        return b"encrypted-result"


class FakeDemoEvaluator:
    backend_name = "cpu-openfhe-native-test"
    ready = True

    def evaluate(
        self,
        operation: str,
        values_a: list[float],
        values_b: list[float] | None,
    ) -> list[float]:
        self.received = (operation, values_a, values_b)
        if operation == "square":
            return [value * value for value in values_a]
        if operation == "sum":
            return [sum(values_a)]
        if operation == "mean":
            return [sum(values_a) / len(values_a)]
        if operation == "variance":
            mean = sum(values_a) / len(values_a)
            return [sum((value - mean) ** 2 for value in values_a) / len(values_a)]
        assert values_b is not None
        if operation == "multiply_plain":
            return [left * right for left, right in zip(values_a, values_b)]
        return [left + right for left, right in zip(values_a, values_b)]


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
            ("add", b"context", b"left", b"right", None, None, None, None),
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
            (
                "sum", b"context", b"values", None, None,
                None, b"sum-keys", 8192,
            ),
        )
        self.assertEqual(result["request_id"], "sum-8192")

    def test_multiply_plain_accepts_scalar_without_evaluation_key(self) -> None:
        evaluator = FakeEvaluator()
        evaluate_request(
            {
                "operation": "multiply_plain",
                "context": encoded(b"context"),
                "ciphertext_a": encoded(b"values"),
                "plaintext_b": 0.8,
            },
            evaluator,
        )
        self.assertEqual(
            evaluator.received,
            (
                "multiply_plain", b"context", b"values", None, 0.8,
                None, None, None,
            ),
        )

    def test_multiply_plain_accepts_finite_vector(self) -> None:
        evaluator = FakeEvaluator()
        evaluate_request(
            {
                "operation": "multiply_plain",
                "context": encoded(b"context"),
                "ciphertext_a": encoded(b"values"),
                "plaintext_b": [0.8, 0.9],
            },
            evaluator,
        )
        self.assertEqual(evaluator.received[4], (0.8, 0.9))

    def test_multiply_plain_rejects_ciphertext_or_nonfinite_value(self) -> None:
        payload = {
            "operation": "multiply_plain",
            "context": encoded(b"context"),
            "ciphertext_a": encoded(b"values"),
            "ciphertext_b": encoded(b"not-accepted"),
            "plaintext_b": 0.8,
        }
        with self.assertRaisesRegex(RequestError, "ciphertext_b"):
            evaluate_request(payload, FakeEvaluator())
        del payload["ciphertext_b"]
        payload["plaintext_b"] = float("inf")
        with self.assertRaisesRegex(RequestError, "finite"):
            evaluate_request(payload, FakeEvaluator())

    def test_rejects_secret_key(self) -> None:
        payload = primitive_payload()
        payload["secret_key"] = encoded(b"must-not-be-accepted")
        with self.assertRaisesRegex(RequestError, "unexpected fields"):
            evaluate_request(payload, FakeEvaluator())

    def test_square_mean_and_variance_contracts(self) -> None:
        evaluator = FakeEvaluator()
        square = primitive_payload("square")
        del square["ciphertext_b"]
        square["evaluation_keys"] = encoded(b"mult-keys")
        evaluate_request(square, evaluator)
        self.assertEqual(
            evaluator.received,
            (
                "square", b"context", b"left", None, None,
                b"mult-keys", None, None,
            ),
        )

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
        self.assertEqual(evaluator.received[-2:], (b"rotation-keys", 4))

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
            evaluator.received[-3:],
            (b"mult-keys", b"rotation-keys", 4),
        )

    def test_demo_exposes_square_mean_and_variance(self) -> None:
        evaluator = FakeDemoEvaluator()
        for operation, expected in (
            ("square", [1.0, 4.0, 9.0, 16.0]),
            ("mean", [2.5]),
            ("variance", [1.25]),
        ):
            result = evaluate_demo_request(
                {"operation": operation, "values_a": [1, 2, 3, 4]},
                evaluator,
            )
            self.assertEqual(result["values"], expected)


class HttpApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = create_server(
            host="127.0.0.1",
            port=0,
            evaluator=FakeEvaluator(),
            demo_evaluator=FakeDemoEvaluator(),
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
        self,
        payload: dict[str, object],
        path: str = "/v1/evaluate",
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
            [
                "add", "subtract", "multiply", "multiply_plain",
                "square", "sum", "mean", "variance",
            ],
        )
        self.assertEqual(payload["backend"], "test-backend")
        self.assertFalse(payload["secret_key_required_by_api"])

    def test_evaluate_endpoint(self) -> None:
        result = self.post(primitive_payload("subtract"))
        self.assertEqual(result["operation"], "subtract")
        self.assertEqual(base64.b64decode(result["ciphertext"]), b"encrypted-result")

    def test_demo_mean_endpoint(self) -> None:
        result = self.post(
            {"operation": "mean", "values_a": [1, 2, 3, 4]},
            "/v1/demo/evaluate",
        )
        self.assertEqual(result["values"], [2.5])

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
