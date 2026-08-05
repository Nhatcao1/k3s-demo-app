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
        expected_amount: Decimal,
        artifacts: dict[str, bytes],
    ) -> None:
        validate_initial_artifacts(artifacts)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO he_demo_sessions
                        (session_id, scheme, status, valid_count, kpi_scale,
                         expected_amount)
                    VALUES (%s, %s, 'INITIALIZED', %s, %s, %s)
                    """,
                    (
                        session_id,
                        scheme,
                        valid_count,
                        kpi_scale,
                        expected_amount,
                    ),
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

    def verification_artifacts(self, session_id: str) -> dict[str, bytes]:
        from .artifacts import CONTEXT, KPI_RESULT_CIPHERTEXT, WRAPPED_SECRET_KEY

        names = (CONTEXT, KPI_RESULT_CIPHERTEXT, WRAPPED_SECRET_KEY)
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
                if str(row[0]) not in ("MULTIPLIED", "VERIFIED"):
                    raise SessionStoreError(
                        f"verify requires MULTIPLIED, current status is {row[0]}"
                    )
                return self._load_many(cursor, session_id, names)

    def mark_verified(
        self,
        session_id: str,
        decrypted_amount: Decimal,
        absolute_error: Decimal,
    ) -> bool:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE he_demo_sessions
                    SET status = 'VERIFIED', decrypted_amount = %s,
                        absolute_error = %s, updated_at = now()
                    WHERE session_id = %s
                      AND status IN ('MULTIPLIED', 'VERIFIED')
                    RETURNING session_id
                    """,
                    (decrypted_amount, absolute_error, session_id),
                )
                changed = cursor.fetchone() is not None
                if changed:
                    cursor.execute(
                        """
                        INSERT INTO he_demo_operations
                            (session_id, operation, outcome)
                        VALUES (%s, 'verify', 'COMPLETED')
                        ON CONFLICT (session_id, operation) DO NOTHING
                        """,
                        (session_id,),
                    )
                return changed

    def inspect(self, session_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT scheme, status, valid_count, kpi_scale,
                           expected_amount, decrypted_amount, absolute_error,
                           created_at, updated_at
                    FROM he_demo_sessions WHERE session_id = %s
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
                    "expected_amount": None if row[4] is None else str(row[4]),
                    "decrypted_amount": (
                        None if row[5] is None else str(row[5])
                    ),
                    "absolute_error": None if row[6] is None else str(row[6]),
                    "created_at": row[7].isoformat(),
                    "updated_at": row[8].isoformat(),
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
