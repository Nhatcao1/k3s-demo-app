# FIDESlib GPU image

This directory is the isolated GPU build context. It contains FIDESlib and its
matching patched OpenFHE only. It must not install or link the standard
`openfhe-python` runtime used by the repository's CPU image.

GitLab CI builds and pushes `dockerboi99/he_k8s:<commit-sha>`. The job compiles
CUDA code but does not execute GPU tests. `FIDESLIB_ARCH` must match the server
GPU before deployment.

The current worker is a link/build skeleton. Implement `add`, `subtract`,
`multiply`, then `sum`, without changing the CPU image.
