from __future__ import annotations

import json
from pathlib import Path
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
    InsufficientLevelError,
    IncompatibleCiphertextError,
    OPERATION_CONTRACTS,
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

    def serialize_ciphertext(self, encrypted: list[float], path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(encrypted), encoding="utf-8")

    def deserialize_ciphertext(self, path: Path) -> list[float]:
        return [float(value) for value in json.loads(path.read_text())]


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
            (root / "compatibility" / "he-sdk-v2.toml").read_text()
        )
        self.assertEqual(__version__, project["project"]["version"])
        self.assertEqual(__version__, compatibility["sdk_version"])
        self.assertEqual(
            compatibility["openfhe"]["workspace_format"],
            "he-sdk-workspace-v2",
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
        self.assertEqual(metadata.chunk_size, 8192)
        self.assertEqual(metadata.chunk_count, 1)

    def test_encrypt_transparently_chunks_and_decrypts_large_vector(self) -> None:
        values = [1, 2, 3, 4, 5]
        encrypted = self.session.encrypt(values, chunk_size=2)

        self.assertEqual(encrypted.chunk_count, 3)
        self.assertEqual(encrypted.metadata.valid_count, 5)
        self.assertEqual(encrypted.metadata.logical_shape, (5,))
        self.assertEqual(encrypted.metadata.chunk_size, 2)
        self.assertEqual(
            [
                (chunk.index, chunk.offset, chunk.valid_count)
                for chunk in encrypted.chunks
            ],
            [(0, 0, 2), (1, 2, 2), (2, 4, 1)],
        )
        self.assertEqual(self.session.decrypt(encrypted), [1, 2, 3, 4, 5])

    def test_chunked_elementwise_operations_and_global_reductions(self) -> None:
        left_values = [1, 2, 3, 4, 5]
        right_values = [5, 4, 3, 2, 1]
        left = self.session.encrypt(
            left_values, chunk_size=2, alignment_id="rows-v1"
        )
        right = self.session.encrypt(
            right_values, chunk_size=2, alignment_id="rows-v1"
        )

        self.assertEqual(self.session.decrypt(self.session.add(left, right)), [6] * 5)
        self.assertEqual(
            self.session.decrypt(self.session.subtract(left, right)),
            [-4, -2, 0, 2, 4],
        )
        self.assertEqual(
            self.session.decrypt(self.session.multiply(left, right)),
            [5, 8, 9, 8, 5],
        )
        self.assertEqual(
            self.session.decrypt(self.session.square(left)),
            [1, 4, 9, 16, 25],
        )
        self.assertEqual(self.session.decrypt(self.session.sum(left)), 15.0)
        self.assertEqual(self.session.decrypt(self.session.mean(left)), 3.0)
        self.assertEqual(self.session.decrypt(self.session.variance(left)), 2.0)

    def test_chunked_binary_operation_rejects_alignment_mismatch(self) -> None:
        left = self.session.encrypt([1, 2, 3], chunk_size=2, alignment_id="a")
        right = self.session.encrypt([4, 5, 6], chunk_size=2, alignment_id="b")
        with self.assertRaisesRegex(IncompatibleCiphertextError, "alignment"):
            self.session.add(left, right)

    def test_encrypt_csv_streams_one_numeric_column(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "values.csv"
            source.write_text("id,amount\na,1.5\nb,2.5\nc,3.5\n", encoding="utf-8")
            encrypted = self.session.encrypt_csv(
                source, column="amount", chunk_size=2
            )
            self.assertEqual(encrypted.chunk_count, 2)
            self.assertEqual(self.session.decrypt(encrypted), [1.5, 2.5, 3.5])

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
        with self.assertRaisesRegex(InsufficientLevelError, "allows 3"):
            self.session.square(value)

    def test_capabilities_advertise_sdk_managed_chunking(self) -> None:
        self.assertTrue(self.session.capabilities.supports_chunking)
        self.assertTrue(self.session.capabilities.supports_streaming_input)
        self.assertFalse(self.session.capabilities.supports_bootstrap)

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
            names = " ".join(path.name for path in workspace.rglob("*"))
            self.assertNotIn("secret", names)

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

    def test_chunked_workspace_round_trip_and_global_compute(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            encrypted = self.session.encrypt(
                range(1, 8), chunk_size=3, alignment_id="ordered-rows"
            )
            self.session.save(encrypted, workspace, name="input")

            manifest = json.loads(
                (workspace / "manifest.json").read_text(encoding="utf-8")
            )
            record = manifest["ciphertexts"]["input"]
            self.assertEqual(manifest["format_version"], "he-sdk-workspace-v2")
            self.assertEqual(len(record["chunks"]), 3)

            loaded = self.session.load(workspace, name="input")
            self.assertIsInstance(loaded, EncryptedVector)
            self.assertEqual(loaded.chunk_count, 3)
            self.assertEqual(self.session.decrypt(loaded), list(range(1, 8)))
            self.assertEqual(self.session.decrypt(self.session.sum(loaded)), 28.0)

    def test_chunked_workspace_round_trip_through_compute_only_session(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            encrypted = self.session.encrypt(range(1, 8), chunk_size=3)
            self.session.save(encrypted, workspace, name="input")

            compute_backend = FakeBackend(has_secret_key=False)
            with mock.patch(
                "he_sdk.session.create_backend_from_public_material",
                return_value=compute_backend,
            ):
                with HESession.open_workspace(workspace) as compute:
                    compute_input = compute.load(workspace, name="input")
                    compute.save(compute.sum(compute_input), workspace, name="sum")
                    compute.save(compute.mean(compute_input), workspace, name="mean")
                    compute.save(
                        compute.variance(compute_input),
                        workspace,
                        name="variance",
                    )

            self.assertEqual(
                self.session.decrypt(self.session.load(workspace, name="sum")),
                28.0,
            )
            self.assertEqual(
                self.session.decrypt(self.session.load(workspace, name="mean")),
                4.0,
            )
            self.assertEqual(
                self.session.decrypt(
                    self.session.load(workspace, name="variance")
                ),
                4.0,
            )

    def test_single_ciphertext_remains_writable_to_legacy_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            self.session.save(self.session.encrypt([0]), workspace, name="seed")
            manifest_path = workspace / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["format_version"] = "he-sdk-workspace-v1"
            manifest["ciphertexts"] = {}
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            self.session.save(
                self.session.encrypt([1, 2, 3]), workspace, name="legacy"
            )
            legacy_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            metadata = legacy_manifest["ciphertexts"]["legacy"]["metadata"]
            self.assertNotIn("chunk_size", metadata)
            self.assertNotIn("chunk_count", metadata)
            self.assertEqual(
                self.session.decrypt(self.session.load(workspace, name="legacy")),
                [1, 2, 3],
            )

            with self.assertRaisesRegex(ArtifactError, "workspace-v2"):
                self.session.save(
                    self.session.encrypt([1, 2, 3], chunk_size=2),
                    workspace,
                    name="too-large-for-v1",
                )

    def test_workspace_rejects_tampered_ciphertext(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            self.session.save(
                self.session.encrypt([1, 2]), workspace, name="input"
            )
            manifest = json.loads(
                (workspace / "manifest.json").read_text(encoding="utf-8")
            )
            relative = manifest["ciphertexts"]["input"]["chunks"][0]["file"]
            (workspace / relative).write_bytes(b"tampered")
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
            manifest["ciphertexts"]["input"]["chunks"][0]["file"] = (
                "../outside.bin"
            )
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ArtifactError, "escapes"):
                self.session.load(workspace, name="input")

    def test_workspace_rejects_missing_or_reordered_chunk(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            self.session.save(
                self.session.encrypt([1, 2, 3, 4, 5], chunk_size=2),
                workspace,
                name="input",
            )
            manifest_path = workspace / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["ciphertexts"]["input"]["chunks"].pop(1)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ArtifactError, "chunk layout"):
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
