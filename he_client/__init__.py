"""Dependency-free client for the trusted HE gateway."""

from .client import (
    CorrelationComponents,
    CovarianceComponents,
    HEClient,
    HEClientError,
    PublicScalar,
    PublicVector,
    RemoteCiphertext,
    VarianceComponents,
)

EncryptedVector = RemoteCiphertext
EncryptedScalar = RemoteCiphertext

__all__ = [
    "CorrelationComponents",
    "CovarianceComponents",
    "EncryptedScalar",
    "EncryptedVector",
    "HEClient",
    "HEClientError",
    "PublicScalar",
    "PublicVector",
    "RemoteCiphertext",
    "VarianceComponents",
]
