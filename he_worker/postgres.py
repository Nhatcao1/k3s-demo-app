"""PostgreSQL transport for secretless SDK workspaces.

PostgreSQL is a small-lab artifact bridge between notebook, CPU nodes, and GPU
nodes. It is not the long-term large-object store. Only public/evaluation
material, manifests, and ciphertexts accepted by the workspace contract are
materialized here.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
from typing import Any

from he_worker.request import WorkerRequest
from he_worker.runner import execute


def _connect():
    try:
        import psycopg
    except ImportError as error:
        raise RuntimeError(
            "PostgreSQL workload mode requires psycopg[binary]"
        ) from error
    password = os.getenv("HE_DB_PASSWORD")
    if not password:
        raise RuntimeError("HE_DB_PASSWORD is required for PostgreSQL mode")
    return psycopg.connect(
        host=os.getenv("HE_DB_HOST", "he-postgres"),
        port=int(os.getenv("HE_DB_PORT", "5432")),
        dbname=os.getenv("HE_DB_NAME", "he_store"),
        user=os.getenv("HE_DB_USER", "he_app"),
        password=password,
        connect_timeout=int(os.getenv("HE_DB_CONNECT_TIMEOUT", "10")),
    )


def _safe_relative_path(raw: object) -> PurePosixPath:
    if not isinstance(raw, str) or not raw:
        raise ValueError("stored artifact has no workspace_path")
    relative = PurePosixPath(raw)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe stored artifact path: {raw}")
    if any(
        token in raw.lower()
        for token in ("secret", "private_key", "secret_key")
    ):
        raise ValueError(f"refusing secret-like artifact path: {raw}")
    return relative


def _artifact_type(relative_path: str) -> str:
    name = relative_path.lower()
    if relative_path == "manifest.json":
        return "manifest"
    _safe_relative_path(relative_path)
    if "eval" in name or "rotation" in name or "relin" in name:
        return "evaluation_key"
    if "public" in name and "key" in name:
        return "public_key"
    if "context" in name or "crypto" in name:
        return "context"
    return "ciphertext"


def _set_running(connection: Any, run_id: int, request: WorkerRequest) -> None:
    backend = request.execution_backend or "openfhe"
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE he_store.runs
            SET status = 'running', backend = %s, operation = %s,
                started_at = now(), completed_at = NULL, error_message = NULL
            WHERE id = %s
            """,
            (backend, request.operation, run_id),
        )
        if cursor.rowcount != 1:
            raise ValueError(f"HE run not found: {run_id}")
    connection.commit()


def _set_finished(
    connection: Any,
    run_id: int,
    *,
    status: str,
    error_message: str | None = None,
) -> None:
    if status not in ("succeeded", "failed"):
        raise ValueError("final run status must be succeeded or failed")
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE he_store.runs
            SET status = %s, completed_at = now(), error_message = %s
            WHERE id = %s
            """,
            (status, error_message, run_id),
        )
    connection.commit()


def _load_workspace(connection: Any, run_id: int, workspace: Path) -> int:
    with connection.cursor() as cursor:
        rows = cursor.execute(
            """
            SELECT DISTINCT ON (metadata->>'workspace_path')
                   payload, sha256, metadata->>'workspace_path'
            FROM he_store.artifacts
            WHERE run_id = %s
              AND metadata->>'workspace_path' IS NOT NULL
            ORDER BY metadata->>'workspace_path', id DESC
            """,
            (run_id,),
        ).fetchall()
    if not rows:
        raise ValueError(f"HE run {run_id} has no stored workspace artifacts")

    for payload, checksum, raw_path in rows:
        relative = _safe_relative_path(raw_path)
        value = bytes(payload)
        if hashlib.sha256(value).hexdigest() != checksum:
            raise ValueError(f"stored artifact checksum failed: {raw_path}")
        destination = workspace.joinpath(*relative.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(value)

    manifest_path = workspace / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("contains_plaintext") is not False
        or manifest.get("contains_secret_key") is not False
    ):
        raise ValueError("stored workspace violates the SDK secretless boundary")
    return len(rows)


def _publish_workspace(connection: Any, run_id: int, workspace: Path) -> int:
    try:
        from psycopg.types.json import Jsonb
    except ImportError as error:
        raise RuntimeError(
            "PostgreSQL workload mode requires psycopg[binary]"
        ) from error

    manifest = json.loads((workspace / "manifest.json").read_text(encoding="utf-8"))
    if (
        manifest.get("contains_plaintext") is not False
        or manifest.get("contains_secret_key") is not False
    ):
        raise ValueError("refusing to publish a non-secretless workspace")

    inserted = 0
    with connection.cursor() as cursor:
        for path in sorted(item for item in workspace.rglob("*") if item.is_file()):
            relative_path = path.relative_to(workspace).as_posix()
            artifact_type = _artifact_type(relative_path)
            payload = path.read_bytes()
            checksum = hashlib.sha256(payload).hexdigest()
            cursor.execute(
                """
                INSERT INTO he_store.artifacts
                    (run_id, artifact_type, encoding, payload, sha256, metadata)
                VALUES (%s, %s, 'binary', %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (
                    run_id,
                    artifact_type,
                    payload,
                    checksum,
                    Jsonb({"workspace_path": relative_path}),
                ),
            )
            inserted += max(cursor.rowcount, 0)
    connection.commit()
    return inserted


def execute_postgres(request: WorkerRequest, run_id: int) -> dict[str, Any]:
    """Materialize, execute, and republish one database-backed HE run."""
    if run_id <= 0:
        raise ValueError("run id must be a positive integer")
    connection = _connect()
    try:
        _set_running(connection, run_id, request)
        try:
            with tempfile.TemporaryDirectory(prefix="he-sdk-worker-") as temporary:
                workspace = Path(temporary) / "workspace"
                workspace.mkdir()
                downloaded = _load_workspace(connection, run_id, workspace)
                local_request = replace(request, workspace=str(workspace)).validate()
                result = execute(local_request)
                uploaded = _publish_workspace(connection, run_id, workspace)
        except Exception as error:
            _set_finished(
                connection,
                run_id,
                status="failed",
                error_message=f"{type(error).__name__}: {error}"[:2000],
            )
            raise
        _set_finished(connection, run_id, status="succeeded")
        result.update(
            {
                "storage": "postgresql",
                "run_id": run_id,
                "downloaded_artifacts": downloaded,
                "uploaded_artifacts": uploaded,
                "output_path": f"run:{run_id}/ciphertexts/{request.output}.bin",
            }
        )
        return result
    finally:
        connection.close()
