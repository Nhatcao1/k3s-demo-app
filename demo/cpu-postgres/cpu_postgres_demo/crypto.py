"""OpenFHE serialization, evaluation, and trusted decryption."""

from __future__ import annotations

from pathlib import Path
import tempfile
from typing import Any, Sequence

from backends.openfhe_python import OpenFHEPythonBackend
from openfhe_cpu.runtime import create_context_and_keys

from .artifacts import (
    CONTEXT,
    KPI_CIPHERTEXT,
    MULTIPLICATION_EVALUATION_KEYS,
    SALARY_CIPHERTEXT,
    SUM_EVALUATION_KEYS,
    WRAPPED_SECRET_KEY,
    unwrap_secret_key,
    wrap_secret_key,
)


class CryptoError(RuntimeError):
    """OpenFHE could not create, evaluate, or decrypt an artifact."""


def _serialize(openfhe: Any, path: Path, value: Any) -> bytes:
    if not openfhe.SerializeToFile(str(path), value, openfhe.BINARY):
        raise CryptoError(f"could not serialize {path.name}")
    return path.read_bytes()


def create_initial_artifacts(
    salaries: Sequence[int],
    kpi: float | int,
    wrapping_key: bytes,
    session_id: str,
    scheme: str,
    bgv_plaintext_modulus: int,
) -> dict[str, bytes]:
    try:
        import openfhe
    except (ImportError, OSError) as error:
        raise CryptoError("OpenFHE-Python is not available") from error

    context, keys = create_context_and_keys(
        openfhe, scheme, bgv_plaintext_modulus
    )
    if scheme == "ckks":
        salary_plaintext = context.MakeCKKSPackedPlaintext(
            [float(value) for value in salaries]
        )
        kpi_plaintext = context.MakeCKKSPackedPlaintext(
            [float(kpi)] * len(salaries)
        )
    else:
        salary_plaintext = context.MakePackedPlaintext(list(salaries))
        kpi_plaintext = context.MakePackedPlaintext([int(kpi)] * len(salaries))
    salary_ciphertext = context.Encrypt(keys.publicKey, salary_plaintext)
    kpi_ciphertext = context.Encrypt(keys.publicKey, kpi_plaintext)

    with tempfile.TemporaryDirectory(prefix="he-session-init-") as directory:
        root = Path(directory)
        context_bytes = _serialize(openfhe, root / "context.bin", context)
        salary_bytes = _serialize(
            openfhe, root / "salary-ciphertext.bin", salary_ciphertext
        )
        kpi_bytes = _serialize(openfhe, root / "kpi-ciphertext.bin", kpi_ciphertext)
        secret_key_bytes = _serialize(openfhe, root / "secret-key.bin", keys.secretKey)

        mult_path = root / "eval-mult.bin"
        if not context.SerializeEvalMultKey(str(mult_path), openfhe.BINARY):
            raise CryptoError("could not serialize multiplication evaluation keys")
        sum_path = root / "eval-sum.bin"
        if not context.SerializeEvalAutomorphismKey(str(sum_path), openfhe.BINARY):
            raise CryptoError("could not serialize sum evaluation keys")

        return {
            CONTEXT: context_bytes,
            SALARY_CIPHERTEXT: salary_bytes,
            KPI_CIPHERTEXT: kpi_bytes,
            SUM_EVALUATION_KEYS: sum_path.read_bytes(),
            MULTIPLICATION_EVALUATION_KEYS: mult_path.read_bytes(),
            WRAPPED_SECRET_KEY: wrap_secret_key(
                secret_key_bytes, wrapping_key, session_id
            ),
        }


def evaluate_sum(artifacts: dict[str, bytes], valid_count: int) -> bytes:
    return OpenFHEPythonBackend().evaluate(
        "sum",
        artifacts[CONTEXT],
        artifacts[SALARY_CIPHERTEXT],
        None,
        None,
        artifacts[SUM_EVALUATION_KEYS],
        valid_count,
    )


def evaluate_multiply(artifacts: dict[str, bytes]) -> bytes:
    from .artifacts import SUM_CIPHERTEXT

    return OpenFHEPythonBackend().evaluate(
        "multiply",
        artifacts[CONTEXT],
        artifacts[SUM_CIPHERTEXT],
        artifacts[KPI_CIPHERTEXT],
        None,
        artifacts[MULTIPLICATION_EVALUATION_KEYS],
        None,
    )


def decrypt_final_result(
    artifacts: dict[str, bytes], wrapping_key: bytes, session_id: str, scheme: str
) -> float | int:
    try:
        import openfhe
    except (ImportError, OSError) as error:
        raise CryptoError("OpenFHE-Python is not available") from error

    from .artifacts import KPI_RESULT_CIPHERTEXT

    with tempfile.TemporaryDirectory(prefix="he-session-verify-") as directory:
        root = Path(directory)
        context_path = root / "context.bin"
        secret_path = root / "secret-key.bin"
        result_path = root / "result.bin"
        context_path.write_bytes(artifacts[CONTEXT])
        secret_path.write_bytes(
            unwrap_secret_key(
                artifacts[WRAPPED_SECRET_KEY], wrapping_key, session_id
            )
        )
        result_path.write_bytes(artifacts[KPI_RESULT_CIPHERTEXT])

        openfhe.ReleaseAllContexts()
        context, context_ok = openfhe.DeserializeCryptoContext(
            str(context_path), openfhe.BINARY
        )
        secret_key, secret_ok = openfhe.DeserializePrivateKey(
            str(secret_path), openfhe.BINARY
        )
        ciphertext, ciphertext_ok = openfhe.DeserializeCiphertext(
            str(result_path), openfhe.BINARY
        )
        if not context_ok or not secret_ok or not ciphertext_ok:
            raise CryptoError("could not deserialize trusted verification artifacts")

        plaintext = context.Decrypt(secret_key, ciphertext)
        plaintext.SetLength(1)
        if scheme == "ckks":
            return float(plaintext.GetRealPackedValue()[0])
        return int(plaintext.GetPackedValue()[0])
