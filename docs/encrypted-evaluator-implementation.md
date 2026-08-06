# Core ciphertext evaluator implementation

## Current scope

Develop only these logical operations first:

```text
add, subtract, multiply, square, sum, mean, variance
```

The shared names live in `common/operations.py`. The OpenFHE and FIDESlib
backends each expose direct methods for the seven operations. Parameter
profiles, workflow contracts, compare/MAX, model inference, and other
workloads wait. See `he-main-api-function-matrix.md` for the detailed matrix.

## Security boundary

The trusted client owns plaintext, key generation, encryption, decryption, and
the accuracy check. The evaluator receives serialized context, operation-
specific evaluation keys, and ciphertexts. It returns ciphertext only.

Never send or log plaintext or the secret key.

## Separate backends

| Backend | Repository/image | HE runtime | Status |
| --- | --- | --- | --- |
| CPU | root `Dockerfile` / `dockerboi99/he_k8s:cpu-*` | standard `openfhe-python` | seven-operation API |
| GPU | `gpu/Dockerfile` / `dockerboi99/he_k8s:gpu-*` | FIDESlib + patched OpenFHE | matching seven-operation API |

Standard OpenFHE and FIDESlib's patched OpenFHE must never be installed or
linked into the same image/process. CPU and GPU exchange only serialized
inputs/results and run as separate jobs or services.

## Development order

1. Verify `add`, `subtract`, `multiply`, and `square` with ciphertext inputs.
2. Verify `sum` and `mean` for one ciphertext batch.
3. Add trusted-client chunk orchestration: SUM each chunk, then ADD partials.
4. Run sizes `50k`, `100k`, `500k`, `1m`, then `10m` on the server.
5. Compare CPU/GPU summaries generated from the same seed and input data.

Do not call a CUDA image a GPU benchmark until it executes the FIDESlib
operation and verifies the decrypted answer.

## Minimal API

```text
POST /v1/evaluate
operation = add | subtract | multiply | square | sum | mean | variance
```

- `add`, `subtract`: context + two ciphertexts;
- `multiply`: context + EvalMult keys + two ciphertexts;
- `square`: context + EvalMult keys + one ciphertext;
- `sum`, `mean`: context + automorphism/SUM keys + one ciphertext +
  `valid_count`.

The response contains backend, operation, evaluation time, and result
ciphertext. It contains no plaintext result.

## Next server gate

Before adding more HE functions:

- GitLab API tests pass and the CPU image builds;
- server client decrypts the seven results and checks tolerance;
- SUM works for one batch, then for chunked `50k` input;
- no request contains a secret key;
- CPU and GPU remain separate images/processes.
