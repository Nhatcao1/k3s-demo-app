from __future__ import annotations

import unittest
from unittest.mock import MagicMock, call, patch

from backends.openfhe_demo import OpenFHEDemoBackend


class OpenFHEDemoCleanupTests(unittest.TestCase):
    def test_add_clears_global_state_before_and_after_request(self) -> None:
        openfhe = MagicMock()
        with (
            patch("backends.openfhe_demo.OpenFHECPU") as openfhe_cpu,
            patch(
                "backends.openfhe_demo.importlib.import_module",
                return_value=openfhe,
            ),
        ):
            he = openfhe_cpu.return_value
            he.encrypt.side_effect = ["left-ciphertext", "right-ciphertext"]
            he.add.return_value = "result-ciphertext"
            he.decrypt.return_value = [4.0, 6.0]

            result = OpenFHEDemoBackend().evaluate("add", [1, 2], [3, 4])

        self.assertEqual(result["values"], [4.0, 6.0])
        openfhe_cpu.assert_called_once_with(openfhe)
        self.assertEqual(
            openfhe.mock_calls,
            [
                call.ClearEvalMultKeys(),
                call.ClearEvalAutomorphismKeys(),
                call.ReleaseAllContexts(),
                call.ClearEvalMultKeys(),
                call.ClearEvalAutomorphismKeys(),
                call.ReleaseAllContexts(),
            ],
        )

    def test_cleanup_runs_when_evaluation_fails(self) -> None:
        openfhe = MagicMock()
        with (
            patch("backends.openfhe_demo.OpenFHECPU") as openfhe_cpu,
            patch(
                "backends.openfhe_demo.importlib.import_module",
                return_value=openfhe,
            ),
        ):
            openfhe_cpu.return_value.encrypt.side_effect = RuntimeError(
                "native error"
            )
            with self.assertRaisesRegex(RuntimeError, "native error"):
                OpenFHEDemoBackend().evaluate("square", [2], None)

        self.assertEqual(openfhe.ReleaseAllContexts.call_count, 2)
        self.assertEqual(openfhe.ClearEvalMultKeys.call_count, 2)
        self.assertEqual(openfhe.ClearEvalAutomorphismKeys.call_count, 2)


if __name__ == "__main__":
    unittest.main()
