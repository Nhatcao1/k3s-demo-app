#!/usr/bin/env python3
"""Straight-line example of the current HE SDK functions."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

from he_sdk import HESession


parser = argparse.ArgumentParser()
parser.add_argument(
    "--backend",
    choices=("openfhe", "fides"),
    default="openfhe",
)
args = parser.parse_args()

left_values = [1.25, -2.0, 3.5, 4.0]
right_values = [0.75, 5.0, -1.5, 2.0]

print("backend:", args.backend)
print("left input:", left_values)
print("right input:", right_values)

session = HESession.create(backend=args.backend)

left_ct = session.encrypt(left_values)
right_ct = session.encrypt(right_values)
print("\nencrypted left:", left_ct)
print("decrypted left:", session.decrypt(left_ct))

add_ct = session.add(left_ct, right_ct)
print("\nadd expected:", [2.0, 3.0, 2.0, 6.0])
print("add decrypted:", session.decrypt(add_ct))

subtract_ct = session.subtract(left_ct, right_ct)
print("\nsubtract expected:", [0.5, -7.0, 5.0, 2.0])
print("subtract decrypted:", session.decrypt(subtract_ct))

multiply_ct = session.multiply(left_ct, right_ct)
print("\nmultiply expected:", [0.9375, -10.0, -5.25, 8.0])
print("multiply decrypted:", session.decrypt(multiply_ct))

square_ct = session.square(left_ct)
print("\nsquare expected:", [1.5625, 4.0, 12.25, 16.0])
print("square decrypted:", session.decrypt(square_ct))

sum_ct = session.sum(left_ct)
print("\nsum expected:", 6.75)
print("sum decrypted:", session.decrypt(sum_ct))

mean_ct = session.mean(left_ct)
print("\nmean expected:", 1.6875)
print("mean decrypted:", session.decrypt(mean_ct))

variance_ct = session.variance(left_ct)
print("\nvariance expected:", 5.60546875)
print("variance decrypted:", session.decrypt(variance_ct))

if args.backend == "openfhe":
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    workspace = Path(f"he-sdk-showcase-{timestamp}")

    print("\n--- save and load ---")
    session.save(left_ct, workspace, name="input")
    loaded_ct = session.load(workspace, name="input")
    print("workspace:", workspace)
    print("loaded input:", session.decrypt(loaded_ct))

    # Use another process for the compute-only session. It receives public
    # material and ciphertext, but it does not receive the secret key.
    compute_code = r"""
import json
from pathlib import Path
import sys
from he_sdk import HESession, SecretKeyUnavailableError

workspace = Path(sys.argv[1])
compute = HESession.open_workspace(workspace)
input_ct = compute.load(workspace, name="input")
result_ct = compute.sum(input_ct)
compute.save(result_ct, workspace, name="compute_sum")

try:
    compute.decrypt(input_ct)
except SecretKeyUnavailableError:
    print(json.dumps({"compute_has_secret_key": False}))

compute.close()
"""

    print("\n--- reopen secretless compute session ---")
    completed = subprocess.run(
        [sys.executable, "-c", compute_code, str(workspace)],
        check=True,
        capture_output=True,
        text=True,
        timeout=600,
    )
    print(json.loads(completed.stdout))

    compute_sum_ct = session.load(workspace, name="compute_sum")
    print("owner decrypts compute result:", session.decrypt(compute_sum_ct))

    print("\n--- release result to recipient ---")
    analyst = session.create_result_recipient()
    recipient_directory = Path(f"{workspace}-recipient")
    released_workspace = Path(f"{workspace}-released")

    analyst.save_public_key(recipient_directory)
    analyst_public_key = session.load_recipient_public_key(
        recipient_directory
    )

    released_sum = session.reencrypt_for_recipient(
        sum_ct,
        analyst_public_key,
    )
    released_mean = session.release_result(mean_ct, to=analyst)

    session.save(released_sum, released_workspace, name="sum")
    session.save(released_mean, released_workspace, name="mean")

    analyst_sum = analyst.load(released_workspace, name="sum")
    analyst_mean = analyst.load(released_workspace, name="mean")
    print("analyst decrypts sum:", analyst.decrypt(analyst_sum))
    print("analyst decrypts mean:", analyst.decrypt(analyst_mean))
    print("secret key saved: no")
else:
    print("\n--- current FIDES limits ---")
    print("save/load: not implemented for a local FIDES session")
    print("recipient release: not implemented for FIDES")

session.close()
print("\nsession closed")
