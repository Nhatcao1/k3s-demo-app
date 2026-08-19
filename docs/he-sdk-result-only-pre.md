# Result-only analyst access with CKKS PRE

## Goal

The data owner encrypts input with an owner key. The compute worker receives
only public/evaluation material and calculates encrypted `sum`, `mean`, or
`variance`. A separate analyst key can decrypt released aggregate results but
cannot decrypt the original input ciphertext.

## Why PRE is valid, with one important boundary

OpenFHE supports proxy re-encryption for CKKS and exposes `ReKeyGen` and
`ReEncrypt` in its Python binding. The SDK now uses those calls to transform an
aggregate ciphertext from the owner key to a distinct analyst key.

PRE does **not** bind a re-encryption key to a function. Anyone who has both an
owner ciphertext and the owner-to-analyst re-key can transform that ciphertext.
Therefore the re-key must not be placed in the compute notebook, PostgreSQL,
workspace, or analyst client. Version `0.4.1` creates and consumes it
inside `reencrypt_for_recipient()` and never returns it from the SDK.

The scalar allowlist and `result_operation` metadata are release-policy checks,
not cryptographic proof that a particular function was evaluated. Production
must run this method in an isolated result-release service that receives only
approved result artifacts. Query authorization, minimum cohort sizes, rate
limits, and audit logs are still required because repeated aggregate queries
can reveal information even when encryption and PRE are correct.

## Trial API: public-key handoff and released-result workspace

```python
from pathlib import Path
from he_sdk import HESession

ANALYST_PUBLIC_KEY = Path("./analyst-public")
RESULT_WORKSPACE = Path("./released-results")

with HESession.create(backend="openfhe") as owner:
    encrypted_input = owner.encrypt([10.0, 20.0, 30.0])

    # Trial shortcut: in production the analyst creates this in its own
    # process/HSM and sends only the exported public-key directory.
    analyst = owner.create_result_recipient()
    analyst.save_public_key(ANALYST_PUBLIC_KEY)
    analyst_public_key = owner.load_recipient_public_key(ANALYST_PUBLIC_KEY)

    owner_result = owner.sum(encrypted_input)
    analyst_result = owner.reencrypt_for_recipient(
        owner_result, analyst_public_key
    )
    owner.save(
        analyst_result, RESULT_WORKSPACE, name="released_sum"
    )

    released_sum = analyst.load(RESULT_WORKSPACE, name="released_sum")
    print(analyst.decrypt(released_sum))  # approximately 60.0
```

Only `EncryptedScalar` results carrying `sum`, `mean`, or `variance` provenance
are accepted. Passing `EncryptedVector` input to either
`reencrypt_for_recipient()` or `analyst.decrypt()` raises
`ResultReleaseError`. `release_result(..., to=analyst)` remains as an
in-process convenience wrapper.

`analyst-public/recipient-public-key.bin` contains only the analyst public key.
Its manifest explicitly sets `contains_secret_key` to `false`. A released
ciphertext is indexed as `kind: released_scalar` and includes the target
`recipient_id`; `analyst.load()` rejects normal vectors, owner-key scalars, and
results addressed to another analyst.

Checksums detect accidental corruption, but they do not authenticate the
analyst identity. The release authority must verify the public-key manifest
through an authenticated channel (or a signature/certificate) before release;
otherwise an attacker could replace both the public key and its checksum.

The current trial intentionally does **not** serialize the analyst secret key.
Keep the analyst notebook/kernel alive until it loads and decrypts the result.
Persisting that secret for a later session belongs behind an analyst-owned HSM
or a separately encrypted keystore, not in the shared HE workspace.

## How this fits the existing two notebooks

1. The analyst notebook opens the same public CKKS context, creates a
   `ResultRecipient`, keeps it alive, and exports only its public key artifact.
2. `02_compute_encrypted.ipynb` remains unchanged. It sees no owner secret,
   analyst secret, or PRE material and writes encrypted aggregate results.
3. The owner/release notebook loads only `sum`, `mean`, and `variance`, loads
   the analyst public key, calls `reencrypt_for_recipient()`, and saves each
   result under a `released_*` name.
4. The analyst notebook uses `analyst.load()` and `analyst.decrypt()` to see
   the released scalar. It cannot load an input as `ReleasedResult`, and its
   distinct native secret key cannot decrypt owner input ciphertexts.

For the notebook trial, files can use a PVC. PostgreSQL should store artifact
URIs, checksums, recipient IDs, status, and audit metadata—not native secret
keys, PRE re-keys, or ciphertext blobs unless a separate artifact codec and
size policy are introduced.
