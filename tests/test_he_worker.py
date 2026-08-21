from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from contextlib import redirect_stderr, redirect_stdout
import io
import unittest
from unittest import mock

from he_sdk import CiphertextMetadata, EncryptedScalar, EncryptedVector
from he_worker.request import WorkerRequest
from he_worker.runner import execute
from he_worker.postgres import _artifact_type, _safe_relative_path


def metadata(*, scalar: bool = False) -> CiphertextMetadata:
    return CiphertextMetadata(
        context_id="context-a",
        context_fingerprint="fingerprint-a",
        key_bundle_id="keys-a",
        scheme="CKKS",
        backend="openfhe",
        engine_version="test",
        packing_layout="ckks-packed-contiguous-v1",
        valid_count=1 if scalar else 3,
        logical_shape=() if scalar else (3,),
        level=0,
        scale_bits=50,
        serialization_version="openfhe-binary-v1",
        result_operation="sum" if scalar else None,
    )


class FakeSession:
    def __init__(self) -> None:
        self.capabilities = SimpleNamespace(backend="openfhe")
        self.values = {
            "left": EncryptedVector(metadata(), b"left", "session-a"),
            "right": EncryptedVector(metadata(), b"right", "session-a"),
        }
        self.saved: tuple[object, str, str] | None = None

    def __enter__(self) -> "FakeSession":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def load(self, workspace: str, *, name: str):
        return self.values[name]

    def add(self, left: EncryptedVector, right: EncryptedVector):
        return EncryptedVector(metadata(), b"result", "session-a")

    def sum(self, value: EncryptedVector):
        return EncryptedScalar(metadata(scalar=True), b"result", "session-a")

    def save(self, value: object, workspace: str, *, name: str) -> Path:
        self.saved = (value, workspace, name)
        return Path(workspace) / "ciphertexts" / f"{name}.bin"


class HEWorkerTests(unittest.TestCase):
    def test_binary_operation_uses_selected_backend_and_saves_result(self) -> None:
        session = FakeSession()
        request = WorkerRequest(
            workspace="/workspace/run-a",
            operation="add",
            left="left",
            right="right",
            output="added",
            execution_backend="fides",
        )
        with (
            mock.patch("he_worker.runner.list_ciphertexts", return_value=("left", "right")),
            mock.patch(
                "he_worker.runner.HESession.open_workspace",
                return_value=session,
            ) as opener,
        ):
            result = execute(request)

        opener.assert_called_once_with(
            "/workspace/run-a", execution_backend="fides"
        )
        self.assertEqual(session.saved[2], "added")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["operation"], "add")
        self.assertFalse(result["contains_secret_key"])

    def test_reduction_accepts_one_vector(self) -> None:
        session = FakeSession()
        request = WorkerRequest(
            workspace="/workspace/run-a",
            operation="sum",
            left="left",
            output="sum",
        )
        with (
            mock.patch("he_worker.runner.list_ciphertexts", return_value=("left",)),
            mock.patch(
                "he_worker.runner.HESession.open_workspace",
                return_value=session,
            ),
        ):
            result = execute(request)
        self.assertEqual(result["output"], "sum")
        self.assertEqual(result["artifact_backend"], "openfhe")

    def test_request_rejects_wrong_arity_and_input_overwrite(self) -> None:
        with self.assertRaisesRegex(ValueError, "right input"):
            WorkerRequest(
                workspace="/workspace",
                operation="multiply",
                left="left",
                output="result",
            ).validate()
        with self.assertRaisesRegex(ValueError, "must not overwrite"):
            WorkerRequest(
                workspace="/workspace",
                operation="sum",
                left="input",
                output="input",
            ).validate()

    def test_existing_output_is_fail_closed(self) -> None:
        request = WorkerRequest(
            workspace="/workspace",
            operation="sum",
            left="input",
            output="result",
        )
        with (
            mock.patch(
                "he_worker.runner.list_ciphertexts",
                return_value=("input", "result"),
            ),
            self.assertRaisesRegex(ValueError, "already exists"),
        ):
            execute(request)

    def test_postgres_transport_rejects_secret_and_unsafe_paths(self) -> None:
        self.assertEqual(_artifact_type("material/context.bin"), "context")
        self.assertEqual(
            _artifact_type("material/rotation-keys.bin"), "evaluation_key"
        )
        with self.assertRaisesRegex(ValueError, "unsafe"):
            _safe_relative_path("../secret.bin")
        with self.assertRaisesRegex(ValueError, "secret-like"):
            _safe_relative_path("material/secret-key.bin")

    def test_cli_accepts_database_run_without_local_workspace(self) -> None:
        from he_worker import __main__ as cli

        result = {
            "status": "completed",
            "run_id": 42,
            "contains_secret_key": False,
        }
        standard_output = io.StringIO()
        with (
            mock.patch(
                "he_worker.postgres.execute_postgres", return_value=result
            ) as execute_database,
            redirect_stdout(standard_output),
        ):
            status = cli.main(
                [
                    "--run-id",
                    "42",
                    "--operation",
                    "sum",
                    "--left",
                    "input",
                    "--output",
                    "result",
                    "--execution-backend",
                    "fides",
                ]
            )
        self.assertEqual(status, 0)
        self.assertIn('"run_id": 42', standard_output.getvalue())
        self.assertEqual(execute_database.call_args.args[1], 42)

    def test_cli_requires_exactly_one_storage_mode(self) -> None:
        from he_worker import __main__ as cli

        standard_error = io.StringIO()
        with redirect_stderr(standard_error):
            status = cli.main(
                [
                    "--workspace",
                    "/tmp/workspace",
                    "--run-id",
                    "42",
                    "--operation",
                    "sum",
                    "--left",
                    "input",
                    "--output",
                    "result",
                ]
            )
        self.assertEqual(status, 1)
        self.assertIn("select exactly one", standard_error.getvalue())


if __name__ == "__main__":
    unittest.main()
