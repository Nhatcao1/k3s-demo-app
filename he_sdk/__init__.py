"""Local, backend-neutral homomorphic-encryption SDK."""

from he_sdk.capabilities import CapabilitySet
from he_sdk.ciphertext import (
    CiphertextMetadata,
    EncryptedScalar,
    EncryptedVector,
)
from he_sdk.config import CKKSConfig
from he_sdk.errors import (
    ArtifactError,
    BackendUnavailableError,
    HEError,
    IncompatibleCiphertextError,
    SessionClosedError,
    SecretKeyUnavailableError,
    UnsupportedOperationError,
)
from he_sdk.session import HESession
from he_sdk.operations import OPERATION_CONTRACTS, OperationContract

__all__ = [
    "ArtifactError",
    "BackendUnavailableError",
    "CKKSConfig",
    "CapabilitySet",
    "CiphertextMetadata",
    "EncryptedScalar",
    "EncryptedVector",
    "HEError",
    "HESession",
    "IncompatibleCiphertextError",
    "OPERATION_CONTRACTS",
    "OperationContract",
    "SessionClosedError",
    "SecretKeyUnavailableError",
    "UnsupportedOperationError",
]

__version__ = "0.4.0"
