#!/usr/bin/env python3
"""Run every public HE SDK operation with either the CPU or GPU backend.

Examples:
    python full_session_showcase.py
    python full_session_showcase.py --device gpu
"""

import argparse
import os
from pathlib import Path
import tempfile

from he_sdk import BackendUnavailableError, HESession, __version__


# Normally no option is needed: each environment installs only one native
# extra, so the SDK detects CPU or GPU. The option is an explicit override.
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--device",
    choices=("cpu", "gpu"),
    default=os.getenv("HE_SDK_DEVICE"),
)
DEVICE = parser.parse_args().device

left_values = [1.0, 2.0, 3.0, 4.0]
right_values = [10.0, 20.0, 30.0, 40.0]

print("he_sdk version:", __version__)
print("requested device:", DEVICE or "auto")
print("left input:", left_values)
print("right input:", right_values)

# HESession.create()
try:
    session = HESession.create(device=DEVICE)
except BackendUnavailableError as error:
    if DEVICE == "cpu":
        install_hint = 'python -m pip install "he_looming_sdk[cpu]==0.6.4"'
    elif DEVICE == "gpu":
        install_hint = (
            "python -m pip install --extra-index-url "
            '"https://gitlab.com/api/v4/projects/84844502/packages/pypi/simple" '
            '"he_looming_sdk[gpu]==0.6.4"'
        )
    else:
        install_hint = (
            'CPU: python -m pip install "he_looming_sdk[cpu]==0.6.4"\n'
            "GPU: python -m pip install --extra-index-url "
            '"https://gitlab.com/api/v4/projects/84844502/packages/pypi/simple" '
            '"he_looming_sdk[gpu]==0.6.4"'
        )
    raise SystemExit(f"{error}\nInstall this backend with:\n{install_hint}") from error

print("selected backend:", session.capabilities.backend)
print("capabilities:", session.capabilities)

# encrypt() and decrypt()
left_ct = session.encrypt(left_values)
right_ct = session.encrypt(right_values)
print("encrypted left:", left_ct)
print("decrypted left:", session.decrypt(left_ct))

# add()
add_ct = session.add(left_ct, right_ct)
print("add expected:", [11.0, 22.0, 33.0, 44.0])
print("add decrypted:", session.decrypt(add_ct))

# subtract()
subtract_ct = session.subtract(left_ct, right_ct)
print("subtract expected:", [-9.0, -18.0, -27.0, -36.0])
print("subtract decrypted:", session.decrypt(subtract_ct))

# multiply()
multiply_ct = session.multiply(left_ct, right_ct)
print("multiply expected:", [10.0, 40.0, 90.0, 160.0])
print("multiply decrypted:", session.decrypt(multiply_ct))

# square()
square_ct = session.square(left_ct)
print("square expected:", [1.0, 4.0, 9.0, 16.0])
print("square decrypted:", session.decrypt(square_ct))

# sum()
sum_ct = session.sum(left_ct)
print("sum expected:", 10.0)
print("sum decrypted:", session.decrypt(sum_ct))

# mean()
mean_ct = session.mean(left_ct)
print("mean expected:", 2.5)
print("mean decrypted:", session.decrypt(mean_ct))

# variance(): population variance
variance_ct = session.variance(left_ct)
print("variance expected:", 1.25)
print("variance decrypted:", session.decrypt(variance_ct))

workspace: Path | None = None

# save() and load()
if session.capabilities.supports_serialization:
    workspace = Path(tempfile.mkdtemp(prefix="he-sdk-workspace-"))
    session.save(left_ct, workspace, name="input")
    loaded_ct = session.load(workspace, name="input")
    print("saved workspace:", workspace)
    print("loaded ciphertext:", loaded_ct)
    print("loaded plaintext:", session.decrypt(loaded_ct))
else:
    print("save/load: not supported by this local backend")

# create_result_recipient(), load_recipient_public_key(),
# reencrypt_for_recipient(), and release_result()
if session.capabilities.supports_proxy_re_encryption:
    analyst = session.create_result_recipient()
    recipient_directory = Path(
        tempfile.mkdtemp(prefix="he-sdk-recipient-")
    )
    released_workspace = Path(
        tempfile.mkdtemp(prefix="he-sdk-released-")
    )

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

    loaded_sum = analyst.load(released_workspace, name="sum")
    loaded_mean = analyst.load(released_workspace, name="mean")
    print("recipient sum:", analyst.decrypt(loaded_sum))
    print("recipient mean:", analyst.decrypt(loaded_mean))
else:
    print("recipient release: not supported by this backend")

# close()
session.close()
print("session closed")

# HESession.open_workspace()
if workspace is not None:
    compute = HESession.open_workspace(workspace)
    compute_input = compute.load(workspace, name="input")
    compute_result = compute.sum(compute_input)
    compute.save(compute_result, workspace, name="compute_sum")
    print("compute-only encrypted result:", compute_result)
    compute.close()
    print("compute workspace closed")
else:
    print("open_workspace: skipped because this backend cannot save artifacts")
