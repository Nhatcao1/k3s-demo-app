# HE SDK sequence diagrams

This directory explains the current HE SDK API as one overall lifecycle and
five focused sequence diagrams. The diagrams describe the implemented API;
they do not imply automatic CPU/GPU fallback or GPU result release.

## Diagram index

| Diagram | Purpose |
|---|---|
| `00-overall-lifecycle.mmd` | Complete trusted session lifecycle from configuration to calculation, persistence, optional result release, and close. |
| `01-session-and-backend.mmd` | Session creation, backend selection, native-runtime guard, capability lookup, and close. |
| `02-encrypt-compute-decrypt.mmd` | Encryption, validation, all seven calculation functions, metadata updates, and decryption. |
| `03-workspace-lifecycle.mmd` | CPU workspace initialization, public/evaluation material export, ciphertext save/load, and compute-only reopen. |
| `04-result-release.mmd` | CPU-only recipient creation, aggregate calculation, proxy re-encryption, persistence, load, and recipient decryption. |
| `05-validation-errors.mmd` | Shared validation order and the main SDK exception paths. |

## Public API mapping

| Public API | Primary diagram |
|---|---|
| `CKKSConfig.profile()` | `01-session-and-backend.mmd` |
| `HESession.create()` | `01-session-and-backend.mmd` |
| `session.capabilities` | `01-session-and-backend.mmd` |
| `session.encrypt()` | `02-encrypt-compute-decrypt.mmd` |
| `session.decrypt()` | `02-encrypt-compute-decrypt.mmd` |
| `session.add()` | `02-encrypt-compute-decrypt.mmd` |
| `session.subtract()` | `02-encrypt-compute-decrypt.mmd` |
| `session.multiply()` | `02-encrypt-compute-decrypt.mmd` |
| `session.square()` | `02-encrypt-compute-decrypt.mmd` |
| `session.sum()` | `02-encrypt-compute-decrypt.mmd` |
| `session.mean()` | `02-encrypt-compute-decrypt.mmd` |
| `session.variance()` | `02-encrypt-compute-decrypt.mmd` |
| `session.save()` | `03-workspace-lifecycle.mmd` |
| `session.load()` | `03-workspace-lifecycle.mmd` |
| `HESession.open_workspace()` | `03-workspace-lifecycle.mmd` |
| `session.create_result_recipient()` | `04-result-release.mmd` |
| `recipient.save_public_key()` | `04-result-release.mmd` |
| `session.load_recipient_public_key()` | `04-result-release.mmd` |
| `session.reencrypt_for_recipient()` | `04-result-release.mmd` |
| `session.release_result()` | `04-result-release.mmd` |
| `recipient.load()` | `04-result-release.mmd` |
| `recipient.decrypt()` | `04-result-release.mmd` |
| `session.close()` | `01-session-and-backend.mmd` |

## Current boundaries

- Each Python process selects one native runtime: stock OpenFHE CPU or FIDES
  GPU with patched OpenFHE.
- CPU OpenFHE implements workspace creation, serialization, and the trial
  aggregate-result proxy re-encryption flow.
- Trusted local CPU and GPU sessions expose encrypt, decrypt, add, subtract,
  multiply, square, sum, mean, and variance.
- Result release accepts only encrypted `sum`, `mean`, and `variance` results.
- The workspace contains context, public/evaluation keys, metadata, and
  ciphertexts. It contains no plaintext or secret key.
