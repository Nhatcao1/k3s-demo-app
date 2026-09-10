from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import tempfile
import tomllib
import unittest
from unittest import mock

from he_sdk import (
    BackendUnavailableError,
    ArtifactError,
    CKKSConfig,
    CapabilitySet,
    EncryptedScalar,
    EncryptedVector,
    HESession,
    IncompatibleCiphertextError,
    OPERATION_CONTRACTS,
    ReleasedResult,
    ResultReleaseError,
    SessionClosedError,
    SecretKeyUnavailableError,
    UnsupportedOperationError,
    __version__,
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
        supports_serialization=True,
        supports_proxy_re_encryption=True,
    )

    def __init__(self, *, has_secret_key: bool = True) -> None:
        self.closed = False
        self.has_secret_key = has_secret_key

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

    def create_result_recipient(self) -> tuple[str, str, str]:
        return "analyst-a", "analyst-public-a", "analyst-secret-a"

    def reencrypt_for_recipient(
        self, encrypted: list[float], recipient_public_key: str
    ) -> dict[str, object]:
        return {
            "values": list(encrypted),
            "recipient_public_key": recipient_public_key,
        }

    def decrypt_for_recipient(
        self,
        encrypted: dict[str, object],
        recipient_secret_key: str,
        length: int,
    ) -> list[float]:
        if recipient_secret_key != "analyst-secret-a":
            raise RuntimeError("wrong analyst key")
        if encrypted["recipient_public_key"] != "analyst-public-a":
            raise RuntimeError("ciphertext was not released to this analyst")
        values = encrypted["values"]
        assert isinstance(values, list)
        return [float(value) for value in values[:length]]

    def serialize_public_key(self, public_key: str, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(public_key, encoding="utf-8")

    def deserialize_public_key(self, path: Path) -> str:
        return path.read_text(encoding="utf-8")

    def close(self) -> None:
        self.closed = True

    def export_public_material(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        for name in (
            "context.bin",
            "public-key.bin",
            "multiplication-keys.bin",
            "rotation-keys.bin",
        ):
            (directory / name).write_bytes(f"fake:{name}".encode())

    def serialize_ciphertext(self, encrypted: Any, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(encrypted), encoding="utf-8")

    def deserialize_ciphertext(self, path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))


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

    def test_package_and_compatibility_versions_match(self) -> None:
        root = Path(__file__).parents[1]
        project = tomllib.loads((root / "pyproject.toml").read_text())
        compatibility = tomllib.loads(
            (root / "compatibility" / "he-sdk-v1.toml").read_text()
        )
        self.assertEqual(__version__, project["project"]["version"])
        self.assertEqual(__version__, compatibility["sdk_version"])
        self.assertEqual(
            compatibility["openfhe"]["workspace_format"],
            "he-sdk-workspace-v1",
        )

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

    def test_pre_releases_only_aggregate_results_to_analyst(self) -> None:
        encrypted_input = self.session.encrypt([10, 20, 30])
        analyst = self.session.create_result_recipient()

        released_sum = self.session.release_result(
            self.session.sum(encrypted_input), to=analyst
        )
        released_mean = self.session.release_result(
            self.session.mean(encrypted_input), to=analyst
        )
        released_variance = self.session.release_result(
            self.session.variance(encrypted_input), to=analyst
        )

        self.assertIsInstance(released_sum, ReleasedResult)
        self.assertEqual(analyst.decrypt(released_sum), 60.0)
        self.assertEqual(analyst.decrypt(released_mean), 20.0)
        self.assertAlmostEqual(
            analyst.decrypt(released_variance), 200.0 / 3.0
        )
        with self.assertRaisesRegex(ResultReleaseError, "ReleasedResult"):
            analyst.decrypt(encrypted_input)  # type: ignore[arg-type]
        with self.assertRaisesRegex(ResultReleaseError, "aggregate scalar"):
            self.session.release_result(  # type: ignore[arg-type]
                encrypted_input, to=analyst
            )

    def test_pre_allows_compute_only_recipient_and_rejects_wrong_context(self) -> None:
        compute = HESession.from_backend(FakeBackend(has_secret_key=False))
        try:
            analyst = compute.create_result_recipient()
            self.assertEqual(analyst.recipient_id, "analyst-a")
        finally:
            compute.close()

        encrypted_input = self.session.encrypt([1, 2])
        released = self.session.release_result(
            self.session.sum(encrypted_input),
            to=self.session.create_result_recipient(),
        )
        other_backend = FakeBackend()
        other_backend.context_id = "context-b"
        other = HESession.from_backend(other_backend)
        try:
            other_analyst = other.create_result_recipient()
            with self.assertRaisesRegex(
                IncompatibleCiphertextError, "different HE context"
            ):
                other_analyst.decrypt(released)
        finally:
            other.close()

    def test_pre_public_key_and_released_result_artifact_flow(self) -> None:
        """Analyst exports public only; owner persists only released output."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            public_key_directory = root / "analyst-public"
            result_workspace = root / "released-results"
            analyst_session = HESession.from_backend(
                FakeBackend(has_secret_key=False)
            )
            try:
                analyst = analyst_session.create_result_recipient()
                analyst.save_public_key(public_key_directory)
                public_manifest = json.loads(
                    (
                        public_key_directory / "recipient-public-key.json"
                    ).read_text(encoding="utf-8")
                )
                self.assertFalse(public_manifest["contains_secret_key"])
                self.assertNotIn(
                    "secret",
                    (public_key_directory / "recipient-public-key.bin")
                    .read_text(encoding="utf-8"),
                )

                analyst_public_key = self.session.load_recipient_public_key(
                    public_key_directory
                )
                encrypted = self.session.encrypt([10, 20, 30])
                released = self.session.reencrypt_for_recipient(
                    self.session.sum(encrypted), analyst_public_key
                )
                self.session.save(
                    released, result_workspace, name="released_sum"
                )

                result_manifest = json.loads(
                    (result_workspace / "manifest.json").read_text(
                        encoding="utf-8"
                    )
                )
                record = result_manifest["ciphertexts"]["released_sum"]
                self.assertEqual(record["kind"], "released_scalar")
                self.assertEqual(record["recipient_id"], analyst.recipient_id)
                self.assertFalse(result_manifest["contains_secret_key"])

                analyst_result = analyst.load(
                    result_workspace, name="released_sum"
                )
                self.assertEqual(analyst.decrypt(analyst_result), 60.0)
                with self.assertRaisesRegex(
                    ResultReleaseError, "ReleasedResult"
                ):
                    analyst.decrypt(encrypted)  # type: ignore[arg-type]

                (
                    public_key_directory / "recipient-public-key.bin"
                ).write_text("tampered", encoding="utf-8")
                with self.assertRaisesRegex(ArtifactError, "checksum"):
                    self.session.load_recipient_public_key(
                        public_key_directory
                    )
            finally:
                analyst_session.close()

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

    def test_secretless_workspace_round_trip_between_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            encrypted = self.session.encrypt([10, 20, 30])
            self.session.save(encrypted, workspace, name="input")

            manifest = json.loads(
                (workspace / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertFalse(manifest["contains_plaintext"])
            self.assertFalse(manifest["contains_secret_key"])
            self.assertNotIn("secret", " ".join(path.name for path in workspace.rglob("*")))

            compute_backend = FakeBackend(has_secret_key=False)
            with mock.patch(
                "he_sdk.session.create_backend_from_public_material",
                return_value=compute_backend,
            ):
                with HESession.open_workspace(workspace) as compute:
                    compute_input = compute.load(workspace, name="input")
                    compute.save(
                        compute.sum(compute_input), workspace, name="sum"
                    )
                    compute.save(
                        compute.mean(compute_input), workspace, name="mean"
                    )
                    compute.save(
                        compute.variance(compute_input),
                        workspace,
                        name="variance",
                    )
                    with self.assertRaises(SecretKeyUnavailableError):
                        compute.decrypt(compute_input)

            self.assertEqual(
                self.session.decrypt(self.session.load(workspace, name="sum")),
                60.0,
            )
            self.assertEqual(
                self.session.decrypt(self.session.load(workspace, name="mean")),
                20.0,
            )
            self.assertEqual(
                self.session.decrypt(
                    self.session.load(workspace, name="variance")
                ),
                200.0 / 3.0,
            )

    def test_workspace_can_select_compatible_execution_backend(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            self.session.save(
                self.session.encrypt([1, 2, 3]), workspace, name="input"
            )
            accelerated = FakeBackend(has_secret_key=False)
            accelerated.name = "fides"
            accelerated.artifact_backend = "fake"
            accelerated.capabilities = CapabilitySet(
                backend="fides",
                schemes=("CKKS",),
                operations=tuple(OPERATION_CONTRACTS),
                supports_serialization=True,
            )
            with mock.patch(
                "he_sdk.session.create_backend_from_public_material",
                return_value=accelerated,
            ) as factory:
                with HESession.open_workspace(
                    workspace, execution_backend="fides"
                ) as compute:
                    loaded = compute.load(workspace, name="input")
                    self.assertIsInstance(loaded, EncryptedVector)
                    self.assertEqual(compute.capabilities.backend, "fides")

            self.assertEqual(factory.call_args.args[0], "fides")

    def test_workspace_rejects_tampered_ciphertext(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            self.session.save(
                self.session.encrypt([1, 2]), workspace, name="input"
            )
            (workspace / "ciphertexts" / "input.bin").write_bytes(b"tampered")
            with self.assertRaisesRegex(ArtifactError, "checksum"):
                self.session.load(workspace, name="input")

    def test_workspace_rejects_unsafe_artifact_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ArtifactError, "artifact name"):
                self.session.save(
                    self.session.encrypt([1]),
                    Path(temporary) / "workspace",
                    name="../secret",
                )

    def test_workspace_rejects_manifest_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            self.session.save(
                self.session.encrypt([1, 2]), workspace, name="input"
            )
            manifest_path = workspace / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["ciphertexts"]["input"]["file"] = "../outside.bin"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ArtifactError, "escapes"):
                self.session.load(workspace, name="input")

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
