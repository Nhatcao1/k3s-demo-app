from __future__ import annotations

import unittest

from client.heir_trial import expected_total
from gateway.heir_adjusted_net import adjusted_net_total_mlir


class AdjustedNetMlirTests(unittest.TestCase):
    def test_emits_secret_three_input_single_result_program(self) -> None:
        source = adjusted_net_total_mlir(4)

        self.assertEqual(source.count("{secret.secret}"), 3)
        self.assertIn("%net = arith.subf", source)
        self.assertIn("%adjusted = arith.mulf", source)
        self.assertIn("return %total : f64", source)

    def test_plaintext_oracle_is_stable(self) -> None:
        self.assertEqual(expected_total(), 241.0)

    def test_rejects_invalid_width(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least two"):
            adjusted_net_total_mlir(1)


if __name__ == "__main__":
    unittest.main()
