"""Transactional PostgreSQL session and artifact storage."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from decimal import Decimal
import os
from typing import Any

from .artifacts import sha256_hex, validate_artifact, validate_initial_artifacts


STATUS_ORDER = {
    "INITIALIZED": 0,
    "SUMMED": 1,
    "MULTIPLIED": 2,
    "VERIFIED": 3,
}


class SessionStoreError(RuntimeError):
    """The database session state is missing or inconsistent."""


def operation_mode(status: str, required_status: str, completed_status: str) -> str:
    """Return COMPUTE or REUSE for an ordered, idempotent operation."""
    if status not in STATUS_ORDER:
        raise SessionStoreError(f"unknown session status: {status}")
    if STATUS_ORDER[status] >= STATUS_ORDER[completed_status]:
        return "REUSE"
    if status != required_status:
        raise SessionStoreError(
            f"operation requires {required_status}, current status is {status}"
        )
    return "COMPUTE"


@dataclass(frozen=True)
class OperationResult:
    payload: bytes
    reused: bool


def _bytes(value: Any) -> bytes:
    return bytes(value)


class SessionStore:
    def __init__(self, conninfo: str | None = None) -> None:
        # An empty conninfo intentionally lets libpq read PGHOST, PGPORT,
        # PGDATABASE, PGUSER, and PGPASSWORD from the Kubernetes environment.
        self.conninfo = os.getenv("DATABASE_URL", "") if conninfo is None else conninfo

    def _connect(self) -> Any:
        try:
            import psycopg
        except ImportError as error:
            raise SessionStoreError("psycopg is not installed") from error
        return psycopg.connect(self.conninfo)

    def create_session(
        self,
        session_id: str,
        scheme: str,
        valid_count: int,
        kpi_scale: int,
        expected_sum: Decimal,
        expected_kpi_amount: Decimal,
        artifacts: dict[str, bytes],
    ) -> None:
        validate_initial_artifacts(artifacts)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO he_demo_sessions
                        (session_id, scheme, status, valid_count, kpi_scale)
                    VALUES (%s, %s, 'INITIALIZED', %s, %s)
                    """,
                    (session_id, scheme, valid_count, kpi_scale),
                )
                cursor.execute(
                    """
                    INSERT INTO he_demo_results
                        (session_id, expected_sum, expected_kpi_amount)
                    VALUES (%s, %s, %s)
                    """,
                    (session_id, expected_sum, expected_kpi_amount),
                )
                for name, payload in artifacts.items():
                    cursor.execute(
                        """
                        INSERT INTO he_demo_artifacts
                            (session_id, artifact_name, payload, sha256)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (session_id, name, payload, sha256_hex(payload)),
                    )
                cursor.execute(
                    """
                    INSERT INTO he_demo_operations (session_id, operation, outcome)
                    VALUES (%s, 'initialize', 'COMPLETED')
                    """,
                    (session_id,),
                )

    def compute_operation(
        self,
        *,
        session_id: str,
        operation: str,
        required_status: str,
        completed_status: str,
        required_artifacts: Iterable[str],
        output_artifact: str,
        compute: Callable[[dict[str, bytes], int], bytes],
    ) -> OperationResult:
        names = tuple(required_artifacts)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT status, valid_count
                    FROM he_demo_sessions
                    WHERE session_id = %s
                    FOR UPDATE
                    """,
                    (session_id,),
                )
                session = cursor.fetchone()
                if session is None:
                    raise SessionStoreError(f"session does not exist: {session_id}")
                status, valid_count = str(session[0]), int(session[1])

                mode = operation_mode(status, required_status, completed_status)
                if mode == "REUSE":
                    existing = self._load_one(cursor, session_id, output_artifact)
                    return OperationResult(existing, reused=True)

                loaded = self._load_many(cursor, session_id, names)
                output = compute(loaded, valid_count)
                validate_artifact(output_artifact, output)
                cursor.execute(
                    """
                    INSERT INTO he_demo_artifacts
                        (session_id, artifact_name, payload, sha256)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        session_id,
                        output_artifact,
                        output,
                        sha256_hex(output),
                    ),
                )
                cursor.execute(
                    """
                    UPDATE he_demo_sessions
                    SET status = %s, updated_at = now()
                    WHERE session_id = %s
                    """,
                    (completed_status, session_id),
                )
                cursor.execute(
                    """
                    INSERT INTO he_demo_operations (session_id, operation, outcome)
                    VALUES (%s, %s, 'COMPLETED')
                    """,
                    (session_id, operation),
                )
                return OperationResult(output, reused=False)

    def verification_artifacts(
        self, session_id: str, result_artifact: str
    ) -> dict[str, bytes]:
        from .artifacts import (
            CONTEXT,
            KPI_RESULT_CIPHERTEXT,
            SUM_CIPHERTEXT,
            WRAPPED_SECRET_KEY,
        )

        allowed_statuses = {
            SUM_CIPHERTEXT: ("SUMMED", "MULTIPLIED", "VERIFIED"),
            KPI_RESULT_CIPHERTEXT: ("MULTIPLIED", "VERIFIED"),
        }
        if result_artifact not in allowed_statuses:
            raise SessionStoreError(
                f"artifact is not a verifiable result: {result_artifact}"
            )
        names = (CONTEXT, result_artifact, WRAPPED_SECRET_KEY)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT status FROM he_demo_sessions
                    WHERE session_id = %s FOR UPDATE
                    """,
                    (session_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    raise SessionStoreError(f"session does not exist: {session_id}")
                if str(row[0]) not in allowed_statuses[result_artifact]:
                    raise SessionStoreError(
                        f"cannot verify {result_artifact} at status {row[0]}"
                    )
                return self._load_many(cursor, session_id, names)

    def expected_values(self, session_id: str) -> tuple[Decimal, Decimal]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT expected_sum, expected_kpi_amount
                    FROM he_demo_results
                    WHERE session_id = %s
                    """,
                    (session_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    raise SessionStoreError(
                        f"session result is missing: {session_id}"
                    )
                if row[0] is None or row[1] is None:
                    raise SessionStoreError(
                        f"session expected values are incomplete: {session_id}"
                    )
                return Decimal(row[0]), Decimal(row[1])

    def record_verification(
        self,
        session_id: str,
        stage: str,
        decrypted_value: Decimal,
        absolute_error: Decimal,
        passed: bool,
    ) -> None:
        if stage not in ("sum", "kpi"):
            raise SessionStoreError(f"unknown verification stage: {stage}")
        operation = "verify_sum" if stage == "sum" else "verify_kpi"
        with self._connect() as connection:
            with connection.cursor() as cursor:
                if stage == "sum":
                    cursor.execute(
                        """
                        UPDATE he_demo_results
                        SET decrypted_sum = %s, sum_absolute_error = %s,
                            updated_at = now()
                        WHERE session_id = %s
                        """,
                        (decrypted_value, absolute_error, session_id),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE he_demo_results
                        SET decrypted_kpi_amount = %s,
                            kpi_absolute_error = %s,
                            updated_at = now()
                        WHERE session_id = %s
                        """,
                        (decrypted_value, absolute_error, session_id),
                    )
                if cursor.rowcount != 1:
                    raise SessionStoreError(
                        f"session result is missing: {session_id}"
                    )
                if stage == "sum":
                    cursor.execute(
                        """
                        UPDATE he_demo_sessions
                        SET updated_at = now()
                        WHERE session_id = %s
                          AND status IN ('SUMMED', 'MULTIPLIED', 'VERIFIED')
                        RETURNING session_id
                        """,
                        (session_id,),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE he_demo_sessions
                        SET status = CASE WHEN %s THEN 'VERIFIED' ELSE status END,
                            updated_at = now()
                        WHERE session_id = %s
                          AND status IN ('MULTIPLIED', 'VERIFIED')
                        RETURNING session_id
                        """,
                        (passed, session_id),
                    )
                if cursor.fetchone() is None:
                    raise SessionStoreError(
                        f"cannot verify {stage} at the current session status"
                    )
                cursor.execute(
                    """
                    INSERT INTO he_demo_operations
                        (session_id, operation, outcome)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (session_id, operation)
                    DO UPDATE SET outcome = EXCLUDED.outcome,
                                  completed_at = now()
                    """,
                    (session_id, operation, "PASSED" if passed else "FAILED"),
                )

    def inspect(self, session_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT s.scheme, s.status, s.valid_count, s.kpi_scale,
                           r.expected_sum, r.decrypted_sum,
                           r.sum_absolute_error, r.expected_kpi_amount,
                           r.decrypted_kpi_amount, r.kpi_absolute_error,
                           s.created_at, s.updated_at
                    FROM he_demo_sessions AS s
                    JOIN he_demo_results AS r USING (session_id)
                    WHERE s.session_id = %s
                    """,
                    (session_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    raise SessionStoreError(f"session does not exist: {session_id}")
                cursor.execute(
                    """
                    SELECT artifact_name, octet_length(payload), sha256
                    FROM he_demo_artifacts
                    WHERE session_id = %s
                    ORDER BY artifact_name
                    """,
                    (session_id,),
                )
                artifacts = [
                    {"name": name, "bytes": size, "sha256": digest}
                    for name, size, digest in cursor.fetchall()
                ]
                return {
                    "session_id": session_id,
                    "scheme": row[0],
                    "status": row[1],
                    "valid_count": row[2],
                    "kpi_scale": row[3],
                    "expected_sum": None if row[4] is None else str(row[4]),
                    "decrypted_sum": (
                        None if row[5] is None else str(row[5])
                    ),
                    "sum_absolute_error": (
                        None if row[6] is None else str(row[6])
                    ),
                    "expected_kpi_amount": (
                        None if row[7] is None else str(row[7])
                    ),
                    "decrypted_kpi_amount": (
                        None if row[8] is None else str(row[8])
                    ),
                    "kpi_absolute_error": (
                        None if row[9] is None else str(row[9])
                    ),
                    "created_at": row[10].isoformat(),
                    "updated_at": row[11].isoformat(),
                    "artifacts": artifacts,
                }

    def artifacts(self, session_id: str, names: Iterable[str]) -> dict[str, bytes]:
        """Load named artifacts for a trusted demo command."""
        with self._connect() as connection:
            with connection.cursor() as cursor:
                return self._load_many(cursor, session_id, names)

    @staticmethod
    def _load_one(cursor: Any, session_id: str, name: str) -> bytes:
        cursor.execute(
            """
            SELECT payload, sha256 FROM he_demo_artifacts
            WHERE session_id = %s AND artifact_name = %s
            """,
            (session_id, name),
        )
        row = cursor.fetchone()
        if row is None:
            raise SessionStoreError(f"session artifact is missing: {name}")
        payload = _bytes(row[0])
        if sha256_hex(payload) != str(row[1]):
            raise SessionStoreError(f"session artifact hash mismatch: {name}")
        return payload

    @classmethod
    def _load_many(
        cls, cursor: Any, session_id: str, names: Iterable[str]
    ) -> dict[str, bytes]:
        return {name: cls._load_one(cursor, session_id, name) for name in names}
