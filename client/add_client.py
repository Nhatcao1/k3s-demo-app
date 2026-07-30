"""Encrypt two CKKS vectors, call the add API, decrypt, and verify."""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import tempfile
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


DEFAULT_LEFT = [1.0, 2.0, 3.0, 4.0]
DEFAULT_RIGHT = [10.0, 20.0, 30.0, 40.0]


def _serialize(openfhe: Any, path: Path, value: Any) -> bytes:
    if not openfhe.SerializeToFile(str(path), value, openfhe.BINARY):
        raise RuntimeError(f"could not serialize {path.name}")
    return path.read_bytes()


def run_trial(
    *,
    url: str,
    left_values: list[float],
    right_values: list[float],
    tolerance: float,
    timeout: float,
) -> dict[str, Any]:
    if len(left_values) != len(right_values) or not left_values:
        raise ValueError("left and right must have the same non-zero length")

    try:
        import openfhe
    except ImportError as error:
        raise RuntimeError(
            "OpenFHE-Python is required; run this client from the trial image"
        ) from error

    batch_size = max(8, 1 << (len(left_values) - 1).bit_length())
    parameters = openfhe.CCParamsCKKSRNS()
    parameters.SetMultiplicativeDepth(1)
    parameters.SetScalingModSize(50)
    parameters.SetBatchSize(batch_size)

    context = openfhe.GenCryptoContext(parameters)
    context.Enable(openfhe.PKE)
    context.Enable(openfhe.KEYSWITCH)
    context.Enable(openfhe.LEVELEDSHE)
    key_pair = context.KeyGen()

    left_plaintext = context.MakeCKKSPackedPlaintext(left_values)
    right_plaintext = context.MakeCKKSPackedPlaintext(right_values)
    left_ciphertext = context.Encrypt(key_pair.publicKey, left_plaintext)
    right_ciphertext = context.Encrypt(key_pair.publicKey, right_plaintext)

    with tempfile.TemporaryDirectory(prefix="he-add-client-") as directory:
        root = Path(directory)
        request_payload = {
            "context": base64.b64encode(
                _serialize(openfhe, root / "context.bin", context)
            ).decode("ascii"),
            "ciphertext_a": base64.b64encode(
                _serialize(openfhe, root / "left.bin", left_ciphertext)
            ).decode("ascii"),
            "ciphertext_b": base64.b64encode(
                _serialize(openfhe, root / "right.bin", right_ciphertext)
            ).decode("ascii"),
        }

        request = Request(
            url,
            data=json.dumps(request_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                response_payload = json.load(response)
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"API returned HTTP {error.code}: {detail}") from error

        encoded_result = response_payload.get("ciphertext")
        if not isinstance(encoded_result, str):
            raise RuntimeError("API response does not contain a ciphertext")
        result_path = root / "result.bin"
        result_path.write_bytes(base64.b64decode(encoded_result, validate=True))
        result_ciphertext, ok = openfhe.DeserializeCiphertext(
            str(result_path), openfhe.BINARY
        )
        if not ok:
            raise RuntimeError("could not deserialize result ciphertext")

    decrypted = context.Decrypt(key_pair.secretKey, result_ciphertext)
    decrypted.SetLength(len(left_values))
    actual = [float(value) for value in decrypted.GetRealPackedValue()]
    expected = [
        left + right for left, right in zip(left_values, right_values, strict=True)
    ]
    maximum_error = max(abs(got - want) for got, want in zip(actual, expected))
    if maximum_error > tolerance:
        raise RuntimeError(
            f"maximum error {maximum_error} exceeds tolerance {tolerance}"
        )

    return {
        "status": "PASS",
        "left": left_values,
        "right": right_values,
        "expected": expected,
        "actual": actual,
        "maximum_absolute_error": maximum_error,
        "secret_key_sent_to_api": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8080/v1/add")
    parser.add_argument("--left", nargs="+", type=float, default=DEFAULT_LEFT)
    parser.add_argument("--right", nargs="+", type=float, default=DEFAULT_RIGHT)
    parser.add_argument("--tolerance", type=float, default=1e-4)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    result = run_trial(
        url=args.url,
        left_values=args.left,
        right_values=args.right,
        tolerance=args.tolerance,
        timeout=args.timeout,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
