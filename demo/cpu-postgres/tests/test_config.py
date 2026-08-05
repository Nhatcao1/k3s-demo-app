from __future__ import annotations

import base64
from pathlib import Path
import sys
import unittest


DEMO_ROOT = Path(__file__).resolve().parents[1]
if str(DEMO_ROOT) not in sys.path:
    sys.path.insert(0, str(DEMO_ROOT))

from cpu_postgres_demo.artifacts import (  # noqa: E402
    ArtifactError,
    CONTEXT,
    FORBIDDEN_RAW_KEY_NAMES,
    KPI_CIPHERTEXT,
    MULTIPLICATION_EVALUATION_KEYS,
    SALARY_CIPHERTEXT,
    SUM_EVALUATION_KEYS,
    WRAPPED_SECRET_KEY,
    validate_artifact,
    validate_initial_artifacts,
)
from cpu_postgres_demo.config import DemoConfigError, DemoInputs  # noqa: E402


def environment() -> dict[str, str]:
    return {
        "DEMO_SESSION_ID": "salary-demo-001",
        "DEMO_SALARIES_JSON": "[1000, 2000.5, 3000]",
        "DEMO_KPI": "0.8",
        "DEMO_KEY_WRAP_KEY": base64.b64encode(b"k" * 32).decode("ascii"),
        "DEMO_TOLERANCE": "0.01",
    }


class DemoInputsTests(unittest.TestCase):
    def test_parses_valid_inputs(self) -> None:
        inputs = DemoInputs.from_environment(environment())
        self.assertEqual(inputs.session_id, "salary-demo-001")
        self.assertEqual(inputs.salaries, (1000.0, 2000.5, 3000.0))
        self.assertEqual(inputs.kpi, 0.8)
        self.assertEqual(inputs.wrap_key, b"k" * 32)

    def test_rejects_invalid_session_id(self) -> None:
        values = environment()
        values["DEMO_SESSION_ID"] = "Salary Demo"
        with self.assertRaisesRegex(DemoConfigError, "DEMO_SESSION_ID"):
            DemoInputs.from_environment(values)

    def test_rejects_non_numeric_salary(self) -> None:
        values = environment()
        values["DEMO_SALARIES_JSON"] = '[1000, "private"]'
        with self.assertRaisesRegex(DemoConfigError, "salary"):
            DemoInputs.from_environment(values)

    def test_rejects_wrong_wrap_key_size(self) -> None:
        values = environment()
        values["DEMO_KEY_WRAP_KEY"] = base64.b64encode(b"short").decode("ascii")
        with self.assertRaisesRegex(DemoConfigError, "32 bytes"):
            DemoInputs.from_environment(values)


class ArtifactContractTests(unittest.TestCase):
    def test_raw_secret_key_names_are_never_allowed(self) -> None:
        for name in FORBIDDEN_RAW_KEY_NAMES:
            with self.subTest(name=name):
                with self.assertRaises(ArtifactError):
                    validate_artifact(name, b"secret")

    def test_initial_session_requires_exact_artifact_set(self) -> None:
        artifacts = {
            CONTEXT: b"context",
            SALARY_CIPHERTEXT: b"salary",
            KPI_CIPHERTEXT: b"kpi",
            SUM_EVALUATION_KEYS: b"sum-keys",
            MULTIPLICATION_EVALUATION_KEYS: b"mult-keys",
            WRAPPED_SECRET_KEY: b"wrapped",
        }
        validate_initial_artifacts(artifacts)
        del artifacts[SUM_EVALUATION_KEYS]
        with self.assertRaisesRegex(ArtifactError, "missing"):
            validate_initial_artifacts(artifacts)


if __name__ == "__main__":
    unittest.main()
