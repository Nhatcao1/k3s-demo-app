from __future__ import annotations

from pathlib import Path
import sys
import unittest


DEMO_ROOT = Path(__file__).resolve().parents[1]
if str(DEMO_ROOT) not in sys.path:
    sys.path.insert(0, str(DEMO_ROOT))

from cpu_postgres_demo.artifacts import (  # noqa: E402
    CONTEXT,
    KPI_CIPHERTEXT,
    KPI_RESULT_CIPHERTEXT,
    MULTIPLICATION_EVALUATION_KEYS,
    SALARY_CIPHERTEXT,
    SUM_CIPHERTEXT,
    SUM_EVALUATION_KEYS,
)
from cpu_postgres_demo.cli import multiply_session, sum_session  # noqa: E402
from cpu_postgres_demo.database import OperationResult  # noqa: E402


class RecordingStore:
    def __init__(self) -> None:
        self.arguments: dict[str, object] = {}

    def compute_operation(self, **arguments: object) -> OperationResult:
        self.arguments = arguments
        return OperationResult(b"encrypted-result", reused=False)


class JobArtifactSelectionTests(unittest.TestCase):
    def test_sum_loads_only_sum_material(self) -> None:
        store = RecordingStore()
        sum_session("salary-demo-001", store)  # type: ignore[arg-type]
        self.assertEqual(
            store.arguments["required_artifacts"],
            (CONTEXT, SALARY_CIPHERTEXT, SUM_EVALUATION_KEYS),
        )
        self.assertEqual(store.arguments["output_artifact"], SUM_CIPHERTEXT)

    def test_multiply_loads_sum_kpi_and_mult_material(self) -> None:
        store = RecordingStore()
        multiply_session("salary-demo-001", store)  # type: ignore[arg-type]
        self.assertEqual(
            store.arguments["required_artifacts"],
            (
                CONTEXT,
                SUM_CIPHERTEXT,
                KPI_CIPHERTEXT,
                MULTIPLICATION_EVALUATION_KEYS,
            ),
        )
        self.assertEqual(
            store.arguments["output_artifact"], KPI_RESULT_CIPHERTEXT
        )


if __name__ == "__main__":
    unittest.main()
