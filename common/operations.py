"""Small logical operation list with no HE-library dependency."""

from __future__ import annotations


PRIMITIVE_OPERATIONS = ("add", "subtract", "multiply")
PLAINTEXT_OPERATIONS = ("multiply_plain",)
UNARY_OPERATIONS = ("square",)
REDUCTION_OPERATIONS = ("sum", "mean", "variance")
OPERATIONS = (
    PRIMITIVE_OPERATIONS
    + PLAINTEXT_OPERATIONS
    + UNARY_OPERATIONS
    + REDUCTION_OPERATIONS
)

MULTIPLICATION_KEY_OPERATIONS = ("multiply", "square", "variance")
ROTATION_KEY_OPERATIONS = ("sum", "mean", "variance")


def validate_operation(value: object) -> str:
    if not isinstance(value, str) or value not in OPERATIONS:
        raise ValueError(f"operation must be one of: {', '.join(OPERATIONS)}")
    return value


def needs_right_ciphertext(operation: str) -> bool:
    return operation in PRIMITIVE_OPERATIONS


def needs_plaintext(operation: str) -> bool:
    return operation in PLAINTEXT_OPERATIONS


def needs_evaluation_keys(operation: str) -> bool:
    """Legacy single-key field used by operations needing only one key type."""
    return operation in ("multiply", "square", "sum", "mean")


def needs_multiplication_keys(operation: str) -> bool:
    return operation in MULTIPLICATION_KEY_OPERATIONS


def needs_rotation_keys(operation: str) -> bool:
    return operation in ROTATION_KEY_OPERATIONS


def needs_valid_count(operation: str) -> bool:
    return operation in REDUCTION_OPERATIONS
