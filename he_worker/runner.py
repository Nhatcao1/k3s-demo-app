"""One-process HE workspace execution through the public SDK contract."""

from __future__ import annotations

from typing import Any

from he_sdk import EncryptedVector, HESession
from he_sdk.artifacts import list_ciphertexts

from he_worker.request import BINARY_OPERATIONS, WorkerRequest


def execute(request: WorkerRequest) -> dict[str, Any]:
    """Execute and persist exactly one operation, returning safe metadata."""
    request.validate()
    existing = set(list_ciphertexts(request.workspace))
    if request.output in existing and not request.overwrite:
        raise ValueError(
            f"output artifact {request.output!r} already exists; set "
            "HE_OVERWRITE=true only for an intentional replacement"
        )

    with HESession.open_workspace(
        request.workspace,
        execution_backend=request.execution_backend,
    ) as session:
        left = session.load(request.workspace, name=request.left)
        if not isinstance(left, EncryptedVector):
            raise TypeError("left input must be an EncryptedVector")

        if request.operation in BINARY_OPERATIONS:
            assert request.right is not None
            right = session.load(request.workspace, name=request.right)
            if not isinstance(right, EncryptedVector):
                raise TypeError("right input must be an EncryptedVector")
            result = getattr(session, request.operation)(left, right)
        else:
            result = getattr(session, request.operation)(left)

        output_path = session.save(
            result,
            request.workspace,
            name=request.output,
        )
        return {
            "status": "completed",
            "execution_backend": session.capabilities.backend,
            "artifact_backend": result.metadata.backend,
            "operation": request.operation,
            "left": request.left,
            "right": request.right,
            "output": request.output,
            "output_path": str(output_path),
            "context_id": result.metadata.context_id,
            "key_bundle_id": result.metadata.key_bundle_id,
            "contains_plaintext": False,
            "contains_secret_key": False,
        }
