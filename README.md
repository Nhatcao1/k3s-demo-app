# HE application for the K3s lab

This repository now builds one secretless **CPU OpenFHE evaluator**. The first
scope is intentionally small:

- primitives: `add`, `subtract`, `multiply`;
- reduction: `sum`.

The API accepts serialized CKKS context, evaluation keys when required, and
ciphertexts. It never accepts plaintext or a secret key and returns only a
result ciphertext.

## CPU and GPU stay separate

```text
k3s-demo-app                         he-gpu-worker
standard openfhe-python              FIDESlib + its patched OpenFHE
CPU image/process                    CUDA GPU image/process
```

Do not install or link standard OpenFHE and FIDESlib's patched OpenFHE in the
same image or process. A future GPU implementation must use the same logical
operation names and serialized job/result contract, but it is built and run
independently in `he-gpu-worker`. GPU primitive/SUM execution is not claimed
until that worker actually implements and passes the server tests.

The backend-neutral operation list is in `common/operations.py`. It imports no
HE library.

## Evaluator API

```text
GET  /healthz
GET  /readyz
GET  /v1/capabilities
POST /v1/evaluate
```

Primitive request:

```json
{
  "operation": "add",
  "context": "<base64>",
  "ciphertext_a": "<base64>",
  "ciphertext_b": "<base64>"
}
```

`multiply` also requires `evaluation_keys` containing serialized EvalMult
keys. A SUM request uses one ciphertext:

```json
{
  "operation": "sum",
  "context": "<base64>",
  "ciphertext_a": "<base64>",
  "evaluation_keys": "<base64 serialized automorphism/SUM keys>",
  "valid_count": 8192,
  "request_id": "optional-run-id"
}
```

For data larger than one CKKS batch, the trusted client encrypts chunks, calls
`sum` for each chunk, then combines the encrypted partial scalars with `add`.

## GitLab pipeline

Contract tests require no HE installation. On the default branch, GitLab CI
builds and pushes:

```text
registry.gitlab.com/nhatcao99uetwork/k3s-demo-app/openfhe-evaluator-cpu:<full-commit-sha>
```

The image contains only standard `openfhe-python` and starts `python -m
api.app`. FIDESlib is not copied into this image.

Run the dependency-free tests with:

```sh
python3 -m unittest discover -s tests -v
```

The older `gateway/`, `he_client/`, and related examples remain as historical
trusted plaintext/session trial code. They are tested but are not copied into
the evaluator image.

See `docs/encrypted-evaluator-implementation.md` for the short implementation
and server-test plan.
