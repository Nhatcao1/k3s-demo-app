"""Backend selection for the local SDK."""

from __future__ import annotations

from he_sdk.backends.base import HEBackend
from he_sdk.config import CKKSConfig
from he_sdk.errors import BackendUnavailableError


def create_backend(name: str, config: CKKSConfig) -> HEBackend:
    normalized = name.strip().lower()
    if normalized == "openfhe":
        from he_sdk.backends.openfhe import OpenFHEBackend

        return OpenFHEBackend(config)
    if normalized == "fides":
        try:
            from he_sdk_fides import FidesBackend
        except (ImportError, OSError) as error:
            raise BackendUnavailableError(
                "The optional he-sdk-fides package is not installed. Install "
                "the CUDA/Linux wheel built for the target GPU server."
            ) from error
        return FidesBackend(config)
    raise ValueError(f"unknown HE backend: {name}")


__all__ = ["HEBackend", "create_backend"]
