"""CKKS PRE trial with public-key handoff and persisted released results."""

from pathlib import Path
import tempfile

from he_sdk import HESession, ResultReleaseError


VALUES = [10.0, 20.0, 30.0]


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    public_key_directory = root / "analyst-public"
    result_workspace = root / "released-results"

    with HESession.create(backend="openfhe") as owner:
        encrypted_input = owner.encrypt(VALUES)

        # The analyst keeps this recipient object. Only its public half crosses
        # to the owner/release boundary; the artifact contains no secret key.
        analyst = owner.create_result_recipient()
        analyst.save_public_key(public_key_directory)
        analyst_public_key = owner.load_recipient_public_key(
            public_key_directory
        )

        encrypted_results = {
            "sum": owner.sum(encrypted_input),
            "mean": owner.mean(encrypted_input),
            "variance": owner.variance(encrypted_input),
        }

        # In production this belongs in an isolated release service. It never
        # exports the ephemeral PRE re-key, only recipient-encrypted results.
        for operation, owner_result in encrypted_results.items():
            analyst_result = owner.reencrypt_for_recipient(
                owner_result, analyst_public_key
            )
            owner.save(
                analyst_result,
                result_workspace,
                name=f"released_{operation}",
            )

        try:
            analyst.decrypt(encrypted_input)  # type: ignore[arg-type]
        except ResultReleaseError:
            print("PASS: analyst cannot decrypt the owner input ciphertext")

        for operation in encrypted_results:
            analyst_result = analyst.load(
                result_workspace, name=f"released_{operation}"
            )
            print(operation, analyst.decrypt(analyst_result))
