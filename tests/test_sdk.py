from __future__ import annotations

import unittest
from unittest import mock

from he_sdk import (
    BackendUnavailableError,
    CKKSConfig,
    CapabilitySet,
    EncryptedScalar,
    EncryptedVector,
    HESession,
    IncompatibleCiphertextError,
    OPERATION_CONTRACTS,
    SessionClosedError,
    UnsupportedOperationError,
)
from he_sdk.backends import create_backend
from he_sdk import smoke


class FakeBackend:
    name = "fake"
    engine_version = "fake-1"
    context_id = "context-a"
    key_bundle_id = "keys-a"
    capabilities = CapabilitySet(
        backend=name,
        schemes=("CKKS",),
        operations=(
            "add",
            "subtract",
            "multiply",
            "square",
            "sum",
            "mean",
            "variance",
        ),
    )

    def __init__(self) -> None:
        self.closed = False

    def encrypt(self, values: list[float]) -> list[float]:
        return list(values)

    def decrypt(self, encrypted: list[float], length: int) -> list[float]:
        return encrypted[:length]

    def add(self, left: list[float], right: list[float]) -> list[float]:
        return [a + b for a, b in zip(left, right)]

    def subtract(self, left: list[float], right: list[float]) -> list[float]:
        return [a - b for a, b in zip(left, right)]

    def multiply(self, left: list[float], right: list[float]) -> list[float]:
        return [a * b for a, b in zip(left, right)]

    def square(self, encrypted: list[float]) -> list[float]:
        return [value * value for value in encrypted]

    def sum(self, encrypted: list[float], valid_count: int) -> list[float]:
        return [sum(encrypted[:valid_count])]

    def mean(self, encrypted: list[float], valid_count: int) -> list[float]:
        return [sum(encrypted[:valid_count]) / valid_count]

    def variance(self, encrypted: list[float], valid_count: int) -> list[float]:
        values = encrypted[:valid_count]
        mean = sum(values) / valid_count
        return [sum((value - mean) ** 2 for value in values) / valid_count]

    def close(self) -> None:
        self.closed = True


class SDKContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = FakeBackend()
        self.session = HESession.from_backend(self.backend)

    def tearDown(self) -> None:
        self.session.close()

    def test_profile_has_stable_complete_identity(self) -> None:
        first = CKKSConfig.profile("ckks-balanced-v1")
        second = CKKSConfig.profile("ckks-balanced-v1")
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(first.multiplicative_depth, 3)
        self.assertEqual(first.security_level, "HEStd_128_classic")
        self.assertEqual(first.batch_size, 8192)
        self.assertEqual(
            tuple(OPERATION_CONTRACTS),
            ("add", "subtract", "multiply", "square", "sum", "mean", "variance"),
        )
        self.assertEqual(OPERATION_CONTRACTS["variance"].depth_cost, 2)

    def test_vector_functions_and_reductions(self) -> None:
        left = self.session.encrypt([1, 2, 3, 4])
        right = self.session.encrypt([4, 3, 2, 1])

        self.assertIsInstance(left, EncryptedVector)
        self.assertEqual(self.session.decrypt(self.session.add(left, right)), [5] * 4)
        self.assertEqual(
            self.session.decrypt(self.session.subtract(left, right)),
            [-3, -1, 1, 3],
        )
        self.assertEqual(
            self.session.decrypt(self.session.multiply(left, right)),
            [4, 6, 6, 4],
        )
        self.assertEqual(
            self.session.decrypt(self.session.square(left)),
            [1, 4, 9, 16],
        )
        encrypted_sum = self.session.sum(left)
        self.assertIsInstance(encrypted_sum, EncryptedScalar)
        self.assertEqual(self.session.decrypt(encrypted_sum), 10.0)
        self.assertEqual(self.session.decrypt(self.session.mean(left)), 2.5)
        self.assertEqual(self.session.decrypt(self.session.variance(left)), 1.25)

    def test_metadata_tracks_context_keys_layout_and_level(self) -> None:
        left = self.session.encrypt([1, 2])
        result = self.session.multiply(left, left)
        metadata = result.metadata
        self.assertEqual(metadata.context_id, "context-a")
        self.assertEqual(metadata.key_bundle_id, "keys-a")
        self.assertEqual(metadata.backend, "fake")
        self.assertEqual(metadata.scheme, "CKKS")
        self.assertEqual(metadata.packing_layout, "ckks-packed-contiguous-v1")
        self.assertEqual(metadata.valid_count, 2)
        self.assertEqual(metadata.level, 1)
        self.assertEqual(metadata.logical_shape, (2,))

    def test_rejects_values_outside_profile_range(self) -> None:
        with self.assertRaisesRegex(ValueError, "values must be in"):
            self.session.encrypt([40001])

    def test_rejects_mixed_sessions_and_shapes(self) -> None:
        first = self.session.encrypt([1, 2])
        other_backend = FakeBackend()
        other_backend.context_id = "context-b"
        other = HESession.from_backend(other_backend)
        try:
            second = other.encrypt([3, 4])
            with self.assertRaisesRegex(IncompatibleCiphertextError, "session"):
                self.session.add(first, second)
        finally:
            other.close()

        wrong_shape = self.session.encrypt([1])
        with self.assertRaisesRegex(IncompatibleCiphertextError, "equal logical"):
            self.session.add(first, wrong_shape)

    def test_depth_budget_is_enforced_before_backend_call(self) -> None:
        value = self.session.encrypt([2])
        value = self.session.square(value)
        value = self.session.square(value)
        value = self.session.square(value)
        with self.assertRaisesRegex(IncompatibleCiphertextError, "allows 3"):
            self.session.square(value)

    def test_unsupported_operation_is_explicit(self) -> None:
        self.backend.capabilities = CapabilitySet(
            backend="fake", schemes=("CKKS",), operations=("add",)
        )
        value = self.session.encrypt([1])
        with self.assertRaises(UnsupportedOperationError):
            self.session.square(value)

    def test_close_is_idempotent_and_blocks_use(self) -> None:
        self.session.close()
        self.session.close()
        self.assertTrue(self.backend.closed)
        with self.assertRaises(SessionClosedError):
            self.session.encrypt([1])

    def test_fides_is_not_silently_routed_to_cpu(self) -> None:
        with self.assertRaisesRegex(BackendUnavailableError, "he-sdk-fides"):
            create_backend("fides", CKKSConfig.profile("ckks-balanced-v1"))

    def test_sdk_smoke_uses_all_first_release_operations(self) -> None:
        with mock.patch.object(
            smoke.HESession,
            "create",
            return_value=HESession.from_backend(FakeBackend()),
        ):
            result = smoke.run()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(
            result["operations"],
            [
                "add",
                "subtract",
                "multiply",
                "square",
                "sum",
                "mean",
                "variance",
            ],
        )


if __name__ == "__main__":
    unittest.main()
