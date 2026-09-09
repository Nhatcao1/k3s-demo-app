#!/usr/bin/env python3
"""Small end-to-end scenario for the current HE SDK.

Run one backend per environment:

    python examples/sdk/full_session_showcase.py --backend openfhe
    python examples/sdk/full_session_showcase.py --backend fides

OpenFHE demonstrates the complete persisted workspace and recipient flow.
FIDES demonstrates local GPU encrypt, evaluate and decrypt; its local artifact
and recipient APIs are not implemented yet, so those steps are skipped.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Callable

from he_sdk import EncryptedScalar, EncryptedVector, HESession


LEFT = [1.25, -2.0, 3.5, 4.0]
RIGHT = [0.75, 5.0, -1.5, 2.0]
EncryptedValue = EncryptedVector | EncryptedScalar


def show(
    session: HESession,
    name: str,
    operation: Callable[[], EncryptedValue],
    expected: list[float] | float,
) -> EncryptedValue:
    started = time.perf_counter()
    encrypted = operation()
    evaluate_ms = (time.perf_counter() - started) * 1000

    started = time.perf_counter()
    actual = session.decrypt(encrypted)
    decrypt_ms = (time.perf_counter() - started) * 1000

    print(f"{name:9} expected={expected}")
    print(f"{'':9} decrypted={actual}")
    print(f"{'':9} evaluate_ms={evaluate_ms:.3f}, decrypt_ms={decrypt_ms:.3f}")
    return encrypted


def run_math(session: HESession) -> dict[str, EncryptedValue]:
    print("\n1. Encrypt and calculate")
    print("backend:", session.capabilities.backend)
    print("left   :", LEFT)
    print("right  :", RIGHT)

    started = time.perf_counter()
    left = session.encrypt(LEFT)
    right = session.encrypt(RIGHT)
    print("left_ct:", left)
    print("encrypt two vectors ms:", (time.perf_counter() - started) * 1000)

    mean = sum(LEFT) / len(LEFT)
    results = {
        "add": show(
            session,
            "add",
            lambda: session.add(left, right),
            [a + b for a, b in zip(LEFT, RIGHT, strict=True)],
        ),
        "subtract": show(
            session,
            "subtract",
            lambda: session.subtract(left, right),
            [a - b for a, b in zip(LEFT, RIGHT, strict=True)],
        ),
        "multiply": show(
            session,
            "multiply",
            lambda: session.multiply(left, right),
            [a * b for a, b in zip(LEFT, RIGHT, strict=True)],
        ),
        "square": show(
            session,
            "square",
            lambda: session.square(left),
            [value * value for value in LEFT],
        ),
        "sum": show(session, "sum", lambda: session.sum(left), sum(LEFT)),
        "mean": show(session, "mean", lambda: session.mean(left), mean),
        "variance": show(
            session,
            "variance",
            lambda: session.variance(left),
            sum((value - mean) ** 2 for value in LEFT) / len(LEFT),
        ),
    }
    results["input"] = left
    return results


# OpenFHE workspace loading runs in another process because it represents a
# separate secretless compute boundary, not a second trusted owner session.
COMPUTE_CODE = r"""
import json
from pathlib import Path
import sys
from he_sdk import HESession, SecretKeyUnavailableError

workspace = Path(sys.argv[1])
with HESession.open_workspace(workspace) as compute:
    encrypted = compute.load(workspace, name="input")
    compute.save(compute.sum(encrypted), workspace, name="computed_sum")
    try:
        compute.decrypt(encrypted)
    except SecretKeyUnavailableError:
        print(json.dumps({"compute": "PASS", "has_secret_key": False}))
    else:
        raise RuntimeError("compute session unexpectedly decrypted input")
"""


def run_openfhe_artifacts(
    owner: HESession,
    results: dict[str, EncryptedValue],
) -> None:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    workspace = Path(f"he-sdk-showcase-{timestamp}")

    print("\n2. Save and load encrypted object")
    owner.save(results["input"], workspace, name="input")
    loaded_input = owner.load(workspace, name="input")
    print("workspace:", workspace)
    print("owner decrypted loaded input:", owner.decrypt(loaded_input))

    print("\n3. Reopen workspace in a secretless compute session")
    completed = subprocess.run(
        [sys.executable, "-c", COMPUTE_CODE, str(workspace)],
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout)
    print(completed.stdout.strip())
    computed_sum = owner.load(workspace, name="computed_sum")
    print("owner decrypted computed sum:", owner.decrypt(computed_sum))

    print("\n4. Release approved aggregate results")
    analyst = owner.create_result_recipient()
    recipient_path = Path(f"{workspace}-recipient")
    released_path = Path(f"{workspace}-released")
    analyst.save_public_key(recipient_path)
    public_key = owner.load_recipient_public_key(recipient_path)

    released_sum = owner.reencrypt_for_recipient(
        results["sum"],  # type: ignore[arg-type]
        public_key,
    )
    released_mean = owner.release_result(
        results["mean"],  # type: ignore[arg-type]
        to=analyst,
    )
    owner.save(released_sum, released_path, name="sum")
    owner.save(released_mean, released_path, name="mean")

    print("analyst sum :", analyst.decrypt(analyst.load(released_path, name="sum")))
    print("analyst mean:", analyst.decrypt(analyst.load(released_path, name="mean")))
    print("secret key saved: no")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--backend", choices=("openfhe", "fides"), default="openfhe"
    )
    args = parser.parse_args()

    with HESession.create(backend=args.backend) as session:
        results = run_math(session)
        if args.backend == "openfhe":
            run_openfhe_artifacts(session, results)
        else:
            print("\n2. Artifact and release support")
            print("SKIP save/load: local FIDES serialization is not implemented")
            print("SKIP recipient: FIDES result release is not implemented")

    print("\n5. Session closed: PASS")


if __name__ == "__main__":
    main()
