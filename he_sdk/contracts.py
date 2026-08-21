"""Operation requirements and backend capability declarations."""

from __future__ import annotations

from dataclasses import dataclass

from common.operations import OPERATIONS


@dataclass(frozen=True)
class OperationContract:
    """Static requirements shared by every implementation of an operation."""

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
        "single ciphertext in SDK v1",
    ),
    "mean": OperationContract(
        "mean", "one packed vector", "encrypted scalar", 1, False, True,
        "single ciphertext in SDK v1",
    ),
    "variance": OperationContract(
        "variance", "one packed vector", "encrypted scalar", 2, True, True,
        "single ciphertext in SDK v1",
    ),
}

if tuple(OPERATION_CONTRACTS) != OPERATIONS:
    raise RuntimeError(
        "SDK operation contracts must match common.operations.OPERATIONS"
    )


@dataclass(frozen=True)
class CapabilitySet:
    """Features and operation contracts exposed by one backend."""

    backend: str
    schemes: tuple[str, ...]
    operations: tuple[str, ...]
    supports_bootstrap: bool = False
    supports_serialization: bool = False
    supports_proxy_re_encryption: bool = False

    def supports(self, operation: str) -> bool:
        return operation in self.operations


__all__ = [
    "CapabilitySet",
    "OPERATION_CONTRACTS",
    "OperationContract",
]
