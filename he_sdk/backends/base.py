"""Backend protocol and factories used by :class:`he_sdk.HESession`."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, Sequence

from he_sdk.config import CKKSConfig
from he_sdk.contracts import CapabilitySet
from he_sdk.errors import BackendUnavailableError


class HEBackend(Protocol):
    name: str
    engine_version: str
    context_id: str
    key_bundle_id: str
    capabilities: CapabilitySet
    has_secret_key: bool

    def __init__(self, config: CKKSConfig) -> None: ...

    def encrypt(self, values: Sequence[float]) -> Any: ...

    def decrypt(self, encrypted: Any, length: int) -> list[float]: ...

    def add(self, left: Any, right: Any) -> Any: ...

    def subtract(self, left: Any, right: Any) -> Any: ...

    def multiply(self, left: Any, right: Any) -> Any: ...

    def square(self, encrypted: Any) -> Any: ...

    def sum(self, encrypted: Any, valid_count: int) -> Any: ...

    def mean(self, encrypted: Any, valid_count: int) -> Any: ...

    def variance(self, encrypted: Any, valid_count: int) -> Any: ...

    def create_result_recipient(self) -> tuple[str, Any, Any]: ...

    def reencrypt_for_recipient(
        self, encrypted: Any, recipient_public_key: Any
    ) -> Any: ...

    def decrypt_for_recipient(
        self, encrypted: Any, recipient_secret_key: Any, length: int
    ) -> list[float]: ...

    def serialize_public_key(self, public_key: Any, path: Path) -> None: ...

    def deserialize_public_key(self, path: Path) -> Any: ...

    def export_public_material(self, directory: Path) -> None: ...

    def serialize_ciphertext(self, encrypted: Any, path: Path) -> None: ...

    def deserialize_ciphertext(self, path: Path) -> Any: ...

    def close(self) -> None: ...


def create_backend(name: str, config: CKKSConfig) -> HEBackend:
    """Create a trusted backend that owns its HE keys."""
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


def create_backend_from_public_material(
    name: str,
    config: CKKSConfig,
    directory: Path,
    *,
    context_id: str,
    key_bundle_id: str,
) -> HEBackend:
    """Open a compute-only backend from persisted public HE material."""
    normalized = name.strip().lower()
    if normalized == "openfhe":
        from he_sdk.backends.openfhe import OpenFHEBackend

        return OpenFHEBackend.from_public_material(
            config,
            directory,
            context_id=context_id,
            key_bundle_id=key_bundle_id,
        )
    if normalized == "fides":
        try:
            from he_sdk_fides import FidesBackend
        except (ImportError, OSError) as error:
            raise BackendUnavailableError(
                "The optional he-sdk-fides package is not installed. Install "
                "the CUDA/Linux wheel built for the target GPU server."
            ) from error
        return FidesBackend.from_public_material(
            config,
            directory,
            context_id=context_id,
            key_bundle_id=key_bundle_id,
        )
    raise ValueError(
        f"backend {name!r} does not support persisted public material"
    )


__all__ = [
    "HEBackend",
    "create_backend",
    "create_backend_from_public_material",
]
