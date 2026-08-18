"""Local, backend-neutral homomorphic-encryption SDK."""

from he_sdk.capabilities import CapabilitySet
from he_sdk.ciphertext import (
    CiphertextChunkMetadata,
    CiphertextMetadata,
    EncryptedScalar,
    EncryptedVector,
)
from he_sdk.config import CKKSConfig
from he_sdk.errors import (
    ArtifactError,
    BackendUnavailableError,
    HEError,
    InsufficientLevelError,
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
    "CiphertextChunkMetadata",
    "CiphertextMetadata",
    "EncryptedScalar",
    "EncryptedVector",
    "HEError",
    "HESession",
    "InsufficientLevelError",
    "IncompatibleCiphertextError",
    "OPERATION_CONTRACTS",
    "OperationContract",
    "SessionClosedError",
    "SecretKeyUnavailableError",
    "UnsupportedOperationError",
]

__version__ = "0.5.0.dev0"
