"""Python adapter between the core HE SDK and the native FIDESlib session."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Sequence
import uuid

from he_sdk.capabilities import CapabilitySet
from he_sdk.config import CKKSConfig
from he_sdk.errors import (
    BackendUnavailableError,
    SecretKeyUnavailableError,
    UnsupportedOperationError,
)
from he_sdk.operations import OPERATION_CONTRACTS


class FidesBackend:
    """Trusted local GPU backend backed by the optional native extension."""

    name = "fides"
    artifact_backend = name

    @staticmethod
    def _capabilities(*, serialization: bool) -> CapabilitySet:
        return CapabilitySet(
            backend="fides",
            schemes=("CKKS",),
            operations=tuple(OPERATION_CONTRACTS),
            supports_bootstrap=False,
            supports_serialization=serialization,
            supports_proxy_re_encryption=False,
        )

    def __init__(self, config: CKKSConfig) -> None:
        self._validate_config(config)
        self.capabilities = self._capabilities(serialization=False)
        self.artifact_backend = self.name
        self.has_secret_key = True
        self._mode = "local"
        self._material_directory: Path | None = None
        self._worker: Path | None = None
        self._device = 0
        self._timeout = 600.0
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

    @classmethod
    def from_public_material(
        cls,
        config: CKKSConfig,
        directory: Path,
        *,
        context_id: str,
        key_bundle_id: str,
    ) -> "FidesBackend":
        """Open an OpenFHE workspace through the FIDES native worker.

        FIDESlib uses its matching patched OpenFHE serializer, so the GPU
        adapter deliberately retains ``openfhe`` as the artifact identity.
        The adapter is compute-only: secret keys never enter the worker Pod.
        """
        cls._validate_config(config)
        material = Path(directory).resolve()
        required = (
            "context.bin",
            "public-key.bin",
            "multiplication-keys.bin",
            "rotation-keys.bin",
        )
        missing = [name for name in required if not (material / name).is_file()]
        if missing:
            raise BackendUnavailableError(
                "FIDES workspace public material is missing: "
                + ", ".join(missing)
            )

        worker = Path(
            os.getenv("HE_GPU_WORKER", "/src/worker/build/he-gpu-worker")
        ).resolve()
        if not worker.is_file() or not os.access(worker, os.X_OK):
            raise BackendUnavailableError(
                f"FIDES native workspace worker is not executable: {worker}"
            )

        instance = cls.__new__(cls)
        instance.capabilities = cls._capabilities(serialization=True)
        instance.artifact_backend = "openfhe"
        instance.has_secret_key = False
        instance.engine_version = "fideslib-workspace-worker"
        instance.context_id = context_id
        instance.key_bundle_id = key_bundle_id
        instance._mode = "workspace"
        instance._material_directory = material
        instance._worker = worker
        instance._device = int(os.getenv("HE_GPU_DEVICE", "0"))
        instance._timeout = float(
            os.getenv("HE_GPU_WORKER_TIMEOUT_SECONDS", "600")
        )
        instance._native = None
        return instance

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

    def _require_local(self, operation: str) -> Any:
        if self._mode != "local":
            raise UnsupportedOperationError(
                f"{operation} is unavailable in a compute-only FIDES workspace"
            )
        return self._active()

    @staticmethod
    def _rotation_indices(valid_count: int) -> list[int]:
        indices: list[int] = []
        step = 1
        while step < valid_count:
            for multiplier in range(1, 4):
                index = multiplier * step
                if index < valid_count:
                    indices.append(index)
            step *= 4
        return indices

    def _write_context_metadata(
        self, context_path: Path, operation: str, valid_count: int | None
    ) -> None:
        rotations = (
            self._rotation_indices(valid_count or 0)
            if operation in ("sum", "mean", "variance")
            else []
        )
        rotation_text = " ".join(str(index) for index in rotations)
        Path(f"{context_path}.dev").write_text(
            f"1 {{ {self._device} }}\n"
            "AutoLoadCiphertexts: 1\n"
            "AutoLoadPlaintexts: 0\n"
            f"RotationIndexes: {{ {rotation_text} }}\n"
            "KeyDist: 1\n"
            "BootstrapSlots: { }\n",
            encoding="utf-8",
        )

    @staticmethod
    def _ciphertext_bytes(value: Any) -> bytes:
        if not isinstance(value, bytes) or not value:
            raise TypeError("FIDES workspace operation requires ciphertext bytes")
        return value

    def _evaluate_workspace(
        self,
        operation: str,
        left: Any,
        right: Any | None = None,
        *,
        valid_count: int | None = None,
    ) -> bytes:
        if self._mode != "workspace":
            raise RuntimeError("FIDES workspace evaluator is not active")
        if self._worker is None or self._material_directory is None:
            raise RuntimeError("FIDES workspace evaluator is closed")

        with tempfile.TemporaryDirectory(prefix="he-sdk-fides-") as temporary:
            root = Path(temporary)
            context = root / "context.bin"
            public_key = root / "public-key.bin"
            left_path = root / "left.bin"
            right_path = root / "right.bin"
            output = root / "result.bin"
            multiplication_keys = root / "multiplication-keys.bin"
            rotation_keys = root / "rotation-keys.bin"

            shutil.copyfile(self._material_directory / "context.bin", context)
            shutil.copyfile(
                self._material_directory / "public-key.bin", public_key
            )
            left_path.write_bytes(self._ciphertext_bytes(left))
            self._write_context_metadata(context, operation, valid_count)

            command = [
                str(self._worker),
                "--operation",
                operation,
                "--context",
                str(context),
                "--public-key",
                str(public_key),
                "--left",
                str(left_path),
                "--output",
                str(output),
            ]
            if right is not None:
                right_path.write_bytes(self._ciphertext_bytes(right))
                command.extend(("--right", str(right_path)))
            if operation in ("multiply", "square", "variance"):
                shutil.copyfile(
                    self._material_directory / "multiplication-keys.bin",
                    multiplication_keys,
                )
                command.extend(
                    ("--multiplication-keys", str(multiplication_keys))
                )
            if operation in ("sum", "mean", "variance"):
                shutil.copyfile(
                    self._material_directory / "rotation-keys.bin",
                    rotation_keys,
                )
                command.extend(("--rotation-keys", str(rotation_keys)))
            if valid_count is not None:
                command.extend(("--valid-count", str(valid_count)))

            try:
                completed = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=self._timeout,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                raise BackendUnavailableError(
                    "FIDES native workspace worker could not complete"
                ) from error
            if completed.returncode != 0:
                detail = (completed.stderr or "<no stderr>").strip()[:8192]
                raise RuntimeError(
                    f"FIDES native worker rejected {operation!r}: {detail}"
                )
            if not output.is_file() or output.stat().st_size == 0:
                raise RuntimeError("FIDES native worker produced no ciphertext")
            return output.read_bytes()

    def encrypt(self, values: Sequence[float]) -> Any:
        return self._require_local("encrypt").encrypt(list(values))

    def decrypt(self, encrypted: Any, length: int) -> list[float]:
        if not self.has_secret_key:
            raise SecretKeyUnavailableError(
                "compute-only FIDES workspace has no secret key"
            )
        return [
            float(value)
            for value in self._require_local("decrypt").decrypt(
                encrypted, length
            )
        ]

    def add(self, left: Any, right: Any) -> Any:
        if self._mode == "workspace":
            return self._evaluate_workspace("add", left, right)
        return self._active().add(left, right)

    def subtract(self, left: Any, right: Any) -> Any:
        if self._mode == "workspace":
            return self._evaluate_workspace("subtract", left, right)
        return self._active().subtract(left, right)

    def multiply(self, left: Any, right: Any) -> Any:
        if self._mode == "workspace":
            return self._evaluate_workspace("multiply", left, right)
        return self._active().multiply(left, right)

    def square(self, encrypted: Any) -> Any:
        if self._mode == "workspace":
            return self._evaluate_workspace("square", encrypted)
        return self._active().square(encrypted)

    def sum(self, encrypted: Any, valid_count: int) -> Any:
        if self._mode == "workspace":
            return self._evaluate_workspace(
                "sum", encrypted, valid_count=valid_count
            )
        return self._active().sum(encrypted, valid_count)

    def mean(self, encrypted: Any, valid_count: int) -> Any:
        if self._mode == "workspace":
            return self._evaluate_workspace(
                "mean", encrypted, valid_count=valid_count
            )
        return self._active().mean(encrypted, valid_count)

    def variance(self, encrypted: Any, valid_count: int) -> Any:
        if self._mode == "workspace":
            return self._evaluate_workspace(
                "variance", encrypted, valid_count=valid_count
            )
        return self._active().variance(encrypted, valid_count)

    def serialize_ciphertext(self, encrypted: Any, path: Path) -> None:
        if self._mode != "workspace":
            raise UnsupportedOperationError(
                "local FIDES sessions do not yet serialize ciphertexts"
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self._ciphertext_bytes(encrypted))

    def deserialize_ciphertext(self, path: Path) -> bytes:
        if self._mode != "workspace":
            raise UnsupportedOperationError(
                "local FIDES sessions do not yet deserialize ciphertexts"
            )
        value = path.read_bytes()
        if not value:
            raise ValueError(f"ciphertext artifact is empty: {path}")
        return value

    def export_public_material(self, directory: Path) -> None:
        raise UnsupportedOperationError(
            "compute-only FIDES sessions cannot create a new workspace"
        )

    def create_result_recipient(self) -> tuple[str, Any, Any]:
        raise UnsupportedOperationError(
            "FIDES result-recipient keys are not implemented"
        )

    def reencrypt_for_recipient(
        self, encrypted: Any, recipient_public_key: Any
    ) -> Any:
        raise UnsupportedOperationError("FIDES result release is not implemented")

    def decrypt_for_recipient(
        self, encrypted: Any, recipient_secret_key: Any, length: int
    ) -> list[float]:
        raise UnsupportedOperationError("FIDES result release is not implemented")

    def serialize_public_key(self, public_key: Any, path: Path) -> None:
        raise UnsupportedOperationError("FIDES result release is not implemented")

    def deserialize_public_key(self, path: Path) -> Any:
        raise UnsupportedOperationError("FIDES result release is not implemented")

    def close(self) -> None:
        if self._native is not None:
            self._native.close()
        self._native = None
        self._worker = None
        self._material_directory = None
