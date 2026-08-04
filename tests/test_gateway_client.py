from __future__ import annotations

import json
import threading
import unittest
from urllib.request import urlopen

from gateway.app import PublicOperand, create_server
from he_client import (
    HEClient,
    HEClientError,
    PublicScalar,
    PublicVector,
)


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
        right: str | PublicOperand | None,
    ) -> str:
        self.operations.append(operation)
        left = self.sessions[session_id][left_id]
        if operation == "sum":
            return self._store(session_id, [sum(left)])
        if operation == "mean":
            return self._store(session_id, [sum(left) / len(left)])
        if operation == "square":
            return self._store(session_id, [value * value for value in left])
        if right is None:
            raise AssertionError(f"{operation} requires a right operand")
        if isinstance(right, str):
            right_values = self.sessions[session_id][right]
        elif right.kind == "public_vector":
            right_values = list(right.values)
        else:
            right_values = [right.values[0]] * len(left)
        functions = {
            "add": lambda a, b: a + b,
            "subtract": lambda a, b: a - b,
            "multiply": lambda a, b: a * b,
        }
        result = [
            functions[operation](a, b)
            for a, b in zip(left, right_values, strict=True)
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
            host="127.0.0.1",
            port=0,
            crypto=self.crypto,
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
            [
                "add",
                "subtract",
                "multiply",
                "square",
                "sum",
                "mean",
            ],
        )
        self.assertEqual(
            payload["public_operands"],
            ["public_vector", "public_scalar"],
        )
        self.assertEqual(
            payload["composite_operations"],
            [
                "variance_components",
                "covariance_components",
                "correlation_components",
                "weighted_sum",
                "risk_score",
            ],
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

    def test_public_operands_and_square(self) -> None:
        with HEClient(self.base_url) as he:
            encrypted = he.encrypt([2, 4, 6])
            public = PublicVector([1, 2, 3])

            self.assertEqual((encrypted + public).decrypt(), [3, 6, 9])
            self.assertEqual(
                (encrypted - PublicScalar(1)).decrypt(),
                [1, 3, 5],
            )
            self.assertEqual((encrypted * public).decrypt(), [2, 8, 18])
            self.assertEqual(encrypted.square().decrypt(), [4, 16, 36])
            self.assertEqual(he.square(encrypted).decrypt(), [4, 16, 36])

    def test_easy_analytics_components_and_scores(self) -> None:
        with HEClient(self.base_url) as he:
            left = he.encrypt([2, 4, 6, 8])
            right = he.encrypt([1, 3, 5, 7])

            variance = he.variance_components(left)
            self.assertEqual(variance.sum_x.decrypt(), [20])
            self.assertEqual(variance.sum_x_square.decrypt(), [120])
            self.assertEqual(variance.count, 4)

            covariance = he.covariance_components(left, right)
            self.assertEqual(covariance.sum_x.decrypt(), [20])
            self.assertEqual(covariance.sum_y.decrypt(), [16])
            self.assertEqual(covariance.sum_xy.decrypt(), [100])
            self.assertEqual(covariance.count, 4)

            correlation = he.correlation_components(left, right)
            self.assertEqual(correlation.sum_x.decrypt(), [20])
            self.assertEqual(correlation.sum_y.decrypt(), [16])
            self.assertEqual(correlation.sum_x_square.decrypt(), [120])
            self.assertEqual(correlation.sum_y_square.decrypt(), [84])
            self.assertEqual(correlation.sum_xy.decrypt(), [100])
            self.assertEqual(correlation.count, 4)

            weights = PublicVector([0.1, 0.2, 0.3, 0.4])
            self.assertAlmostEqual(
                he.weighted_sum(left, weights).decrypt()[0], 6.0
            )
            self.assertAlmostEqual(
                he.risk_score(
                    left,
                    weights,
                    PublicScalar(1.5),
                ).decrypt()[0],
                7.5,
            )

    def test_public_vector_length_is_checked_locally(self) -> None:
        with HEClient(self.base_url) as he:
            encrypted = he.encrypt([1, 2, 3])
            with self.assertRaisesRegex(
                HEClientError, "must match ciphertext logical length"
            ):
                he.add(encrypted, PublicVector([1, 2]))

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
