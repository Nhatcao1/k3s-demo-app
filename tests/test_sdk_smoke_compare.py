from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "sdk" / "compare_smoke_results.py"


def load_compare_module():
    spec = importlib.util.spec_from_file_location("compare_smoke_under_test", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load smoke comparison script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SmokeComparisonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_compare_module()
        self.reference = {
            "status": "PASS",
            "backend": "openfhe",
            "operations": ["add", "variance"],
            "decrypted_results": {
                "add": [2.0, 4.0],
                "variance": [1.25],
            },
        }

    def test_accepts_results_within_ckks_tolerance(self) -> None:
        candidate = {
            "status": "PASS",
            "backend": "fides",
            "operations": ["add", "variance"],
            "decrypted_results": {
                "add": [2.0001, 3.9999],
                "variance": [1.2501],
            },
        }
        self.module.compare(self.reference, candidate)

    def test_rejects_backend_result_drift(self) -> None:
        candidate = {
            "status": "PASS",
            "backend": "fides",
            "operations": ["add", "variance"],
            "decrypted_results": {
                "add": [2.0, 4.0],
                "variance": [1.5],
            },
        }
        with self.assertRaisesRegex(RuntimeError, "variance"):
            self.module.compare(self.reference, candidate)


if __name__ == "__main__":
    unittest.main()
