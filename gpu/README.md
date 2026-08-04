# FIDESlib GPU image

This directory is the isolated GPU build context. It contains FIDESlib and its
matching patched OpenFHE only. It must not install or link the standard
`openfhe-python` runtime used by the repository's CPU image.

GitLab CI builds and pushes `dockerboi99/he_k8s:gpu-<commit-sha>` and
`dockerboi99/he_k8s:gpu-latest`. The job compiles CUDA code but does not execute
GPU tests. `FIDESLIB_ARCH` must match the server GPU before deployment.

Add masked CI/CD variables `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` to the
`k3s-demo-app` GitLab project. The GPU job is skipped until both exist.

The image exposes the same `/v1/evaluate` HTTP shape as the CPU evaluator for
`add`, `subtract`, `multiply`, and `sum`. Its Python adapter only validates and
stages binary artifacts; all HE operations execute in the C++ FIDESlib worker.
Because FIDESlib loads GPU evaluation keys using the public key, GPU requests
also include `public_key`. The API advertises this in `/v1/capabilities`.

No secret key is accepted. The benchmark client owns key generation,
encryption, result decryption, and correctness checks. This image contains only
FIDESlib's matching patched OpenFHE and must remain separate from the CPU image.

The transport bridge has dependency-free contract tests, but the CUDA build and
serialized-artifact compatibility still require the manual GitLab build and an
NVIDIA-enabled server run.
