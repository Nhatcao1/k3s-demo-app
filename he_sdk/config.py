"""Versioned, reviewable configuration for local HE sessions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math


@dataclass(frozen=True)
class CKKSConfig:
    """Complete CKKS contract supported by the first SDK release.

    Some OpenFHE choices are deliberately recorded as ``library-default``.
    They remain explicit compatibility fields even though the current trial
    runtime does not override the OpenFHE default.
    """

    profile_name: str = "ckks-balanced-v1"
    scheme: str = "CKKS"
    security_level: str = "HEStd_128_classic"
    multiplicative_depth: int = 3
    ring_dimension: int = 16384
    batch_size: int = 8192
    scaling_modulus_size: int = 50
    first_modulus_size: int = 60
    scaling_technique: str = "FLEXIBLEAUTO"
    key_switch_technique: str = "library-default"
    secret_key_distribution: str = "library-default"
    input_scale: float = 1.0
    minimum_input: float = -40000.0
    maximum_input: float = 40000.0
    bootstrap_enabled: bool = False
    rotation_indices: tuple[int, ...] = ()
    generate_multiplication_keys: bool = True
    generate_sum_keys: bool = True
    compression_mode: str = "none"
    serialization_version: str = "openfhe-binary-v1"
    expected_cpu: str = "1-4 cores"
    expected_ram: str = "2-8 GiB"
    expected_gpu: str = "none"
    expected_vram: str = "none"

    def __post_init__(self) -> None:
        if self.scheme != "CKKS":
            raise ValueError("CKKSConfig scheme must be CKKS")
        if self.multiplicative_depth < 1:
            raise ValueError("multiplicative_depth must be positive")
        if self.ring_dimension < 2 or self.ring_dimension & (
            self.ring_dimension - 1
        ):
            raise ValueError("ring_dimension must be a power of two")
        if not 1 <= self.batch_size <= self.ring_dimension // 2:
            raise ValueError("batch_size must be in [1, ring_dimension / 2]")
        if self.scaling_modulus_size < 1 or self.first_modulus_size < 1:
            raise ValueError("modulus sizes must be positive")
        if not math.isfinite(self.input_scale) or self.input_scale <= 0:
            raise ValueError("input_scale must be finite and positive")
        if not (
            math.isfinite(self.minimum_input)
            and math.isfinite(self.maximum_input)
            and self.minimum_input < self.maximum_input
        ):
            raise ValueError("input range must contain two ordered finite values")
        if any(
            not isinstance(index, int) or index == 0
            for index in self.rotation_indices
        ):
            raise ValueError("rotation_indices must contain non-zero integers")

    @classmethod
    def profile(cls, name: str) -> "CKKSConfig":
        """Load a named, immutable compatibility profile."""
        if name != "ckks-balanced-v1":
            raise ValueError(f"unknown CKKS profile: {name}")
        return cls()

    @property
    def fingerprint(self) -> str:
        """Return a stable identity for every compatibility-relevant field."""
        encoded = json.dumps(
            asdict(self), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def validate_values(self, values: object) -> list[float]:
        if isinstance(values, (str, bytes)):
            raise ValueError("values must be a non-empty numeric sequence")
        try:
            materialized = [
                float(value) for value in values  # type: ignore[union-attr]
            ]
        except (TypeError, ValueError) as error:
            raise ValueError("values must be a non-empty numeric sequence") from error
        if not 1 <= len(materialized) <= self.batch_size:
            raise ValueError(
                f"value count must be in [1, {self.batch_size}]"
            )
        if not all(math.isfinite(value) for value in materialized):
            raise ValueError("values must not contain NaN or infinity")
        if not all(
            self.minimum_input <= value <= self.maximum_input
            for value in materialized
        ):
            raise ValueError(
                f"values must be in [{self.minimum_input}, {self.maximum_input}]"
            )
        return materialized
