"""Backend protocol and factories used by :class:`he_sdk.HESession`."""

from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path
from typing import Any, Protocol, Sequence

from he_sdk.config import CKKSConfig
from he_sdk.contracts import CapabilitySet
from he_sdk.errors import BackendUnavailableError
from he_sdk.native_runtime import claim_native_runtime


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


def resolve_backend_name(name: str | None = None) -> str:
    """Map public CPU/GPU names or detect the single installed component."""
    if name is not None:
        normalized = name.strip().lower()
        aliases = {
            "cpu": "openfhe",
            "gpu": "fides",
            "openfhe": "openfhe",
            "fides": "fides",
        }
        if normalized != "auto":
            try:
                return aliases[normalized]
            except KeyError as error:
                raise ValueError(f"unknown HE device/backend: {name}") from error

    installed: list[str] = []
    if find_spec("openfhe") is not None:
        installed.append("openfhe")
    if find_spec("he_sdk_fides") is not None:
        installed.append("fides")

    if len(installed) == 1:
        return installed[0]
    if not installed:
        raise BackendUnavailableError(
            "No HE backend is installed. Install he_looming_sdk[cpu] or "
            "he_looming_sdk[gpu] in this Python environment."
        )
    raise BackendUnavailableError(
        "Both CPU and GPU native backends are installed. Use separate Python "
        "environments, or explicitly select device='cpu' or device='gpu'."
    )


def create_backend(name: str | None, config: CKKSConfig) -> HEBackend:
    """Create a trusted backend that owns its HE keys."""
    normalized = resolve_backend_name(name)
    if normalized == "openfhe":
        from he_sdk.backends.openfhe import OpenFHEBackend

        claim_native_runtime("openfhe")
        return OpenFHEBackend(config)
    if normalized == "fides":
        try:
            from he_sdk_fides import FidesBackend
        except (ImportError, OSError) as error:
            raise BackendUnavailableError(
                "The he-sdk-fides component is unavailable. Reinstall "
                "he_looming_sdk in the supported CUDA/Linux environment."
            ) from error
        claim_native_runtime("fides")
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
    normalized = resolve_backend_name(name)
    if normalized == "openfhe":
        from he_sdk.backends.openfhe import OpenFHEBackend

        claim_native_runtime("openfhe")
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
                "The he-sdk-fides component is unavailable. Reinstall "
                "he_looming_sdk in the supported CUDA/Linux environment."
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
    "resolve_backend_name",
]
