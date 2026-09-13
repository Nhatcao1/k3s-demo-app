# FIDES GPU notebook image

This work lives only on branch `gpu-notebook-image`. The image contains:

- CUDA build/runtime base;
- FIDESlib and its matching patched OpenFHE;
- the native `he-sdk-fides` Python binding;
- `he_looming_sdk` core;
- JupyterLab;
- `/workspace/gpu_full_session.ipynb`.

GitLab job `build-he-notebook-gpu` builds and pushes both tags to the existing
Docker Hub repository:

```text
docker.io/dockerboi99/he_k8s:notebook-gpu-<short-commit-sha>
docker.io/dockerboi99/he_k8s:notebook-gpu-latest
```

The CI runner compiles the CUDA image but does not execute HE operations. Run
the image on an NVIDIA GPU host with NVIDIA Container Toolkit:

```bash
docker pull docker.io/dockerboi99/he_k8s:notebook-gpu-latest
docker run --rm --gpus all -p 8888:8888 \
  docker.io/dockerboi99/he_k8s:notebook-gpu-latest
```

Open the Jupyter URL printed by the container and run
`gpu_full_session.ipynb`. The notebook does not install packages or compile
native code; it uses the components already present in the image.
