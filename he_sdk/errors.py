"""Public exceptions raised by the local HE SDK."""

from __future__ import annotations


class HEError(RuntimeError):
    """Base exception for SDK failures."""


class BackendUnavailableError(HEError):
    """The requested native backend is not installed or ready."""


class UnsupportedOperationError(HEError):
    """The selected backend cannot execute an operation."""


class IncompatibleCiphertextError(HEError, ValueError):
    """Ciphertexts cannot safely be used in the requested operation."""


class SessionClosedError(HEError):
    """An operation was attempted after a session was closed."""


class SecretKeyUnavailableError(HEError):
    """Decryption was requested from a compute-only session."""


class ArtifactError(HEError, ValueError):
    """A persisted HE workspace is missing, corrupt, or incompatible."""


class ResultReleaseError(HEError, ValueError):
    """A ciphertext is not eligible for result-only analyst release."""
