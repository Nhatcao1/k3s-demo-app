from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


DEMO_ROOT = Path(__file__).resolve().parents[1] / "demo" / "cpu-postgres"
sys.path.insert(0, str(DEMO_ROOT))

from cpu_postgres_demo import cli  # noqa: E402
from cpu_postgres_demo.config import DemoConfigError, parse_salary_rows  # noqa: E402


class SalaryCsvTests(unittest.TestCase):
    def parse(self, content: str) -> tuple[tuple[int, ...], tuple[Decimal, ...]]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "salaries.csv"
            path.write_text(content, encoding="utf-8")
            return parse_salary_rows({"DEMO_SALARIES_CSV": str(path)})

    def test_each_salary_has_its_own_allowed_kpi(self) -> None:
        salaries, kpis = self.parse(
            "salary,kpi\n10000000,0.8\n200000000,1.2\n"
        )
        self.assertEqual(salaries, (10_000_000, 200_000_000))
        self.assertEqual(kpis, (Decimal("0.8"), Decimal("1.2")))

    def test_rejects_kpi_outside_the_discrete_set(self) -> None:
        with self.assertRaisesRegex(DemoConfigError, "must be 0.8"):
            self.parse("salary,kpi\n10000000,0.85\n")


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

    def test_failed_verification_keeps_observed_value_and_error(self) -> None:
        inputs = SimpleNamespace(
            session_id="demo-1",
            scheme="ckks",
            wrap_key=b"x" * 32,
            kpi_scale=10,
            tolerance=0.000001,
        )
        store = FakeStore()
        with patch.object(cli, "decrypt_result", return_value=111.0):
            with self.assertRaises(cli.VerificationFailed):
                cli.verify_session(inputs, store, "kpi")
        self.assertEqual(
            store.recorded,
            ("demo-1", "kpi", Decimal("111.0"), Decimal("1.0"), False),
        )


if __name__ == "__main__":
    unittest.main()
