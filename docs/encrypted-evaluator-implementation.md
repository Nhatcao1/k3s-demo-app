# Encrypted-only evaluator implementation contract

## Status and first scope

This document is the binding contract for the next implementation. The
existing `gateway/` is a trusted plaintext trial and remains operational until
this replacement passes its tests.

Implement one workload first:

```text
CKKS encrypted vector -> SUM -> encrypted scalar
```

CPU is mandatory. GPU is a later, separate backend and must not block the CPU
delivery.

## Security boundary

```text
trusted test client
  plaintext fixture + secret key
  -> encrypt
  -> context + SUM evaluation keys + ciphertext
                                      |
                                      v
secretless evaluator API
  deserialize -> encrypted SUM -> serialize result ciphertext
                                      |
                                      v
trusted test client
  decrypt -> compare with plaintext reference -> summary.json
```

Mandatory rules:

- plaintext and the secret key never enter an evaluator request;
- the evaluator image contains no test fixture and writes no request body to
  logs;
- context and evaluation keys are not confused with the secret key;
- the client secret key is generated for the run, kept in memory or an
  `emptyDir`, and never committed or stored in a Kubernetes Secret;
- only the trusted client decrypts the final ciphertext;
- cryptographic parameters come from the reviewed backend profile, not from
  HTTP fields.

## Source changes

Reuse the existing ciphertext-only prototype rather than creating another
service framework:

```text
api/app.py
  extend the existing serialized-ciphertext evaluator from add to SUM

client/encrypted_sum_benchmark.py
  new trusted client: fixture, reference, keygen, encrypt, HTTP call, decrypt

common/result_contract.py
  one validator/writer shared by CPU and future GPU benchmark results

tests/test_encrypted_sum_api.py
  request validation and ciphertext-only evaluator contract

tests/test_encrypted_sum_benchmark.py
  deterministic client orchestration and accuracy gate

Dockerfile.evaluator-cpu
  evaluator API image; default command starts api.app

Dockerfile.test-client
  one-shot encrypted smoke and benchmark client
```

`encryptor/app.py` must not be deployed for this target because it accepts
plaintext over HTTP. `gateway/app.py` remains historical trial code and is not
included in the new evaluator image.

## Minimal HTTP contract

Keep the existing health endpoints and add one evaluation endpoint:

```text
GET  /healthz
GET  /readyz
GET  /v1/capabilities
POST /v1/evaluate/sum
```

Request fields:

```json
{
  "context": "<base64 OpenFHE context>",
  "evaluation_keys": "<base64 SUM/rotation keys>",
  "ciphertext": "<base64 input ciphertext>",
  "valid_count": 8192,
  "request_id": "sum-<git-sha>-<seed>-8192"
}
```

Response fields:

```json
{
  "request_id": "sum-<git-sha>-<seed>-8192",
  "workload": "sum",
  "backend": "cpu",
  "result_ciphertext": "<base64 output ciphertext>",
  "evaluation_seconds": 1.23
}
```

The response must not contain a plaintext or decrypted result.

## Shared benchmark result

CPU and GPU execute separately but write the same schema to different files:

```text
benchmark_results/<run-id>/cpu.json
benchmark_results/<run-id>/gpu.json
benchmark_results/<run-id>/comparison.md
```

Required `summary.json` fields:

```text
run_id, workload, backend, status
git_commit, image_digest, input_seed, input_count, ciphertext_chunks
warmup_runs, measured_runs
setup_seconds, keygen_seconds, encryption_seconds
evaluation_seconds, decryption_seconds, end_to_end_seconds
maximum_absolute_error, maximum_relative_error
peak_host_memory, peak_gpu_memory
```

Use one warm-up and at least five measured runs. CPU and GPU must use the same
seed, values, valid count, expected result and accuracy tolerance.

## GitLab CI and images

Add these pipeline jobs:

```text
test-encrypted-evaluator
build-openfhe-evaluator-cpu
build-openfhe-test-client
```

Default-branch images:

```text
registry.gitlab.com/nhatcao99uetwork/k3s-demo-app/openfhe-evaluator-cpu:<full-commit-sha>
registry.gitlab.com/nhatcao99uetwork/k3s-demo-app/openfhe-test-client:<full-commit-sha>
```

The future GPU image is separate:

```text
registry.gitlab.com/nhatcao99uetwork/k3s-demo-app/fides-evaluator-gpu:<full-commit-sha>
```

## Completion gates

The CPU milestone is complete only when:

1. dependency-free API contract tests pass;
2. the evaluator rejects plaintext, unknown fields and missing evaluation
   keys;
3. both images build from one Git commit;
4. the encrypted client smoke Job succeeds against the K3s evaluator;
5. the decrypted SUM passes the declared tolerance;
6. evaluator logs contain no plaintext, secret key or serialized payload;
7. the CPU benchmark produces a schema-valid `cpu.json`.

GPU implementation starts only after these gates pass.
