# FIDES backend trong package SDK

`he_looming_sdk==0.6.5` cung cấp extra GPU, nhưng native FIDES vẫn là một
distribution riêng do CI của project build:

```sh
python3 -m pip install \
  --extra-index-url "https://gitlab.com/api/v4/projects/84844502/packages/pypi/simple" \
  "he_looming_sdk[gpu]==0.6.5"
```

Pip cài hai distribution sau trong GPU environment:

```text
he_looming_sdk==0.6.5
he-sdk-fides==0.3.5
```

`he-sdk-fides` là native wheel Python 3.12/Linux x86_64. Wheel chứa Python
adapter và extension C++ liên kết FIDESlib, patched OpenFHE và CUDA runtime cần
thiết. NVIDIA driver và GPU phù hợp vẫn do môi trường chạy cung cấp.

## Luồng code

```mermaid
flowchart LR
    APP["Python application"] --> SESSION["HESession.create()"]
    SESSION -->|openfhe| CPU["OpenFHEBackend"]
    SESSION -->|fides| GPU["he_sdk_fides.FidesBackend"]
    GPU --> BINDING["pybind11 _native"]
    BINDING --> CPP["gpu/worker/src/fides_backend.cpp"]
    CPP --> FIDES["FIDESlib + patched OpenFHE + CUDA"]
```

Không cài extra `cpu` trong GPU environment. Stock OpenFHE và patched OpenFHE
không an toàn khi được load cùng process. Dùng hai virtual environment riêng:

```sh
python3 -m pip install "he_looming_sdk[cpu]==0.6.5"
python3 examples/sdk/full_session_showcase.py

python3 -m pip install \
  --extra-index-url "https://gitlab.com/api/v4/projects/84844502/packages/pypi/simple" \
  "he_looming_sdk[gpu]==0.6.5"
python3 examples/sdk/full_session_showcase.py
```

SDK không tự fallback GPU sang CPU.

## Build và publish

`build-fides-sdk-wheel` dùng CUDA builder, build native extension rồi chạy
`auditwheel repair` để tạo wheel `manylinux_2_35_x86_64`, tương thích ABI với
Ubuntu 22.04/Google Colab. GitLab runner chỉ
kiểm tra compile/package; kiểm tra runtime vẫn chạy trên T4.

Core CPU được release độc lập trước. Extra GPU chỉ yêu cầu pip tải plugin; nó
không tự build hoặc publish native wheel.

FIDES mặc định publish lên GitLab Package Registry bằng `CI_JOB_TOKEN`. Chỉ tạo
variable sau nếu chủ động chạy job public PyPI dạng manual:

```text
FIDES_PYPI_API_TOKEN = token PyPI có quyền tạo/publish project he-sdk-fides
```

Sau khi pipeline `main` thành công, publish theo thứ tự:

```sh
git fetch origin main
git tag -a fides-v0.3.5 origin/main -m "Publish he-sdk-fides 0.3.5"
git push origin fides-v0.3.5
```

Tag GPU không chặn hoặc thay đổi core `v0.6.5`; xem `he-sdk-pypi.md`.

## Giới hạn hiện tại

- Python 3.12, Linux x86_64, glibc 2.35 hoặc mới hơn;
- CUDA build target `75-real` cho NVIDIA T4;
- không tự cài NVIDIA driver;
- wheel FIDES vẫn phải do project build và publish riêng;
- không load CPU OpenFHE và GPU FIDES native backend trong cùng process;
- GPU runtime acceptance vẫn phải chạy trên GPU server.
