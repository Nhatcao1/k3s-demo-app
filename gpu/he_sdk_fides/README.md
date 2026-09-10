# he-sdk-fides

Linux/CUDA backend component installed by `he_looming_sdk`. It binds the repository's
existing `he_gpu::FidesBackend` C++ class and FIDESlib's matching patched
OpenFHE build.

Both native packages may exist in one Python environment, but one interpreter
must select only one backend. Loading stock OpenFHE and FIDESlib's patched
OpenFHE into the same process is rejected by the SDK. This component is built
in GitLab CI or the GPU Docker builder; users install the top-level
`he_looming_sdk` distribution rather than installing this component directly.
