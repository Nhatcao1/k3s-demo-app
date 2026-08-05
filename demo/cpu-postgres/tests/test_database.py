from __future__ import annotations

from pathlib import Path
import sys
import unittest


DEMO_ROOT = Path(__file__).resolve().parents[1]
if str(DEMO_ROOT) not in sys.path:
    sys.path.insert(0, str(DEMO_ROOT))

from cpu_postgres_demo.database import (  # noqa: E402
    SessionStoreError,
    operation_mode,
)


class OperationTransitionTests(unittest.TestCase):
    def test_sum_computes_from_initialized(self) -> None:
        self.assertEqual(
            operation_mode("INITIALIZED", "INITIALIZED", "SUMMED"), "COMPUTE"
        )

    def test_completed_or_later_operation_reuses_artifact(self) -> None:
        self.assertEqual(
            operation_mode("SUMMED", "INITIALIZED", "SUMMED"), "REUSE"
        )
        self.assertEqual(
            operation_mode("VERIFIED", "INITIALIZED", "SUMMED"), "REUSE"
        )

    def test_multiply_cannot_run_before_sum(self) -> None:
        with self.assertRaisesRegex(SessionStoreError, "requires SUMMED"):
            operation_mode("INITIALIZED", "SUMMED", "MULTIPLIED")

    def test_unknown_status_is_rejected(self) -> None:
        with self.assertRaisesRegex(SessionStoreError, "unknown"):
            operation_mode("BROKEN", "SUMMED", "MULTIPLIED")


if __name__ == "__main__":
    unittest.main()
