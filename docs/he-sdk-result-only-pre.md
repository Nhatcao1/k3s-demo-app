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
workspace, or analyst client. Version `0.4.1.dev0` creates and consumes it
inside `release_result()` and never returns it from the SDK.

The scalar allowlist and `result_operation` metadata are release-policy checks,
not cryptographic proof that a particular function was evaluated. Production
must run this method in an isolated result-release service that receives only
approved result artifacts. Query authorization, minimum cohort sizes, rate
limits, and audit logs are still required because repeated aggregate queries
can reveal information even when encryption and PRE are correct.

## Trial API

```python
from he_sdk import HESession

with HESession.create(backend="openfhe") as owner:
    encrypted_input = owner.encrypt([10.0, 20.0, 30.0])
    analyst = owner.create_result_recipient()

    encrypted_sum = owner.sum(encrypted_input)
    released_sum = owner.release_result(encrypted_sum, to=analyst)

    print(analyst.decrypt(released_sum))  # approximately 60.0
```

Only `EncryptedScalar` results carrying `sum`, `mean`, or `variance` provenance
are accepted. Passing `EncryptedVector` input to either `release_result()` or
`analyst.decrypt()` raises `ResultReleaseError`.

## How this fits the existing two notebooks

1. `01_owner_encrypt.ipynb` remains the data-owner and release-authority trial.
   It creates the analyst recipient before publishing inputs, then keeps the
   recipient and owner session in memory.
2. `02_compute_encrypted.ipynb` remains unchanged. It sees no owner secret,
   analyst secret, or PRE material and writes encrypted aggregate results.
3. Back in notebook 01, load only `sum`, `mean`, and `variance`, call
   `owner.release_result(..., to=analyst)`, and deliver the returned objects to
   the analyst trial.

This first increment is intentionally in-memory. Persisted analyst keys and
released-result artifacts need a separate protected format and deployment
boundary; they must not be added to the existing secretless compute workspace.
