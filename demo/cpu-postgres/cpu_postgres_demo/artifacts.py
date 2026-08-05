"""Artifact names and secret-key envelope helpers."""

from __future__ import annotations

import hashlib
import secrets


CONTEXT = "crypto_context"
SALARY_CIPHERTEXT = "salary_ciphertext"
KPI_CIPHERTEXT = "kpi_ciphertext"
SUM_EVALUATION_KEYS = "sum_evaluation_keys"
MULTIPLICATION_EVALUATION_KEYS = "multiplication_evaluation_keys"
WRAPPED_SECRET_KEY = "wrapped_secret_key"
SUM_CIPHERTEXT = "sum_ciphertext"
KPI_RESULT_CIPHERTEXT = "kpi_result_ciphertext"

ALLOWED_ARTIFACTS = frozenset(
    {
        CONTEXT,
        SALARY_CIPHERTEXT,
        KPI_CIPHERTEXT,
        SUM_EVALUATION_KEYS,
        MULTIPLICATION_EVALUATION_KEYS,
        WRAPPED_SECRET_KEY,
        SUM_CIPHERTEXT,
        KPI_RESULT_CIPHERTEXT,
    }
)
INITIAL_ARTIFACTS = frozenset(
    {
        CONTEXT,
        SALARY_CIPHERTEXT,
        KPI_CIPHERTEXT,
        SUM_EVALUATION_KEYS,
        MULTIPLICATION_EVALUATION_KEYS,
        WRAPPED_SECRET_KEY,
    }
)
FORBIDDEN_RAW_KEY_NAMES = frozenset(
    {"secret_key", "private_key", "raw_secret_key", "raw_private_key"}
)
ENVELOPE_MAGIC = b"HEK1"
NONCE_BYTES = 12


class ArtifactError(ValueError):
    """An artifact violates the demo storage contract."""


def validate_artifact(name: str, payload: bytes) -> None:
    if name in FORBIDDEN_RAW_KEY_NAMES or name not in ALLOWED_ARTIFACTS:
        raise ArtifactError(f"artifact name is not allowed: {name}")
    if not isinstance(payload, bytes) or not payload:
        raise ArtifactError(f"artifact {name} must contain bytes")


def validate_initial_artifacts(artifacts: dict[str, bytes]) -> None:
    names = frozenset(artifacts)
    if names != INITIAL_ARTIFACTS:
        missing = sorted(INITIAL_ARTIFACTS - names)
        unexpected = sorted(names - INITIAL_ARTIFACTS)
        detail = []
        if missing:
            detail.append("missing: " + ", ".join(missing))
        if unexpected:
            detail.append("unexpected: " + ", ".join(unexpected))
        raise ArtifactError("invalid initial artifacts (" + "; ".join(detail) + ")")
    for name, payload in artifacts.items():
        validate_artifact(name, payload)


def sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def wrap_secret_key(secret_key: bytes, wrapping_key: bytes, session_id: str) -> bytes:
    if not secret_key:
        raise ArtifactError("secret key cannot be empty")
    if len(wrapping_key) != 32:
        raise ArtifactError("wrapping key must contain exactly 32 bytes")
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = secrets.token_bytes(NONCE_BYTES)
    ciphertext = AESGCM(wrapping_key).encrypt(
        nonce, secret_key, session_id.encode("utf-8")
    )
    return ENVELOPE_MAGIC + nonce + ciphertext


def unwrap_secret_key(envelope: bytes, wrapping_key: bytes, session_id: str) -> bytes:
    if len(wrapping_key) != 32:
        raise ArtifactError("wrapping key must contain exactly 32 bytes")
    if not envelope.startswith(ENVELOPE_MAGIC):
        raise ArtifactError("secret-key envelope has an unsupported format")
    minimum = len(ENVELOPE_MAGIC) + NONCE_BYTES + 16
    if len(envelope) < minimum:
        raise ArtifactError("secret-key envelope is truncated")
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce_start = len(ENVELOPE_MAGIC)
    nonce_end = nonce_start + NONCE_BYTES
    return AESGCM(wrapping_key).decrypt(
        envelope[nonce_start:nonce_end],
        envelope[nonce_end:],
        session_id.encode("utf-8"),
    )
