"""Validated command contract for the Kubernetes HE worker."""

from __future__ import annotations

from dataclasses import dataclass
import os


BINARY_OPERATIONS = ("add", "subtract", "multiply")
UNARY_OPERATIONS = ("square", "sum", "mean", "variance")
OPERATIONS = BINARY_OPERATIONS + UNARY_OPERATIONS
EXECUTION_BACKENDS = ("openfhe", "fides")


@dataclass(frozen=True)
class WorkerRequest:
    workspace: str
    operation: str
    left: str
    output: str
    right: str | None = None
    execution_backend: str | None = None
    overwrite: bool = False

    def validate(self) -> "WorkerRequest":
        if not self.workspace:
            raise ValueError("workspace is required")
        if self.operation not in OPERATIONS:
            raise ValueError(
                f"unsupported operation {self.operation!r}; expected one of "
                + ", ".join(OPERATIONS)
            )
        if not self.left:
            raise ValueError("left input artifact name is required")
        if not self.output:
            raise ValueError("output artifact name is required")
        if self.operation in BINARY_OPERATIONS and not self.right:
            raise ValueError(f"{self.operation} requires a right input artifact")
        if self.operation in UNARY_OPERATIONS and self.right:
            raise ValueError(f"{self.operation} does not accept a right input")
        if self.output in (self.left, self.right):
            raise ValueError("output must not overwrite an input artifact")
        if (
            self.execution_backend is not None
            and self.execution_backend not in EXECUTION_BACKENDS
        ):
            raise ValueError(
                "execution backend must be openfhe or fides"
            )
        return self

    @classmethod
    def from_environment(cls) -> "WorkerRequest":
        backend = os.getenv("HE_EXECUTION_BACKEND") or None
        return cls(
            workspace=os.getenv("HE_WORKSPACE", ""),
            operation=os.getenv("HE_OPERATION", ""),
            left=os.getenv("HE_LEFT", ""),
            right=os.getenv("HE_RIGHT") or None,
            output=os.getenv("HE_OUTPUT", ""),
            execution_backend=backend,
            overwrite=os.getenv("HE_OVERWRITE", "false").lower()
            in ("1", "true", "yes"),
        ).validate()
