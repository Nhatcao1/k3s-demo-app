from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path
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
            runtime.create_result_recipient.return_value = (
                "analyst-public",
                "analyst-secret",
            )
            runtime.reencrypt_for_recipient.return_value = "released"
            runtime.decrypt_with_key.return_value = [3.0]

            backend = OpenFHEBackend(CKKSConfig.profile("ckks-balanced-v1"))
            try:
                self.assertEqual(backend.encrypt([1.0]), "encrypted")
                self.assertEqual(backend.add("left", "right"), "added")
                self.assertEqual(backend.decrypt("added", 1), [3.0])
                self.assertTrue(backend.capabilities.supports_serialization)
                self.assertTrue(
                    backend.capabilities.supports_proxy_re_encryption
                )
                recipient_id, public_key, secret_key = (
                    backend.create_result_recipient()
                )
                self.assertTrue(recipient_id)
                self.assertEqual(public_key, "analyst-public")
                self.assertEqual(secret_key, "analyst-secret")
                self.assertEqual(
                    backend.reencrypt_for_recipient("sum", public_key),
                    "released",
                )
                self.assertEqual(
                    backend.decrypt_for_recipient(
                        "released", secret_key, 1
                    ),
                    [3.0],
                )
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

    def test_compute_backend_loads_public_material_without_secret(self) -> None:
        module = self.module()
        with (
            patch(
                "he_sdk.backends.openfhe.OpenFHECPU.from_public_material"
            ) as load_runtime,
            patch(
                "he_sdk.backends.openfhe.importlib.import_module",
                return_value=module,
            ),
        ):
            load_runtime.return_value.has_secret_key = False
            backend = OpenFHEBackend.from_public_material(
                CKKSConfig.profile("ckks-balanced-v1"),
                Path("/public/material"),
                context_id="context-a",
                key_bundle_id="keys-a",
            )
            try:
                self.assertFalse(backend.has_secret_key)
                self.assertEqual(backend.context_id, "context-a")
                self.assertEqual(backend.key_bundle_id, "keys-a")
                load_runtime.assert_called_once_with(
                    module, Path("/public/material")
                )
            finally:
                backend.close()


if __name__ == "__main__":
    unittest.main()
