"""Small logical operation list with no HE-library dependency."""

from __future__ import annotations


BINARY_OPERATIONS = ("add", "subtract", "multiply")
UNARY_OPERATIONS = ("square",)
REDUCTION_OPERATIONS = ("sum", "mean")
OPERATIONS = BINARY_OPERATIONS + UNARY_OPERATIONS + REDUCTION_OPERATIONS


def validate_operation(value: object) -> str:
    if not isinstance(value, str) or value not in OPERATIONS:
        raise ValueError(f"operation must be one of: {', '.join(OPERATIONS)}")
    return value


def needs_right_ciphertext(operation: str) -> bool:
    return operation in BINARY_OPERATIONS


def needs_evaluation_keys(operation: str) -> bool:
    return operation in ("multiply", "square", "sum", "mean")


def needs_valid_count(operation: str) -> bool:
    return operation in REDUCTION_OPERATIONS
