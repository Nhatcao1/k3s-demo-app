"""SDK-level contracts for operation names shared with the K3s service."""

from __future__ import annotations

from dataclasses import dataclass

from common.operations import OPERATIONS


@dataclass(frozen=True)
class OperationContract:
    name: str
    inputs: str
    output: str
    depth_cost: int
    requires_multiplication_keys: bool
    requires_rotation_keys: bool
    chunk_policy: str


OPERATION_CONTRACTS = {
    "add": OperationContract(
        "add", "two equal packed vectors", "packed vector", 0, False, False,
        "matching chunks",
    ),
    "subtract": OperationContract(
        "subtract", "two equal packed vectors", "packed vector", 0, False,
        False, "matching chunks",
    ),
    "multiply": OperationContract(
        "multiply", "two equal packed vectors", "packed vector", 1, True,
        False, "matching chunks",
    ),
    "square": OperationContract(
        "square", "one packed vector", "packed vector", 1, True, False,
        "independent chunks",
    ),
    "sum": OperationContract(
        "sum", "one packed vector", "encrypted scalar", 0, False, True,
        "encrypted reduction across all chunks",
    ),
    "mean": OperationContract(
        "mean", "one packed vector", "encrypted scalar", 1, False, True,
        "global sum scaled by total logical count",
    ),
    "variance": OperationContract(
        "variance", "one packed vector", "encrypted scalar", 2, True, True,
        "global encrypted first and second moments",
    ),
}

if tuple(OPERATION_CONTRACTS) != OPERATIONS:
    raise RuntimeError(
        "SDK operation contracts must match common.operations.OPERATIONS"
    )
