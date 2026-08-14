"""Python adapter between the core HE SDK and the native FIDESlib session."""

from __future__ import annotations

import importlib
from typing import Any, Sequence
import uuid

from he_sdk.capabilities import CapabilitySet
from he_sdk.config import CKKSConfig
from he_sdk.errors import BackendUnavailableError
from he_sdk.operations import OPERATION_CONTRACTS


class FidesBackend:
    """Trusted local GPU backend backed by the optional native extension."""

    name = "fides"
    capabilities = CapabilitySet(
        backend=name,
        schemes=("CKKS",),
        operations=tuple(OPERATION_CONTRACTS),
        supports_bootstrap=False,
        supports_serialization=False,
    )

    def __init__(self, config: CKKSConfig) -> None:
        self._validate_config(config)
        try:
            native = importlib.import_module("he_sdk_fides._native")
        except (ImportError, OSError) as error:
            raise BackendUnavailableError(
                "The he-sdk-fides native extension is unavailable. Install "
                "the GPU wheel built for this CUDA/Linux environment."
            ) from error

        self.engine_version = str(
            getattr(native, "__engine_version__", "fideslib-patched-openfhe")
        )
        self.context_id = uuid.uuid4().hex
        self.key_bundle_id = uuid.uuid4().hex
        try:
            self._native: Any | None = native.NativeSession(
                device=0,
                multiplicative_depth=config.multiplicative_depth,
                first_modulus_size=config.first_modulus_size,
                scaling_modulus_size=config.scaling_modulus_size,
                ring_dimension=config.ring_dimension,
                batch_size=config.batch_size,
            )
        except Exception as error:
            raise BackendUnavailableError(
                "FIDES could not initialize CUDA device 0 with the tested "
                "SDK profile."
            ) from error

    @staticmethod
    def _validate_config(config: CKKSConfig) -> None:
        supported = {
            "scheme": "CKKS",
            "security_level": "HEStd_128_classic",
            "multiplicative_depth": 3,
            "first_modulus_size": 60,
            "scaling_modulus_size": 50,
            "ring_dimension": 16384,
            "batch_size": 8192,
            "scaling_technique": "FLEXIBLEAUTO",
            "key_switch_technique": "library-default",
            "secret_key_distribution": "library-default",
            "input_scale": 1.0,
            "compression_mode": "none",
            "serialization_version": "openfhe-binary-v1",
        }
        mismatches = [
            f"{name}={getattr(config, name)!r} (supported {expected!r})"
            for name, expected in supported.items()
            if getattr(config, name) != expected
        ]
        if config.bootstrap_enabled:
            mismatches.append("bootstrap_enabled=True (supported False)")
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
                "FIDES backend does not support this profile: "
                + "; ".join(mismatches)
            )

    def _active(self) -> Any:
        if self._native is None:
            raise RuntimeError("FIDES backend is closed")
        return self._native

    def encrypt(self, values: Sequence[float]) -> Any:
        return self._active().encrypt(list(values))

    def decrypt(self, encrypted: Any, length: int) -> list[float]:
        return [float(value) for value in self._active().decrypt(encrypted, length)]

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

    def close(self) -> None:
        if self._native is None:
            return
        self._native.close()
        self._native = None
