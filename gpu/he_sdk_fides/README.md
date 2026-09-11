# he-sdk-fides

Optional native GPU dependency installed by
`pip install "he_looming_sdk[gpu]==0.6.4"`. The wheel is built and published
separately because it contains the FIDESlib, patched OpenFHE, and CUDA-linked
runtime. Do not install the `cpu` extra in the same environment.

Linux/CUDA backend component selected by the `gpu` extra. It binds the
repository's existing `he_gpu::FidesBackend` C++ class and FIDESlib's matching
patched OpenFHE build.

Loading stock OpenFHE and FIDESlib's patched OpenFHE into the same process is
rejected by the SDK. Keep CPU and GPU extras in separate environments. This
component is built in GitLab CI or the GPU Docker builder; users normally
install it through the top-level `he_looming_sdk[gpu]` extra.
