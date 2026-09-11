# HE application for the K3s lab

## Local SDK

The repository also builds the `he_looming_sdk` Python distribution. Its OpenFHE adapter
reuses `openfhe_cpu/runtime.py`, which is the same function layer used by the
CPU HTTP evaluator. Application developers therefore get a different wrapper,
not a second implementation of the HE calculations.

### Install the CPU package

Current prerequisites:

- Linux x86_64;
- Python 3.12 (`>=3.12,<3.13`);
- the GNU OpenMP runtime, provided by the Ubuntu/Debian package `libgomp1`.

On Ubuntu/Debian, install the system prerequisite before the Python package:

```sh
sudo apt-get update
sudo apt-get install -y libgomp1 python3.12-venv

python3.12 -m venv .venv-he
source .venv-he/bin/activate
python -m pip install --upgrade pip
python -m pip install "he_looming_sdk[cpu]==0.6.3"
```

On Google Colab:

```python
!apt-get update -qq
!apt-get install -y libgomp1
!python -m pip install --upgrade pip
!python -m pip install "he_looming_sdk[cpu]==0.6.3"
```

Verify the installation:

```python
import openfhe
import he_sdk

print(he_sdk.__version__)
```

The `[cpu]` extra installs the pinned `openfhe` Python dependency. Do not install
`openfhe` separately. The GPU/FIDES extra is optional and is not part of this
CPU-first installation path.

Run the complete CPU session example:

```sh
python examples/sdk/full_session_showcase.py --backend openfhe
```

### Install the optional GPU package from GitLab

Use a separate Python 3.12/Linux x86_64 environment with an NVIDIA driver and
a supported CUDA GPU. Do not install the `[cpu]` and `[gpu]` extras in the same
environment because FIDESlib uses its own patched OpenFHE runtime.

After the `fides-v0.3.3` pipeline job `publish-fides-sdk-gitlab` succeeds:

```sh
python3.12 -m venv .venv-he-gpu
source .venv-he-gpu/bin/activate
python -m pip install --upgrade pip
python -m pip install \
  --extra-index-url "https://gitlab.com/api/v4/projects/84844502/packages/pypi/simple" \
  "he_looming_sdk[gpu]==0.6.3"
```

Use `--extra-index-url`, not `--index-url`: pip obtains the core package from
public PyPI and the native `he-sdk-fides==0.3.3` wheel from GitLab. If the
GitLab registry is private, authenticate with a read-package deploy token:

```sh
python -m pip install \
  --extra-index-url "https://DEPLOY_USERNAME:DEPLOY_TOKEN@gitlab.com/api/v4/projects/84844502/packages/pypi/simple" \
  "he_looming_sdk[gpu]==0.6.3"
```

Do not commit or paste the real deploy token into a shared notebook.

Run the same session API through FIDES on the GPU:

```sh
python examples/sdk/full_session_showcase.py --backend fides
```

```python
from he_sdk import HESession

with HESession.create(backend="openfhe") as he:
    values = he.encrypt([1.0, 2.0, 3.0, 4.0])
    encrypted_result = he.variance(values)
    result = he.decrypt(encrypted_result)
```

Version 0.4 also supports an SDK-only, secretless filesystem handoff:

```python
# Owner process
owner = HESession.create(backend="openfhe")
encrypted = owner.encrypt([10.0, 20.0, 30.0])
owner.save(encrypted, "./he-workspace", name="input")

# Separate compute process
with HESession.open_workspace("./he-workspace") as compute:
    encrypted = compute.load("./he-workspace", name="input")
    compute.save(compute.sum(encrypted), "./he-workspace", name="sum")
```

The two-kernel tutorial is under `examples/notebooks/`; see
`docs/he-sdk-workspace.md` for the artifact and trust-boundary contract.

GitLab CI builds the wheels and runs native OpenFHE integration tests. The
public `he_looming_sdk` release exposes separate `cpu` and `gpu` extras so one
environment installs only its selected native backend. See
`docs/he-sdk.md`, `docs/he-sdk-fides.md`, and `compatibility/he-sdk-v1.toml`.
The current-vs-target layer boundaries and deliberately smaller remote roadmap
are in `docs/he-sdk-architecture.md`.

Version tags matching `pyproject.toml` publish the wheel to public PyPI and to
this project's private GitLab PyPI registry. See `docs/he-sdk-pypi.md` for
public publishing and `docs/he-sdk-gitlab-registry.md` for the private fallback.

The successful CPU image contains the verified wheel at
`/opt/he-sdk-wheel/he_looming_sdk-*.whl`. The GitOps repository provides
`scripts/sdk/run-smoke.sh cpu-<short-sha>` to install and execute it in a K3s
Job without modifying the server host.

For the first persistent storage trial, `compose.postgres.yaml` runs a separate
PostgreSQL container with a durable named volume. Its initial schema stores SDK
run metadata and encrypted/public artifacts only; it intentionally rejects a
`secret_key` artifact type. See `postgres/README.md`.

This repository now builds one secretless **CPU OpenFHE evaluator**. The first
scope is intentionally small:

- primitives: `add`, `subtract`, `multiply`;
- unary: `square`;
- reductions: `sum`, `mean`, `variance` (population variance).

The API accepts serialized CKKS context, evaluation keys when required, and
ciphertexts. It never accepts plaintext or a secret key and returns only a
result ciphertext.

## CPU and GPU stay separate

```text
k3s-demo-app/Dockerfile              k3s-demo-app/gpu/Dockerfile
standard openfhe-python              FIDESlib + its patched OpenFHE
CPU image/process                    CUDA GPU image/process
```

Install `he_looming_sdk[cpu]` and `he_looming_sdk[gpu]` in separate Python
environments. Never load standard OpenFHE and FIDESlib's patched OpenFHE in
the same Python process. `HESession.create()` rejects changing the native
backend in an interpreter. The deployed CPU/GPU images remain independent
processes.

The small operation list is in `common/operations.py`. The seven explicit
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
POST /v1/demo/evaluate
POST /v1/demo/bgv/evaluate
```

`/v1/demo/bgv/evaluate` is a trusted CPU-only integer multiplication check. It
creates a BGV context, encrypts packed integer vectors, performs `EvalMult` or
`EvalSum`, decrypts, and reports timings. The production-style secretless
`/v1/evaluate` contract remains CKKS; FIDESlib GPU remains CKKS-only.

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

`variance` composes `E[x²] - E[x]²` and therefore needs both key types. It
uses explicit `multiplication_keys` and `rotation_keys` fields instead of the
legacy single `evaluation_keys` field.

For data larger than one CKKS batch, the trusted client encrypts chunks, calls
`sum` for each chunk, then combines the encrypted partial scalars with `add`.
See `docs/he-main-api-function-matrix.md` for the complete function/key table
and the next implementation order.

## GitLab pipeline

Contract tests require no HE installation. On the default branch, GitLab CI
builds and pushes:

```text
docker.io/dockerboi99/he_k8s:cpu-<short-commit-sha>
docker.io/dockerboi99/he_k8s:cpu-latest
docker.io/dockerboi99/he_k8s:gpu-<short-commit-sha>
docker.io/dockerboi99/he_k8s:gpu-latest
```

Deploy the commit tag on cached or mirrored registries. `latest` is only a
convenience alias; it is not a reliable deployment identity because a mirror
may continue serving an older digest for the moving tag.

The CPU image uses standard `openfhe-python` and starts `python -m api.app`.
It also contains NumPy and Pandas so the same CPU image can be used
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
the seven checked operations.

The parameter trade-offs and later optimization checkpoint are recorded in
`docs/he-parameter-optimization-note.md`.

The older `gateway/`, `he_client/`, and related examples remain as historical
trusted plaintext/session trial code. They are tested but are not copied into
the evaluator image.

See `docs/encrypted-evaluator-implementation.md` for the short implementation
and server-test plan.
