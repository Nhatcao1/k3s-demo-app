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
k3s-demo-app/Dockerfile              k3s-demo-app/gpu/Dockerfile
standard openfhe-python              FIDESlib + its patched OpenFHE
CPU image/process                    CUDA GPU image/process
```

Do not install or link standard OpenFHE and FIDESlib's patched OpenFHE in the
same image or process. Both images are built from this repository, but remain
independent processes. The GPU worker has an in-memory primitive/SUM backend.
Remote ciphertext transport is not claimed until a FIDESlib-compatible
serialization adapter is implemented and passes the server tests.

The small operation list is in `common/operations.py`. The four explicit
OpenFHE methods live in `backends/openfhe_python.py`; the matching FIDESlib
methods live in `gpu/worker/src/fides_backend.cpp`. The HTTP layer contains no
HE-library calls. Parameter profiles and workflow contracts are intentionally
left for later.

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
docker.io/dockerboi99/he_k8s:<full-commit-sha>
```

The CPU image contains only standard `openfhe-python` and starts `python -m
api.app`. The GPU image is built separately from `gpu/Dockerfile` and contains
FIDESlib plus its patched OpenFHE. Neither runtime is copied into the other
image.

The GPU push requires masked project CI/CD variables `DOCKERHUB_USERNAME` and
`DOCKERHUB_TOKEN`. The Docker Hub token needs read/write permission.

Run the dependency-free tests with:

```sh
python3 -m unittest discover -s tests -v
```

The older `gateway/`, `he_client/`, and related examples remain as historical
trusted plaintext/session trial code. They are tested but are not copied into
the evaluator image.

See `docs/encrypted-evaluator-implementation.md` for the short implementation
and server-test plan.
