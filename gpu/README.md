# FIDESlib GPU image

This directory is the isolated GPU build context. It contains FIDESlib and its
matching patched OpenFHE only. It must not install or link the standard
`openfhe-python` runtime used by the repository's CPU image.

It also builds the optional `he-sdk-fides` native wheel. The Python binding,
worker executable, and demo executable reuse the same `he_gpu_backend` C++
library. The wheel is kept under `/opt/he-sdk-fides-wheel` and is released only
after the tagged T4 runner equivalence test. See `docs/he-sdk-fides.md`.

On `main`, GitLab CI builds and pushes only
`dockerboi99/he_k8s:gpu-latest`. The job compiles CUDA code but does not execute
GPU tests. `FIDESLIB_ARCH` must match the server GPU before deployment.

Add masked CI/CD variables `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` to the
`k3s-demo-app` GitLab project. The GPU job is skipped until both exist.

The image exposes the same `/v1/evaluate` HTTP shape as the CPU evaluator for
`add`, `subtract`, `multiply`, `square`, `sum`, `mean`, and population
`variance`. Its Python adapter
only validates and stages binary artifacts; all HE operations execute in the
C++ FIDESlib worker.
Because FIDESlib loads GPU evaluation keys using the public key, GPU requests
also include `public_key`. The API advertises this in `/v1/capabilities`.

No secret key is accepted. The benchmark client owns key generation,
encryption, result decryption, and correctness checks. This image contains only
FIDESlib's matching patched OpenFHE and must remain separate from the CPU image.

The transport bridge has dependency-free contract tests, but the CUDA build and
serialized-artifact compatibility still require the manual GitLab build and an
NVIDIA-enabled server run.

## Native plaintext demo endpoint

`POST /v1/demo/evaluate` is the deliberately small GPU correctness demo. It
accepts numeric arrays, then `/src/worker/build/he-gpu-demo` performs context
creation, key generation, encryption, all seven exposed operations, and
decryption entirely in C++ with FIDESlib. Python only carries the HTTP JSON;
it does not import OpenFHE or perform HE work.

Every newly requested main operation must add its matching native
demo operation, direct correctness case, and benchmark case in the same change.
This keeps GPU image checks fast while preserving `/v1/evaluate` as the real
secretless contract.

Example:

```json
{"operation":"sum","values_a":[12,7,8,9]}
```

This is a trusted plaintext demo, not the final secretless boundary. The
existing `/v1/evaluate` encrypted-artifact endpoint remains separate for later
serialization work.

After deploying the GPU image, call the demo endpoint for a tiny correctness
case. No OpenFHE installation is needed on the calling machine:

```sh
curl -sS -X POST http://127.0.0.1:18081/v1/demo/evaluate \
  -H 'Content-Type: application/json' \
  -d '{"operation":"variance","values_a":[1,2,3,4]}'
```

Expected population variance is approximately `1.25`.
