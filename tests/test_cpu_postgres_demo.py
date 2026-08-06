from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


DEMO_ROOT = Path(__file__).resolve().parents[1] / "demo" / "cpu-postgres"
sys.path.insert(0, str(DEMO_ROOT))

from cpu_postgres_demo import cli  # noqa: E402
from cpu_postgres_demo.config import DemoConfigError, parse_kpi  # noqa: E402


class KpiConfigTests(unittest.TestCase):
    def test_kpi_accepts_demo_range(self) -> None:
        self.assertEqual(parse_kpi({"DEMO_KPI": "0.8"}), Decimal("0.8"))
        self.assertEqual(parse_kpi({"DEMO_KPI": "1.2"}), Decimal("1.2"))

    def test_kpi_rejects_values_outside_demo_range(self) -> None:
        for value in ("0.79", "1.21"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(DemoConfigError, "0.8 and 1.2"):
                    parse_kpi({"DEMO_KPI": value})


class FakeStore:
    def __init__(self) -> None:
        self.recorded: tuple[object, ...] | None = None

    def verification_artifacts(
        self, session_id: str, result_artifact: str
    ) -> dict[str, bytes]:
        return {result_artifact: b"ciphertext"}

    def expected_values(self, session_id: str) -> tuple[Decimal, Decimal]:
        return Decimal("100"), Decimal("110")

    def record_verification(self, *values: object) -> None:
        self.recorded = values


class VerificationTests(unittest.TestCase):
    def test_sum_and_kpi_keep_separate_expected_values(self) -> None:
        inputs = SimpleNamespace(
            session_id="demo-1",
            scheme="ckks",
            wrap_key=b"x" * 32,
            kpi_scale=10,
            tolerance=0.000001,
        )
        cases = (("sum", 100.0, Decimal("100")), ("kpi", 110.0, Decimal("110")))
        for stage, observed, expected in cases:
            with self.subTest(stage=stage):
                store = FakeStore()
                with patch.object(cli, "decrypt_result", return_value=observed):
                    cli.verify_session(inputs, store, stage)
                self.assertEqual(
                    store.recorded,
                    ("demo-1", stage, expected, Decimal("0"), True),
                )


if __name__ == "__main__":
    unittest.main()
