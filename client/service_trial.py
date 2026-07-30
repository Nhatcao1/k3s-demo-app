"""Test encryptor -> ciphertext add API -> decryptor using only HTTP."""

from __future__ import annotations

import argparse
import json
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


DEFAULT_LEFT = [1.0, 2.0, 3.0, 4.0]
DEFAULT_RIGHT = [10.0, 20.0, 30.0, 40.0]


def post_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.load(response)
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{url} returned HTTP {error.code}: {detail}") from error
    if not isinstance(result, dict):
        raise RuntimeError(f"{url} did not return a JSON object")
    return result


def run_trial(
    *,
    encryptor_url: str,
    add_url: str,
    left: list[float],
    right: list[float],
    tolerance: float,
    timeout: float,
) -> dict[str, Any]:
    encrypted = post_json(
        f"{encryptor_url.rstrip('/')}/encrypt-pair",
        {"left": left, "right": right},
        timeout,
    )
    session_id = encrypted.get("session_id")
    bundle = encrypted.get("evaluation_bundle")
    if not isinstance(session_id, str) or not isinstance(bundle, dict):
        raise RuntimeError("encryptor response is missing session_id or bundle")

    evaluated = post_json(add_url, bundle, timeout)
    ciphertext = evaluated.get("ciphertext")
    if not isinstance(ciphertext, str):
        raise RuntimeError("add API response is missing ciphertext")

    decrypted = post_json(
        f"{encryptor_url.rstrip('/')}/sessions/{session_id}/decrypt",
        {"ciphertext": ciphertext},
        timeout,
    )
    actual = decrypted.get("values")
    if not isinstance(actual, list):
        raise RuntimeError("decryptor response is missing values")

    expected = [
        left_value + right_value
        for left_value, right_value in zip(left, right, strict=True)
    ]
    if len(actual) != len(expected):
        raise RuntimeError("decrypted result has the wrong length")
    maximum_error = max(
        abs(float(got) - want) for got, want in zip(actual, expected, strict=True)
    )
    if maximum_error > tolerance:
        raise RuntimeError(
            f"maximum error {maximum_error} exceeds tolerance {tolerance}"
        )

    return {
        "status": "PASS",
        "left": left,
        "right": right,
        "expected": expected,
        "actual": actual,
        "maximum_absolute_error": maximum_error,
        "openfhe_required_on_caller": False,
        "secret_key_returned_to_caller": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--encryptor-url",
        default="http://127.0.0.1:18081/v1",
    )
    parser.add_argument(
        "--add-url",
        default="http://127.0.0.1:18080/v1/add",
    )
    parser.add_argument("--left", nargs="+", type=float, default=DEFAULT_LEFT)
    parser.add_argument("--right", nargs="+", type=float, default=DEFAULT_RIGHT)
    parser.add_argument("--tolerance", type=float, default=1e-4)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    result = run_trial(
        encryptor_url=args.encryptor_url,
        add_url=args.add_url,
        left=args.left,
        right=args.right,
        tolerance=args.tolerance,
        timeout=args.timeout,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
