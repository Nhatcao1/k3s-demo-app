"""Fast source checks for FIDESlib API constraints caught by prior CI builds."""

from __future__ import annotations

from pathlib import Path
import re
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]


class FidesSourceContractTests(unittest.TestCase):
    def test_encrypt_never_receives_temporary_plaintext(self) -> None:
        """FIDESlib Encrypt requires Plaintext&, unlike standard OpenFHE."""
        for source in (REPOSITORY / "gpu" / "worker" / "src").glob("*.cpp"):
            text = source.read_text(encoding="utf-8")
            self.assertIsNone(
                re.search(
                    r"Encrypt\s*\([^;]*MakeCKKSPackedPlaintext\s*\(",
                    text,
                    flags=re.DOTALL,
                ),
                f"{source}: assign MakeCKKSPackedPlaintext() to a named "
                "Plaintext before calling FIDESlib Encrypt()",
            )

    def test_main_backend_calls_expected_fideslib_methods(self) -> None:
        backend = (
            REPOSITORY / "gpu" / "worker" / "src" / "fides_backend.cpp"
        ).read_text(encoding="utf-8")
        for method in (
            "EvalAdd",
            "EvalSub",
            "EvalMult",
            "EvalSquare",
            "AccumulateSum",
        ):
            self.assertIn(f"{method}(", backend)

    def test_calls_match_pinned_fideslib_when_submodule_is_available(self) -> None:
        public_api_path = (
            REPOSITORY
            / "gpu"
            / "third_party"
            / "FIDESlib"
            / "api"
            / "CryptoContext.hpp"
        )
        if not public_api_path.is_file():
            self.skipTest("FIDESlib submodule is not initialized in this checkout")

        public_api = public_api_path.read_text(encoding="utf-8")
        for method in (
            "EvalAdd",
            "EvalSub",
            "EvalMult",
            "EvalSquare",
            "AccumulateSum",
        ):
            self.assertIn(f"{method}(", public_api)


if __name__ == "__main__":
    unittest.main()
