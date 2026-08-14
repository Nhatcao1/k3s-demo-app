from __future__ import annotations

import importlib.util
import math
import unittest

from he_sdk import HESession


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


if __name__ == "__main__":
    unittest.main()
