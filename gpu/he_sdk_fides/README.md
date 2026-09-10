# he-sdk-fides

Optional Linux/CUDA backend plugin for `he-sdk`. It binds the repository's
existing `he_gpu::FidesBackend` C++ class and FIDESlib's matching patched
OpenFHE build. It must not be installed in the same environment as the stock
`openfhe` Python wheel.

This package is built in GitLab CI or the GPU Docker builder. A normal laptop
only runs its dependency-free Python contract tests.
