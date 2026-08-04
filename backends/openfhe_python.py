"""Simple OpenFHE-Python backend for add, subtract, multiply, and sum."""

from __future__ import annotations

from pathlib import Path
import tempfile
import threading
from typing import Any


class OpenFHEBackendError(ValueError):
    """An invalid serialized OpenFHE artifact was supplied."""


class OpenFHEPythonBackend:
    """Deserialize one request and call OpenFHE primitives directly."""

    backend_name = "cpu-openfhe"
    serialization = "openfhe_binary_base64"
    _lock = threading.Lock()

    @property
    def ready(self) -> bool:
        try:
            import openfhe  # noqa: F401
        except (ImportError, OSError):
            return False
        return True

    @staticmethod
    def add(context: Any, left: Any, right: Any) -> Any:
        """Ciphertext + ciphertext via OpenFHE EvalAdd."""
        return context.EvalAdd(left, right)

    @staticmethod
    def subtract(context: Any, left: Any, right: Any) -> Any:
        """Ciphertext - ciphertext via OpenFHE EvalSub."""
        return context.EvalSub(left, right)

    @staticmethod
    def multiply(context: Any, left: Any, right: Any) -> Any:
        """Ciphertext * ciphertext via OpenFHE EvalMult."""
        return context.EvalMult(left, right)

    @staticmethod
    def sum(context: Any, encrypted: Any, valid_count: int) -> Any:
        """Reduce one packed ciphertext via OpenFHE EvalSum."""
        return context.EvalSum(encrypted, valid_count)

    @staticmethod
    def _deserialize_ciphertext(openfhe: Any, path: Path, field: str) -> Any:
        ciphertext, ok = openfhe.DeserializeCiphertext(str(path), openfhe.BINARY)
        if not ok:
            raise OpenFHEBackendError(f"could not deserialize {field}")
        return ciphertext

    def evaluate(
        self,
        operation: str,
        context: bytes,
        ciphertext_a: bytes,
        ciphertext_b: bytes | None,
        evaluation_keys: bytes | None,
        valid_count: int | None,
    ) -> bytes:
        """Evaluate serialized artifacts and return one serialized ciphertext."""
        if not self.ready:
            raise RuntimeError("OpenFHE-Python is not installed")

        import openfhe

        # OpenFHE uses process-global context and key registries. Only one
        # request may load artifacts at a time.
        with self._lock, tempfile.TemporaryDirectory(prefix="he-evaluate-") as directory:
            root = Path(directory)
            context_path = root / "context.bin"
            left_path = root / "ciphertext-a.bin"
            result_path = root / "result.bin"
            context_path.write_bytes(context)
            left_path.write_bytes(ciphertext_a)

            openfhe.ReleaseAllContexts()
            for clear_name in ("ClearEvalMultKeys", "ClearEvalAutomorphismKeys"):
                clear = getattr(openfhe, clear_name, None)
                if clear is not None:
                    clear()

            crypto_context, ok = openfhe.DeserializeCryptoContext(
                str(context_path), openfhe.BINARY
            )
            if not ok:
                raise OpenFHEBackendError("could not deserialize context")

            if evaluation_keys is not None:
                key_path = root / "evaluation-keys.bin"
                key_path.write_bytes(evaluation_keys)
                if operation == "multiply":
                    ok = crypto_context.DeserializeEvalMultKey(
                        str(key_path), openfhe.BINARY
                    )
                else:
                    ok = crypto_context.DeserializeEvalAutomorphismKey(
                        str(key_path), openfhe.BINARY
                    )
                if not ok:
                    raise OpenFHEBackendError(
                        "could not deserialize evaluation_keys"
                    )

            left = self._deserialize_ciphertext(openfhe, left_path, "ciphertext_a")

            if operation == "sum":
                assert valid_count is not None
                result = self.sum(crypto_context, left, valid_count)
            else:
                assert ciphertext_b is not None
                right_path = root / "ciphertext-b.bin"
                right_path.write_bytes(ciphertext_b)
                right = self._deserialize_ciphertext(
                    openfhe, right_path, "ciphertext_b"
                )
                functions = {
                    "add": self.add,
                    "subtract": self.subtract,
                    "multiply": self.multiply,
                }
                result = functions[operation](crypto_context, left, right)

            if not openfhe.SerializeToFile(str(result_path), result, openfhe.BINARY):
                raise RuntimeError("could not serialize result ciphertext")
            return result_path.read_bytes()
