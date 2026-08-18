"""Minimal in-memory CKKS PRE trial for result-only analyst access."""

from he_sdk import HESession, ResultReleaseError


VALUES = [10.0, 20.0, 30.0]


with HESession.create(backend="openfhe") as owner:
    encrypted_input = owner.encrypt(VALUES)

    # This is a second OpenFHE key pair in the same CKKS context.  Its secret
    # key cannot decrypt encrypted_input, which is under the owner's key.
    analyst = owner.create_result_recipient()

    encrypted_results = {
        "sum": owner.sum(encrypted_input),
        "mean": owner.mean(encrypted_input),
        "variance": owner.variance(encrypted_input),
    }

    # In production this loop belongs in a separate release service.  The
    # compute worker must never receive the owner secret or PRE re-key.
    released_results = {
        operation: owner.release_result(result, to=analyst)
        for operation, result in encrypted_results.items()
    }

    try:
        analyst.decrypt(encrypted_input)  # type: ignore[arg-type]
    except ResultReleaseError:
        print("PASS: analyst cannot decrypt the owner input ciphertext")

    for operation, result in released_results.items():
        print(operation, analyst.decrypt(result))
