# HE SDK API contract

This document describes the current Python SDK with OpenAPI-style input and
output schemas. The SDK is currently an in-process Python API rather than an
HTTP service. Types such as `EncryptedVector` contain opaque native handles
and are not directly JSON-serializable HTTP payloads.

Each Python process selects one native backend:

- `openfhe` for CPU;
- `fides` for GPU.

The SDK does not automatically switch or fall back between CPU and GPU.

## Common schemas

### CKKSConfig

```yaml
CKKSConfig:
  type: object
  properties:
    profile:
      type: string
      enum: [ckks-balanced-v1]
    scheme:
      type: string
      enum: [CKKS]
    multiplicative_depth:
      type: integer
      default: 3
    ring_dimension:
      type: integer
      default: 16384
    batch_size:
      type: integer
      default: 8192
    first_modulus_size:
      type: integer
      default: 60
    scaling_modulus_size:
      type: integer
      default: 50
    scaling_technique:
      type: string
      default: FLEXIBLEAUTO
```

### CiphertextMetadata

```yaml
CiphertextMetadata:
  type: object
  required:
    - context_id
    - context_fingerprint
    - key_bundle_id
    - scheme
    - backend
    - valid_count
    - logical_shape
    - level
    - scale_bits
  properties:
    context_id:
      type: string
    context_fingerprint:
      type: string
    key_bundle_id:
      type: string
    scheme:
      type: string
      enum: [CKKS]
    backend:
      type: string
      enum: [openfhe, fides]
    engine_version:
      type: string
    valid_count:
      type: integer
    logical_shape:
      type: array
      items:
        type: integer
    level:
      type: integer
    scale_bits:
      type: integer
    serialization_version:
      type: string
    checksum:
      type: [string, "null"]
    result_operation:
      type: [string, "null"]
      enum:
        - add
        - subtract
        - multiply
        - square
        - sum
        - mean
        - variance
        - null
```

### EncryptedVector and EncryptedScalar

```yaml
EncryptedVector:
  type: object
  x-python-type: he_sdk.EncryptedVector
  properties:
    metadata:
      $ref: "#/components/schemas/CiphertextMetadata"
    ciphertext:
      description: Opaque native handle; not a public JSON field

EncryptedScalar:
  type: object
  x-python-type: he_sdk.EncryptedScalar
  properties:
    metadata:
      $ref: "#/components/schemas/CiphertextMetadata"
    ciphertext:
      description: Opaque native handle; not a public JSON field
```

### CapabilitySet

```yaml
CapabilitySet:
  type: object
  required:
    - backend
    - schemes
    - operations
  properties:
    backend:
      type: string
      enum: [openfhe, fides]
    schemes:
      type: array
      items:
        type: string
      example: [CKKS]
    operations:
      type: array
      items:
        type: string
        enum:
          - add
          - subtract
          - multiply
          - square
          - sum
          - mean
          - variance
    supports_bootstrap:
      type: boolean
    supports_serialization:
      type: boolean
    supports_proxy_re_encryption:
      type: boolean
```

## API operations

| Group | `operationId` / Python API | OpenAPI-style input | Output | Current backend support | Meaning |
|---|---|---|---|---|---|
| Configuration | `createCKKSConfig` / `CKKSConfig.profile()` | `{name: "ckks-balanced-v1"}` | `CKKSConfig` | CPU, GPU | Creates the CKKS configuration shared by the complete session. |
| Session | `createSession` / `HESession.create()` | `{device?: "cpu" \| "gpu", backend?: "openfhe" \| "fides", config?: CKKSConfig}` | `HESession` | CPU, GPU | Creates a trusted local session, HE context, and key bundle. Pass `device` or `backend`, not both. The current API accepts no credentials. |
| Session | `getCapabilities` / `session.capabilities` | None | `CapabilitySet` | CPU, GPU | Reports backend, scheme, operations, serialization, bootstrap, and proxy re-encryption capabilities. |
| Session | `openWorkspace` / `HESession.open_workspace()` | `{path: string, execution_backend?: "openfhe" \| "fides"}` | `HESession` with no secret key | OpenFHE; FIDES compute-only bridge | Opens a session from persisted public/evaluation material. This session cannot decrypt. |
| Encryption | `encryptVector` / `session.encrypt()` | `{values: number[]}` with `1..batch_size` elements | `EncryptedVector` | CPU and trusted local GPU | Encrypts a vector with the session public key. Context and public key are owned by the session and are not passed with every call. |
| Decryption | `decryptValue` / `session.decrypt()` | `{value: EncryptedVector \| EncryptedScalar}` | `number[] \| number` | CPU and trusted local GPU | Decrypts with the secret key belonging to the same session. Compute-only sessions are rejected. |
| Arithmetic | `addVectors` / `session.add()` | `{left: EncryptedVector, right: EncryptedVector}` | `EncryptedVector` | CPU, GPU | Adds corresponding vector elements. Inputs must have compatible session, context, key bundle, shape, and packing layout. |
| Arithmetic | `subtractVectors` / `session.subtract()` | `{left: EncryptedVector, right: EncryptedVector}` | `EncryptedVector` | CPU, GPU | Subtracts corresponding vector elements with the same compatibility requirements as `add`. |
| Arithmetic | `multiplyVectors` / `session.multiply()` | `{left: EncryptedVector, right: EncryptedVector}` | `EncryptedVector` | CPU, GPU | Multiplies corresponding vector elements. Requires a multiplication key and consumes one multiplicative level. |
| Arithmetic | `squareVector` / `session.square()` | `{value: EncryptedVector}` | `EncryptedVector` | CPU, GPU | Squares each encrypted element and consumes one multiplicative level. |
| Aggregation | `sumVector` / `session.sum()` | `{value: EncryptedVector}` | `EncryptedScalar` | CPU, GPU | Sums all valid elements. `valid_count` is read from ciphertext metadata. |
| Aggregation | `meanVector` / `session.mean()` | `{value: EncryptedVector}` | `EncryptedScalar` | CPU, GPU | Calculates the mean. The SDK reads the element count from metadata. |
| Aggregation | `varianceVector` / `session.variance()` | `{value: EncryptedVector}` | `EncryptedScalar` | CPU, GPU | Calculates population variance. Requires multiplication and rotation keys and currently has depth cost 2. |
| Artifact | `saveEncryptedArtifact` / `session.save()` | `{value: EncryptedVector \| EncryptedScalar \| ReleasedResult, workspace: string, name: string}` | `{path: string}` | OpenFHE CPU; existing FIDES workspace mode | Persists ciphertext and metadata. The workspace does not persist plaintext or a secret key. |
| Artifact | `loadEncryptedArtifact` / `session.load()` | `{workspace: string, name: string}` | `EncryptedVector \| EncryptedScalar \| ReleasedResult` | OpenFHE CPU; existing FIDES workspace mode | Loads an artifact and validates context, configuration, key bundle, checksum, and serialization version. |
| Result release | `createResultRecipient` / `session.create_result_recipient()` | None | `ResultRecipient` | OpenFHE CPU | Generates a separate recipient ID and key pair. The current SDK generates the identity internally. |
| Result release | `saveRecipientPublicKey` / `recipient.save_public_key()` | `{path: string}` | `{path: string}` | OpenFHE CPU | Exports only the recipient public key for the owner/release authority. |
| Result release | `loadRecipientPublicKey` / `session.load_recipient_public_key()` | `{path: string}` | `RecipientPublicKey` | OpenFHE CPU | Loads the recipient public key into the owner session. |
| Result release | `reencryptForRecipient` / `session.reencrypt_for_recipient()` | `{value: EncryptedScalar, recipient_public_key: RecipientPublicKey}` | `ReleasedResult` | OpenFHE CPU | Proxy re-encrypts an already-calculated result into the recipient key domain. Only results with `sum`, `mean`, or `variance` provenance are accepted. |
| Result release | `releaseResult` / `session.release_result()` | `{value: EncryptedScalar, to: ResultRecipient}` | `ReleasedResult` | OpenFHE CPU | Convenience API for a recipient belonging to the same owner session. It does not calculate the aggregate. |
| Result release | `loadReleasedResult` / `recipient.load()` | `{workspace: string, name: string}` | `ReleasedResult` | OpenFHE CPU | Loads a released result addressed to this recipient. |
| Result release | `decryptReleasedResult` / `recipient.decrypt()` | `{value: ReleasedResult}` | `number` | OpenFHE CPU | Decrypts an aggregate scalar that was proxy re-encrypted for the matching recipient key. |
| Lifecycle | `closeSession` / `session.close()` | None | `null` / `None` | CPU, GPU | Closes the backend, removes native context/key references, and releases resources. Repeated calls are safe. |

## Backend capability summary

| Capability | OpenFHE CPU | FIDES trusted local GPU | FIDES compute-only workspace |
|---|---:|---:|---:|
| Create context and keys | Yes | Yes | No; loads existing public material |
| Encrypt | Yes | Yes | No |
| Decrypt | Yes | Yes | No secret key |
| Add, subtract, multiply, square | Yes | Yes | Yes |
| Sum, mean, variance | Yes | Yes | Yes |
| Create a new workspace | Yes | No | No |
| Save/load ciphertext artifacts | Yes | No | Existing compatible workspace only |
| Proxy re-encryption | Trial | No | No |
| Automatic CPU/GPU fallback | No | No | No |

## Error contract for a future HTTP API

The current Python API raises exceptions. If it is later exposed through
HTTP, the following status mapping is recommended.

| Python exception | Suggested HTTP status | Meaning |
|---|---:|---|
| `ValueError` | `400` | Invalid input or HE configuration |
| `IncompatibleCiphertextError` | `409` | Different session, context, key bundle, shape, backend, or incompatible level |
| `SecretKeyUnavailableError` | `403` | A compute-only session attempted to decrypt |
| `UnsupportedOperationError` | `422` | The selected backend does not support the requested capability |
| `ArtifactError` | `422` | Workspace or artifact is missing, corrupt, or incompatible |
| `ResultReleaseError` | `422` | The encrypted result is not eligible for release |
| `BackendUnavailableError` | `503` | The native CPU/GPU backend could not initialize |

## HTTP serialization note

An HTTP API must not attempt to serialize the private Python `_handle` field.
Use one of these boundaries instead:

1. a workspace artifact reference containing `workspace` and `name`; or
2. an explicitly versioned ciphertext byte encoding such as Base64 with its
   complete `CiphertextMetadata`.

Plaintext and secret keys must not be included in evaluator requests or
secretless workspaces.
