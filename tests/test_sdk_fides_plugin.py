"""Dependency-free contract tests for the optional FIDES Python adapter."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from he_sdk import (
    BackendUnavailableError,
    CKKSConfig,
    HESession,
)


REPOSITORY = Path(__file__).resolve().parents[1]
BACKEND_SOURCE = (
    REPOSITORY
    / "gpu"
    / "he_sdk_fides"
    / "src"
    / "he_sdk_fides"
    / "backend.py"
)


def load_backend_module():
    spec = importlib.util.spec_from_file_location(
        "he_sdk_fides_backend_under_test", BACKEND_SOURCE
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load FIDES backend source")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeNativeSession:
    def __init__(self, **parameters: int) -> None:
        self.parameters = parameters
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


class FidesPluginAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_backend_module()
        self.native_module = SimpleNamespace(
            __engine_version__="fides-test",
            NativeSession=FakeNativeSession,
        )

    def create_backend(self):
        with patch.object(
            self.module.importlib,
            "import_module",
            return_value=self.native_module,
        ):
            return self.module.FidesBackend(
                CKKSConfig.profile("ckks-balanced-v1")
            )

    def test_adapter_supports_the_complete_sdk_contract(self) -> None:
        backend = self.create_backend()
        native = backend._native
        self.assertEqual(backend.name, "fides")
        self.assertEqual(backend.engine_version, "fides-test")
        self.assertEqual(native.parameters["batch_size"], 8192)

        with HESession.from_backend(backend) as session:
            left = session.encrypt([1.0, 2.0, 3.0, 4.0])
            right = session.encrypt([4.0, 3.0, 2.0, 1.0])
            self.assertEqual(session.decrypt(session.add(left, right)), [5.0] * 4)
            self.assertEqual(
                session.decrypt(session.subtract(left, right)),
                [-3.0, -1.0, 1.0, 3.0],
            )
            self.assertEqual(
                session.decrypt(session.multiply(left, right)),
                [4.0, 6.0, 6.0, 4.0],
            )
            self.assertEqual(
                session.decrypt(session.square(left)),
                [1.0, 4.0, 9.0, 16.0],
            )
            self.assertEqual(session.decrypt(session.sum(left)), 10.0)
            self.assertEqual(session.decrypt(session.mean(left)), 2.5)
            self.assertEqual(session.decrypt(session.variance(left)), 1.25)

        self.assertTrue(native.closed)

    def test_adapter_rejects_untested_profile_variants(self) -> None:
        with self.assertRaisesRegex(ValueError, "custom rotation_indices"):
            self.module.FidesBackend(CKKSConfig(rotation_indices=(1,)))

    def test_missing_native_extension_is_explicit(self) -> None:
        with (
            patch.object(
                self.module.importlib,
                "import_module",
                side_effect=ImportError("not installed"),
            ),
            self.assertRaisesRegex(
                BackendUnavailableError, "native extension is unavailable"
            ),
        ):
            self.module.FidesBackend(CKKSConfig.profile("ckks-balanced-v1"))

    def test_cuda_initialization_failure_is_explicit(self) -> None:
        failing_native = SimpleNamespace(
            __engine_version__="fides-test",
            NativeSession=lambda **_: (_ for _ in ()).throw(
                RuntimeError("no CUDA device")
            ),
        )
        with (
            patch.object(
                self.module.importlib,
                "import_module",
                return_value=failing_native,
            ),
            self.assertRaisesRegex(
                BackendUnavailableError, "could not initialize CUDA device 0"
            ),
        ):
            self.module.FidesBackend(CKKSConfig.profile("ckks-balanced-v1"))


if __name__ == "__main__":
    unittest.main()
