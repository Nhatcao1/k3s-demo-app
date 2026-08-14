from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from he_sdk import BackendUnavailableError, CKKSConfig
from he_sdk.backends.openfhe import OpenFHEBackend


class OpenFHEAdapterTests(unittest.TestCase):
    @staticmethod
    def module() -> SimpleNamespace:
        return SimpleNamespace(
            __version__="test-1.5.1",
            ClearEvalMultKeys=MagicMock(),
            ClearEvalAutomorphismKeys=MagicMock(),
            ReleaseAllContexts=MagicMock(),
        )

    def test_adapter_reuses_openfhe_cpu_runtime(self) -> None:
        module = self.module()
        with (
            patch("he_sdk.backends.openfhe.OpenFHECPU") as runtime_type,
            patch(
                "he_sdk.backends.openfhe.importlib.import_module",
                return_value=module,
            ),
        ):
            runtime = runtime_type.return_value
            runtime.encrypt.return_value = "encrypted"
            runtime.add.return_value = "added"
            runtime.decrypt.return_value = [3.0]

            backend = OpenFHEBackend(CKKSConfig.profile("ckks-balanced-v1"))
            try:
                self.assertEqual(backend.encrypt([1.0]), "encrypted")
                self.assertEqual(backend.add("left", "right"), "added")
                self.assertEqual(backend.decrypt("added", 1), [3.0])
                runtime_type.assert_called_once_with(module)
                runtime.add.assert_called_once_with("left", "right")
            finally:
                backend.close()

        module.ClearEvalMultKeys.assert_called_once_with()
        module.ClearEvalAutomorphismKeys.assert_called_once_with()
        module.ReleaseAllContexts.assert_called_once_with()

    def test_process_global_state_allows_only_one_active_session(self) -> None:
        module = self.module()
        with (
            patch("he_sdk.backends.openfhe.OpenFHECPU"),
            patch(
                "he_sdk.backends.openfhe.importlib.import_module",
                return_value=module,
            ),
        ):
            first = OpenFHEBackend(CKKSConfig.profile("ckks-balanced-v1"))
            try:
                with self.assertRaisesRegex(
                    BackendUnavailableError, "Only one local OpenFHE"
                ):
                    OpenFHEBackend(CKKSConfig.profile("ckks-balanced-v1"))
            finally:
                first.close()

    def test_rejects_unimplemented_profile_variants(self) -> None:
        with self.assertRaisesRegex(ValueError, "custom rotation_indices"):
            OpenFHEBackend(CKKSConfig(rotation_indices=(1, 2)))


if __name__ == "__main__":
    unittest.main()
