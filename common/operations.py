"""Small logical operation contract with no HE-library dependency."""

from __future__ import annotations


PRIMITIVE_OPERATIONS = ("add", "subtract", "multiply")
REDUCTION_OPERATIONS = ("sum",)
OPERATIONS = PRIMITIVE_OPERATIONS + REDUCTION_OPERATIONS


def validate_operation(value: object) -> str:
    if not isinstance(value, str) or value not in OPERATIONS:
        raise ValueError(f"operation must be one of: {', '.join(OPERATIONS)}")
    return value


def needs_right_ciphertext(operation: str) -> bool:
    return operation in PRIMITIVE_OPERATIONS


def needs_evaluation_keys(operation: str) -> bool:
    return operation in ("multiply", "sum")
