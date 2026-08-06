# HE application for the K3s lab

This repository now builds one secretless **CPU OpenFHE evaluator**. The first
scope is intentionally small:

- primitives: `add`, `subtract`, `multiply`;
- unary: `square`;
- reductions: `sum`, `mean`.

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
independent processes. The GPU worker receives serialized artifacts through
its HTTP adapter and performs the HE operations in native FIDESlib C++.

The small operation list is in `common/operations.py`. The six explicit
CPU defaults and direct functions live in `openfhe_cpu/runtime.py`, and the
serialized evaluator adapter lives in `backends/openfhe_python.py`. The
matching FIDESlib methods live in `gpu/worker/src/fides_backend.cpp`. The HTTP
layer contains no HE-library calls. Parameter profiles and workflow contracts
are intentionally left for later.

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

`multiply` and `square` require `evaluation_keys` containing serialized
EvalMult keys. `sum` and `mean` use one ciphertext plus rotation keys:

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
See `docs/he-main-api-function-matrix.md` for the complete function/key table
and the next implementation order.

## GitLab pipeline

Contract tests require no HE installation. On the default branch, GitLab CI
builds and pushes:

```text
docker.io/dockerboi99/he_k8s:cpu-<full-commit-sha>
docker.io/dockerboi99/he_k8s:cpu-latest
docker.io/dockerboi99/he_k8s:gpu-<full-commit-sha>
docker.io/dockerboi99/he_k8s:gpu-latest
```

The CPU image contains only standard `openfhe-python` and starts `python -m
api.app`. It also contains NumPy and Pandas so the same CPU image can be used
as the non-GPU client for an in-cluster comparison Job; the evaluator service
does not import them. The GPU image is built separately from `gpu/Dockerfile`
and contains FIDESlib plus its patched OpenFHE. Neither HE runtime is copied
into the other image.

Both image pushes require masked project CI/CD variables
`DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`. The Docker Hub token needs
read/write permission. CPU builds automatically; the GPU build remains manual.

Run the dependency-free tests with:

```sh
python3 -m unittest discover -s tests -v
```

For a direct CPU check before Docker or K3s, install `requirements.txt` and
run:

```sh
python -m client.direct_openfhe_cpu_test
```

See `docs/direct-openfhe-library.md` for the short direct-library setup and
the six checked operations.

The parameter trade-offs and later optimization checkpoint are recorded in
`docs/he-parameter-optimization-note.md`.

The older `gateway/`, `he_client/`, and related examples remain as historical
trusted plaintext/session trial code. They are tested but are not copied into
the evaluator image.

See `docs/encrypted-evaluator-implementation.md` for the short implementation
and server-test plan.
