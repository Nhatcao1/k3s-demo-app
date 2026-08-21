from __future__ import annotations

import importlib.util
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from he_sdk import HESession, ResultReleaseError


OPENFHE_AVAILABLE = importlib.util.find_spec("openfhe") is not None


@unittest.skipUnless(OPENFHE_AVAILABLE, "OpenFHE native dependency is not installed")
class OpenFHESDKIntegrationTests(unittest.TestCase):
    def assert_close(
        self, observed: list[float] | float, expected: list[float] | float
    ) -> None:
        actual_values = observed if isinstance(observed, list) else [observed]
        expected_values = expected if isinstance(expected, list) else [expected]
        self.assertEqual(len(actual_values), len(expected_values))
        for actual, wanted in zip(actual_values, expected_values):
            self.assertTrue(
                math.isclose(actual, wanted, rel_tol=1e-3, abs_tol=1e-3),
                f"observed {actual}, expected {wanted}",
            )

    def test_all_first_release_functions(self) -> None:
        left_values = [1.25, -2.0, 3.5, 4.0]
        right_values = [0.75, 5.0, -1.5, 2.0]
        with HESession.create(backend="openfhe") as he:
            left = he.encrypt(left_values)
            right = he.encrypt(right_values)
            self.assert_close(
                he.decrypt(he.add(left, right)),
                [a + b for a, b in zip(left_values, right_values)],
            )
            self.assert_close(
                he.decrypt(he.subtract(left, right)),
                [a - b for a, b in zip(left_values, right_values)],
            )
            self.assert_close(
                he.decrypt(he.multiply(left, right)),
                [a * b for a, b in zip(left_values, right_values)],
            )
            self.assert_close(
                he.decrypt(he.square(left)),
                [value * value for value in left_values],
            )
            self.assert_close(he.decrypt(he.sum(left)), sum(left_values))
            self.assert_close(
                he.decrypt(he.mean(left)), sum(left_values) / len(left_values)
            )
            mean = sum(left_values) / len(left_values)
            expected_variance = sum(
                (value - mean) ** 2 for value in left_values
            ) / len(left_values)
            self.assert_close(
                he.decrypt(he.variance(left)), expected_variance
            )

    def test_result_only_proxy_re_encryption(self) -> None:
        values = [10.0, 20.0, 30.0]
        with HESession.create(backend="openfhe") as owner:
            encrypted_input = owner.encrypt(values)
            analyst = owner.create_result_recipient()

            # Keep the native smoke test deliberately small. Public-key and
            # released-result persistence are covered by SDK contract tests;
            # this verifies only one real OpenFHE PRE transformation.
            released_sum = owner.reencrypt_for_recipient(
                owner.sum(encrypted_input), analyst.public_key
            )
            self.assert_close(analyst.decrypt(released_sum), 60.0)

            # The analyst API refuses an owner ciphertext, and its native key
            # is different from the key that encrypted this input.
            with self.assertRaises(ResultReleaseError):
                analyst.decrypt(encrypted_input)  # type: ignore[arg-type]

    def test_secretless_workspace_across_processes(self) -> None:
        values = [10.0, 20.0, 30.0]
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            with HESession.create(backend="openfhe") as owner:
                owner.save(owner.encrypt(values), workspace, name="input")
                compute_code = """
from pathlib import Path
import sys
from he_sdk import HESession, SecretKeyUnavailableError

workspace = Path(sys.argv[1])
with HESession.open_workspace(workspace) as compute:
    encrypted = compute.load(workspace, name="input")
    compute.save(compute.sum(encrypted), workspace, name="sum")
    compute.save(compute.mean(encrypted), workspace, name="mean")
    compute.save(compute.variance(encrypted), workspace, name="variance")
    try:
        compute.decrypt(encrypted)
    except SecretKeyUnavailableError:
        pass
    else:
        raise RuntimeError("compute session unexpectedly decrypted input")
"""
                completed = subprocess.run(
                    [sys.executable, "-c", compute_code, str(workspace)],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=600,
                )
                self.assertEqual(
                    completed.returncode,
                    0,
                    f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
                )
                self.assert_close(
                    owner.decrypt(owner.load(workspace, name="sum")), 60.0
                )
                self.assert_close(
                    owner.decrypt(owner.load(workspace, name="mean")), 20.0
                )
                self.assert_close(
                    owner.decrypt(owner.load(workspace, name="variance")),
                    200.0 / 3.0,
                )


if __name__ == "__main__":
    unittest.main()
