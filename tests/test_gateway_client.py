from __future__ import annotations

import json
import threading
import unittest
from urllib.request import urlopen

from gateway.app import create_server
from he_client import HEClient, HEClientError


class FakeGatewayCrypto:
    ready = True

    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, list[float]]] = {}
        self.next_session = 0
        self.next_ciphertext = 0
        self.operations: list[str] = []

    def _store(self, session_id: str, values: list[float]) -> str:
        self.next_ciphertext += 1
        ciphertext_id = f"ciphertext-{self.next_ciphertext}"
        self.sessions[session_id][ciphertext_id] = values
        return ciphertext_id

    def create_session(
        self, values: list[float], multiplicative_depth: int
    ) -> tuple[str, str]:
        self.next_session += 1
        session_id = f"session-{self.next_session}"
        self.sessions[session_id] = {}
        return session_id, self._store(session_id, values)

    def encrypt(self, session_id: str, values: list[float]) -> str:
        return self._store(session_id, values)

    def evaluate(
        self,
        session_id: str,
        operation: str,
        left_id: str,
        right_id: str | None,
    ) -> str:
        self.operations.append(operation)
        left = self.sessions[session_id][left_id]
        if operation == "sum":
            return self._store(session_id, [sum(left)])
        if operation == "mean":
            return self._store(session_id, [sum(left) / len(left)])
        if right_id is None:
            raise AssertionError(f"{operation} requires a right ciphertext")
        right = self.sessions[session_id][right_id]
        functions = {
            "add": lambda a, b: a + b,
            "subtract": lambda a, b: a - b,
            "multiply": lambda a, b: a * b,
        }
        result = [
            functions[operation](a, b)
            for a, b in zip(left, right, strict=True)
        ]
        return self._store(session_id, result)

    def decrypt(self, session_id: str, ciphertext_id: str) -> list[float]:
        return self.sessions[session_id][ciphertext_id]

    def delete_session(self, session_id: str) -> None:
        del self.sessions[session_id]


class GatewayClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.crypto = FakeGatewayCrypto()
        self.server = create_server(
            host="127.0.0.1", port=0, crypto=self.crypto
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_capabilities_list_composable_operations(self) -> None:
        with urlopen(
            self.base_url + "/v1/capabilities", timeout=2
        ) as response:
            payload = json.load(response)
        self.assertEqual(
            payload["operations"],
            ["add", "subtract", "multiply", "sum", "mean"],
        )
        self.assertFalse(payload["client_openfhe_required"])

    def test_operator_expression_uses_one_session(self) -> None:
        with HEClient(self.base_url) as he:
            left = he.encrypt([1, 2, 3])
            right = he.encrypt([10, 20, 30])
            result = (left + right) * right
            self.assertEqual(result.decrypt(), [110, 440, 990])

        self.assertEqual(self.crypto.operations, ["add", "multiply"])
        self.assertEqual(self.crypto.sessions, {})

    def test_sum_and_mean_reduce_an_expression(self) -> None:
        with HEClient(self.base_url) as he:
            installment = he.encrypt([12, 25, 41])
            payment = he.encrypt([10, 20, 30])
            difference = installment - payment
            self.assertEqual(difference.sum().decrypt(), [18])
            self.assertEqual(difference.mean().decrypt(), [6])
            self.assertEqual(he.sum(difference).decrypt(), [18])
            self.assertEqual(he.mean(difference).decrypt(), [6])

        self.assertEqual(
            self.crypto.operations,
            ["subtract", "sum", "mean", "sum", "mean"],
        )

    def test_subtraction_method_and_operator(self) -> None:
        with HEClient(self.base_url) as he:
            left = he.encrypt([10, 20])
            right = he.encrypt([1, 2])
            self.assertEqual((left - right).decrypt(), [9, 18])
            self.assertEqual(he.subtract(left, right).decrypt(), [9, 18])

    def test_rejects_ciphertext_from_another_client(self) -> None:
        with HEClient(self.base_url) as first, HEClient(
            self.base_url
        ) as second:
            left = first.encrypt([1])
            right = second.encrypt([2])
            with self.assertRaisesRegex(
                HEClientError, "must belong to this HEClient"
            ):
                first.add(left, right)


if __name__ == "__main__":
    unittest.main()
