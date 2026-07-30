from __future__ import annotations

import base64
import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from api.app import RequestError, create_server, evaluate_add_request


class FakeAdder:
    ready = True

    def add(self, context: bytes, ciphertext_a: bytes, ciphertext_b: bytes) -> bytes:
        self.received = (context, ciphertext_a, ciphertext_b)
        return b"encrypted-sum"


def encoded(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


class EvaluateAddRequestTests(unittest.TestCase):
    def test_decodes_inputs_and_encodes_result(self) -> None:
        evaluator = FakeAdder()
        result = evaluate_add_request(
            {
                "context": encoded(b"context"),
                "ciphertext_a": encoded(b"left"),
                "ciphertext_b": encoded(b"right"),
            },
            evaluator,
        )

        self.assertEqual(evaluator.received, (b"context", b"left", b"right"))
        self.assertEqual(base64.b64decode(result["ciphertext"]), b"encrypted-sum")

    def test_rejects_unexpected_fields(self) -> None:
        with self.assertRaisesRegex(RequestError, "unexpected fields"):
            evaluate_add_request(
                {
                    "context": encoded(b"context"),
                    "ciphertext_a": encoded(b"left"),
                    "ciphertext_b": encoded(b"right"),
                    "secret_key": encoded(b"must-not-be-accepted"),
                },
                FakeAdder(),
            )

    def test_rejects_invalid_base64(self) -> None:
        with self.assertRaisesRegex(RequestError, "not valid base64"):
            evaluate_add_request(
                {
                    "context": "!!!",
                    "ciphertext_a": encoded(b"left"),
                    "ciphertext_b": encoded(b"right"),
                },
                FakeAdder(),
            )


class HttpApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = create_server(host="127.0.0.1", port=0, evaluator=FakeAdder())
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def get_json(self, path: str) -> tuple[int, dict[str, object]]:
        with urlopen(self.base_url + path, timeout=2) as response:
            return response.status, json.load(response)

    def test_health_ready_and_capabilities(self) -> None:
        self.assertEqual(self.get_json("/healthz")[0], 200)
        self.assertEqual(self.get_json("/readyz")[0], 200)
        status, payload = self.get_json("/v1/capabilities")
        self.assertEqual(status, 200)
        self.assertEqual(payload["operations"], ["ciphertext_add"])
        self.assertFalse(payload["secret_key_required_by_api"])

    def test_add_endpoint(self) -> None:
        payload = {
            "context": encoded(b"context"),
            "ciphertext_a": encoded(b"left"),
            "ciphertext_b": encoded(b"right"),
        }
        request = Request(
            self.base_url + "/v1/add",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            result = json.load(response)
        self.assertEqual(base64.b64decode(result["ciphertext"]), b"encrypted-sum")

    def test_rejects_secret_key_field(self) -> None:
        payload = {
            "context": encoded(b"context"),
            "ciphertext_a": encoded(b"left"),
            "ciphertext_b": encoded(b"right"),
            "secret_key": encoded(b"secret"),
        }
        request = Request(
            self.base_url + "/v1/add",
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
