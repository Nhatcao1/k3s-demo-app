"""Local OpenFHE adapter reusing the existing CPU function implementation."""

from __future__ import annotations

import importlib
from pathlib import Path
import threading
from typing import Any, Sequence
import uuid

from he_sdk.capabilities import CapabilitySet
from he_sdk.config import CKKSConfig
from he_sdk.errors import BackendUnavailableError
from he_sdk.operations import OPERATION_CONTRACTS
from openfhe_cpu.runtime import (
    BATCH_SIZE,
    FIRST_MOD_SIZE,
    MULTIPLICATIVE_DEPTH,
    RING_DIMENSION,
    SCALING_MOD_SIZE,
    OpenFHECPU,
)


class OpenFHEBackend:
    """Trusted local backend that owns context, keys and native objects."""

    name = "openfhe"
    capabilities = CapabilitySet(
        backend=name,
        schemes=("CKKS",),
        operations=tuple(OPERATION_CONTRACTS),
        supports_bootstrap=False,
        supports_serialization=True,
        supports_proxy_re_encryption=True,
    )
    _lease_lock = threading.Lock()

    def __init__(self, config: CKKSConfig) -> None:
        supported = {
            "multiplicative_depth": MULTIPLICATIVE_DEPTH,
            "first_modulus_size": FIRST_MOD_SIZE,
            "scaling_modulus_size": SCALING_MOD_SIZE,
            "ring_dimension": RING_DIMENSION,
            "batch_size": BATCH_SIZE,
        }
        mismatches = [
            f"{name}={getattr(config, name)!r} (supported {expected!r})"
            for name, expected in supported.items()
            if getattr(config, name) != expected
        ]
        if config.scaling_technique != "FLEXIBLEAUTO":
            mismatches.append(
                "scaling_technique="
                f"{config.scaling_technique!r} (supported 'FLEXIBLEAUTO')"
            )
        if config.bootstrap_enabled:
            mismatches.append("bootstrap_enabled=True (supported False)")
        fixed_fields = {
            "security_level": "HEStd_128_classic",
            "key_switch_technique": "library-default",
            "secret_key_distribution": "library-default",
            "input_scale": 1.0,
            "compression_mode": "none",
            "serialization_version": "openfhe-binary-v1",
        }
        mismatches.extend(
            f"{name}={getattr(config, name)!r} (supported {expected!r})"
            for name, expected in fixed_fields.items()
            if getattr(config, name) != expected
        )
        if config.rotation_indices:
            mismatches.append("custom rotation_indices are not implemented")
        if not config.generate_multiplication_keys:
            mismatches.append(
                "generate_multiplication_keys=False is not implemented"
            )
        if not config.generate_sum_keys:
            mismatches.append("generate_sum_keys=False is not implemented")
        if mismatches:
            raise ValueError(
                "OpenFHE backend does not support this profile: "
                + "; ".join(mismatches)
            )

        try:
            module = importlib.import_module("openfhe")
        except (ImportError, OSError) as error:
            raise BackendUnavailableError(
                "OpenFHE is not installed. Install the 'openfhe' SDK extra "
                "on supported Linux, or run this integration in GitLab CI."
            ) from error

        if not self._lease_lock.acquire(blocking=False):
            raise BackendUnavailableError(
                "Only one local OpenFHE HESession may be active per process. "
                "The pinned binding uses process-global evaluation-key state."
            )
        self._owns_lease = True
        try:
            self.engine_version = str(
                getattr(module, "__version__", "openfhe-1.5.1")
            )
            self.context_id = uuid.uuid4().hex
            self.key_bundle_id = uuid.uuid4().hex
            self._runtime: OpenFHECPU | None = OpenFHECPU(module)
        except BaseException:
            self._owns_lease = False
            self._lease_lock.release()
            raise

    def _active(self) -> OpenFHECPU:
        if self._runtime is None:
            raise RuntimeError("OpenFHE backend is closed")
        return self._runtime

    @classmethod
    def from_public_material(
        cls,
        config: CKKSConfig,
        directory: Path,
        *,
        context_id: str,
        key_bundle_id: str,
    ) -> "OpenFHEBackend":
        """Create a compute-only backend from an SDK workspace."""
        try:
            module = importlib.import_module("openfhe")
        except (ImportError, OSError) as error:
            raise BackendUnavailableError(
                "OpenFHE is not installed. Install the 'openfhe' SDK extra "
                "on supported Linux, or run this integration in GitLab CI."
            ) from error

        if config.fingerprint != CKKSConfig.profile(
            "ckks-balanced-v1"
        ).fingerprint:
            raise ValueError(
                "OpenFHE workspace requires the ckks-balanced-v1 profile"
            )
        if not cls._lease_lock.acquire(blocking=False):
            raise BackendUnavailableError(
                "Only one local OpenFHE HESession may be active per process. "
                "The pinned binding uses process-global evaluation-key state."
            )

        backend = cls.__new__(cls)
        backend._owns_lease = True
        try:
            backend.engine_version = str(
                getattr(module, "__version__", "openfhe-1.5.1")
            )
            backend.context_id = context_id
            backend.key_bundle_id = key_bundle_id
            backend._runtime = OpenFHECPU.from_public_material(
                module, directory
            )
        except BaseException:
            backend._owns_lease = False
            cls._lease_lock.release()
            raise
        return backend

    @property
    def has_secret_key(self) -> bool:
        return self._active().has_secret_key

    def encrypt(self, values: Sequence[float]) -> Any:
        return self._active().encrypt(values)

    def decrypt(self, encrypted: Any, length: int) -> list[float]:
        return self._active().decrypt(encrypted, length)

    def add(self, left: Any, right: Any) -> Any:
        return self._active().add(left, right)

    def subtract(self, left: Any, right: Any) -> Any:
        return self._active().subtract(left, right)

    def multiply(self, left: Any, right: Any) -> Any:
        return self._active().multiply(left, right)

    def square(self, encrypted: Any) -> Any:
        return self._active().square(encrypted)

    def sum(self, encrypted: Any, valid_count: int) -> Any:
        return self._active().sum(encrypted, valid_count)

    def mean(self, encrypted: Any, valid_count: int) -> Any:
        return self._active().mean(encrypted, valid_count)

    def variance(self, encrypted: Any, valid_count: int) -> Any:
        return self._active().variance(encrypted, valid_count)

    def create_result_recipient(self) -> tuple[str, Any, Any]:
        """Generate a second key pair in the owner's CKKS context."""
        public_key, secret_key = self._active().create_result_recipient()
        return uuid.uuid4().hex, public_key, secret_key

    def reencrypt_for_recipient(
        self, encrypted: Any, recipient_public_key: Any
    ) -> Any:
        return self._active().reencrypt_for_recipient(
            encrypted, recipient_public_key
        )

    def decrypt_for_recipient(
        self, encrypted: Any, recipient_secret_key: Any, length: int
    ) -> list[float]:
        return self._active().decrypt_with_key(
            encrypted, recipient_secret_key, length
        )

    def serialize_public_key(self, public_key: Any, path: Path) -> None:
        self._active().serialize_public_key(public_key, path)

    def deserialize_public_key(self, path: Path) -> Any:
        return self._active().deserialize_public_key(path)

    def export_public_material(self, directory: Path) -> None:
        self._active().export_public_material(directory)

    def serialize_ciphertext(self, encrypted: Any, path: Path) -> None:
        self._active().serialize_ciphertext(encrypted, path)

    def deserialize_ciphertext(self, path: Path) -> Any:
        return self._active().deserialize_ciphertext(path)

    def close(self) -> None:
        if not getattr(self, "_owns_lease", False):
            return
        self._runtime = None
        try:
            module = importlib.import_module("openfhe")
        except (ImportError, OSError):
            module = None
        try:
            if module is not None:
                for clear_name in (
                    "ClearEvalMultKeys",
                    "ClearEvalAutomorphismKeys",
                    "ReleaseAllContexts",
                ):
                    clear = getattr(module, clear_name, None)
                    if clear is not None:
                        clear()
        finally:
            self._owns_lease = False
            self._lease_lock.release()
