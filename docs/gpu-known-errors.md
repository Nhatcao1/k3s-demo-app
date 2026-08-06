# GPU/FIDESlib known errors

Keep this short list updated whenever a GPU CI or K3s failure is diagnosed.

| Symptom | Cause | Required fix |
|---|---|---|
| `cannot bind Plaintext& to an rvalue` | FIDESlib `Encrypt()` requires a named mutable `Plaintext`; standard OpenFHE accepts patterns that look less strict. | Store `MakeCKKSPackedPlaintext()` in a variable, then pass that variable to `Encrypt()`. `tests/test_gpu_source_contract.py` prevents regression. |
| CMake asks to run `git submodule sync` inside the image | Copied nested submodules retain Git metadata that does not resolve in Docker build context. | Build patched OpenFHE with `-DGIT_SUBMOD_AUTO=OFF` after applying the pinned FIDESlib patch. |
| OpenFHE serialization headers are missing | The worker uses patched OpenFHE serialization but its include directories were not exported transitively. | Keep the explicit OpenFHE include directories in `gpu/worker/CMakeLists.txt`. |
| `cuda.h: No such file or directory` | FIDESlib headers require the CUDA driver headers but the worker target did not import CUDA toolkit paths. | Keep `find_package(CUDAToolkit REQUIRED)`, `${CUDAToolkit_INCLUDE_DIRS}`, `CUDA::cudart`, and `CUDA::cuda_driver`. |
| Image builds but fails or has no native code for Tesla T4 | FIDESlib defaults do not include compute capability 7.5. | Keep `FIDESLIB_ARCH=75-real` for the T4 build. |
| New `gpu-latest` exists but K3s runs an old digest | The corporate Docker mirror cached the moving tag. | The GitOps deploy script must resolve Docker Hub `gpu-latest` to an immutable digest before applying it. |
| Replacement GPU Pod stays Pending | One T4 is already held by the old Pod during a rolling update. | Use `Recreate`; delete the old Deployment before applying the replacement. |
| Native C++ succeeds but HTTP returns invalid JSON | FIDESlib prints its GPU banner before the JSON result. | Parse the last valid JSON object from worker stdout. |
| GPU Pod cannot schedule | Runtime, hostname, GPU request, or T4 toleration does not match the cluster. | Keep `runtimeClassName: nvidia`, the confirmed GPU hostname, `nvidia.com/gpu: 1`, and `dedicated=T4:NoSchedule` toleration in GitOps. |

Important architecture rule: never link standard OpenFHE and FIDESlib's patched
OpenFHE into the same image/process. CPU OpenFHE-Python and GPU FIDESlib remain
separate images and runtimes.
