"""Local, backend-neutral homomorphic-encryption SDK."""

from he_sdk.capabilities import CapabilitySet
from he_sdk.ciphertext import (
    CiphertextMetadata,
    EncryptedScalar,
    EncryptedVector,
)
from he_sdk.config import CKKSConfig
from he_sdk.errors import (
    BackendUnavailableError,
    HEError,
    IncompatibleCiphertextError,
    SessionClosedError,
    UnsupportedOperationError,
)
from he_sdk.session import HESession
from he_sdk.operations import OPERATION_CONTRACTS, OperationContract

__all__ = [
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
    "UnsupportedOperationError",
]

__version__ = "0.3.0"
