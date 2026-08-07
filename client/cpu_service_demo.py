#!/usr/bin/env python3
"""Small trusted client demo for the deployed CPU HE evaluator service."""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import tempfile
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from openfhe_cpu.runtime import create_trial_context_and_keys


LEFT = [1.25, -2.0, 3.5, 4.0]
RIGHT = [0.75, 5.0, -1.5, 2.0]


def _serialize(openfhe: Any, path: Path, value: Any) -> bytes:
    if not openfhe.SerializeToFile(str(path), value, openfhe.BINARY):
        raise RuntimeError(f"could not serialize {path.name}")
    return path.read_bytes()


def _encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _post(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"service returned HTTP {error.code}: {detail}") from error
    except URLError as error:
        raise RuntimeError(f"could not reach CPU evaluator: {error}") from error


def _decrypt(
    openfhe: Any,
    context: Any,
    secret_key: Any,
    encoded_ciphertext: str,
    output_length: int,
    path: Path,
) -> list[float]:
    path.write_bytes(base64.b64decode(encoded_ciphertext, validate=True))
    ciphertext, ok = openfhe.DeserializeCiphertext(str(path), openfhe.BINARY)
    if not ok:
        raise RuntimeError("could not deserialize service result")
    plaintext = context.Decrypt(secret_key, ciphertext)
    plaintext.SetLength(output_length)
    return [
        float(value)
        for value in plaintext.GetRealPackedValue()[:output_length]
    ]


def run_demo(url: str, timeout: float, tolerance: float) -> dict[str, Any]:
    try:
        import openfhe
    except ImportError as error:
        raise RuntimeError("run this demo from the cpu-latest image") from error

    context, keys = create_trial_context_and_keys(openfhe)
    left_ciphertext = context.Encrypt(
        keys.publicKey, context.MakeCKKSPackedPlaintext(LEFT)
    )
    right_ciphertext = context.Encrypt(
        keys.publicKey, context.MakeCKKSPackedPlaintext(RIGHT)
    )

    expected = {
        "add": [left + right for left, right in zip(LEFT, RIGHT, strict=True)],
        "subtract": [left - right for left, right in zip(LEFT, RIGHT, strict=True)],
        "multiply": [left * right for left, right in zip(LEFT, RIGHT, strict=True)],
        "square": [value * value for value in LEFT],
        "sum": [sum(LEFT)],
        "mean": [sum(LEFT) / len(LEFT)],
        "variance": [
            sum(
                (value - sum(LEFT) / len(LEFT)) ** 2
                for value in LEFT
            ) / len(LEFT)
        ],
    }

    with tempfile.TemporaryDirectory(prefix="he-cpu-demo-") as directory:
        root = Path(directory)
        context_encoded = _encode(_serialize(openfhe, root / "context.bin", context))
        left_encoded = _encode(
            _serialize(openfhe, root / "left.bin", left_ciphertext)
        )
        right_encoded = _encode(
            _serialize(openfhe, root / "right.bin", right_ciphertext)
        )

        mult_key_path = root / "eval-mult.bin"
        if not context.SerializeEvalMultKey(str(mult_key_path), openfhe.BINARY):
            raise RuntimeError("could not serialize multiplication keys")
        sum_key_path = root / "eval-sum.bin"
        if not context.SerializeEvalAutomorphismKey(str(sum_key_path), openfhe.BINARY):
            raise RuntimeError("could not serialize sum keys")

        results: dict[str, Any] = {}
        for operation in (
            "add", "subtract", "multiply", "square", "sum", "mean",
            "variance",
        ):
            payload: dict[str, Any] = {
                "operation": operation,
                "context": context_encoded,
                "ciphertext_a": left_encoded,
                "request_id": f"cpu-demo-{operation}",
            }
            if operation in ("add", "subtract", "multiply"):
                payload["ciphertext_b"] = right_encoded
            if operation in ("multiply", "square"):
                payload["evaluation_keys"] = _encode(mult_key_path.read_bytes())
            if operation in ("sum", "mean"):
                payload["evaluation_keys"] = _encode(sum_key_path.read_bytes())
                payload["valid_count"] = len(LEFT)
            if operation == "variance":
                payload["multiplication_keys"] = _encode(
                    mult_key_path.read_bytes()
                )
                payload["rotation_keys"] = _encode(sum_key_path.read_bytes())
                payload["valid_count"] = len(LEFT)

            response = _post(url, payload, timeout)
            encoded_result = response.get("ciphertext")
            if not isinstance(encoded_result, str):
                raise RuntimeError(f"{operation}: response has no ciphertext")
            actual = _decrypt(
                openfhe,
                context,
                keys.secretKey,
                encoded_result,
                1 if operation in ("sum", "mean", "variance") else len(LEFT),
                root / f"{operation}-result.bin",
            )
            maximum_error = max(
                abs(got - want)
                for got, want in zip(actual, expected[operation], strict=True)
            )
            if maximum_error > tolerance:
                raise RuntimeError(
                    f"{operation}: maximum error {maximum_error} exceeds {tolerance}"
                )
            results[operation] = {
                "status": "PASS",
                "expected": expected[operation],
                "decrypted": actual,
                "maximum_absolute_error": maximum_error,
            }

    return {
        "status": "PASS",
        "service_url": url,
        "backend": "cpu-openfhe",
        "secret_key_sent_to_service": False,
        "operations": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url", default="http://he-evaluator:8080/v1/evaluate"
    )
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--tolerance", type=float, default=1e-3)
    args = parser.parse_args()
    print(json.dumps(run_demo(args.url, args.timeout, args.tolerance), indent=2))


if __name__ == "__main__":
    main()
