# Cài HE SDK bằng pip

Đây là hướng dẫn cài đặt chính thức cho người dùng SDK. Đường cài hoàn chỉnh
phải dùng `pip install`; `git clone` và tự build FIDESlib chỉ là cách chẩn đoán
dành cho người phát triển, không được xem là một bản phát hành SDK.

Tên distribution dùng với pip là `he_looming_sdk`. Tên module import trong
Python là `he_sdk`.

## Trạng thái package

| Backend | Package | Trạng thái |
|---|---|---|
| CPU | `he_looming_sdk[cpu]==0.6.4` | Đã publish trên public PyPI |
| GPU | `he_looming_sdk[gpu]==0.6.4` + `he-sdk-fides==0.3.3` | Đã publish; cần Linux/Python/CUDA host đúng yêu cầu bên dưới |

## CPU — OpenFHE

Yêu cầu hiện tại:

- Linux x86_64;
- Python 3.12;
- Ubuntu 24.04 hoặc môi trường có C++ runtime tương thích với OpenFHE wheel;
- `libgomp1`.

```bash
sudo apt-get update
sudo apt-get install -y libgomp1 python3.12-venv

python3.12 -m venv .venv-he-cpu
source .venv-he-cpu/bin/activate
python -m pip install --upgrade pip
python -m pip install "he_looming_sdk[cpu]==0.6.4"
```

Kiểm tra:

```bash
python - <<'PY'
from he_sdk import HESession, __version__

with HESession.create(device="cpu") as session:
    encrypted = session.encrypt([1.0, 2.0, 3.0])
    result = session.decrypt(session.sum(encrypted))
    print("SDK:", __version__)
    print("backend:", session.capabilities.backend)
    print("sum:", result)
PY
```

Kết quả `sum` xấp xỉ `6.0`. CKKS có sai số số thực nhỏ.

OpenFHE wheel hiện yêu cầu phiên bản `libstdc++` mới hơn Google Colab cung cấp,
vì vậy không dùng Colab để kiểm tra CPU package này.

## GPU — FIDESlib

### Phạm vi hỗ trợ hiện tại

GPU package đã publish nhưng có phạm vi hẹp hơn CPU:

- Linux x86_64;
- đúng CPython 3.12 (`>=3.12,<3.13`);
- glibc từ 2.39 vì wheel hiện có tag
  `cp312-cp312-manylinux_2_39_x86_64`;
- NVIDIA GPU và host driver cung cấp `libcuda.so.1`;
- native target đã build là `sm_75` cho NVIDIA T4;
- CPU và GPU nằm trong hai virtual environment riêng;
- không cài stock OpenFHE CPU cùng FIDESlib patched OpenFHE trong một process.

Ubuntu 24.04 có glibc 2.39 và là môi trường phù hợp nhất hiện tại. Google
Colab hosted thường có userspace cũ hơn tag của wheel nên chưa được xem là
đường cài GPU hỗ trợ. CUDA compiler và CMake chỉ cần trong pipeline đóng gói,
không phải trên máy người dùng wheel.

### 1. Kiểm tra host trước khi cài

```bash
uname -m
python3.12 --version
ldd --version | head -n 1
nvidia-smi
```

Kết quả tối thiểu mong đợi:

```text
x86_64
Python 3.12.x
glibc 2.39 hoặc mới hơn
nvidia-smi nhìn thấy NVIDIA GPU và driver
```

Với target T4 hiện tại, kiểm tra model/compute capability:

```bash
nvidia-smi --query-gpu=name,compute_cap,driver_version --format=csv,noheader
```

Kết quả T4 phải có compute capability `7.5`. GPU architecture khác cần build
wheel riêng hoặc acceptance test riêng trước khi công bố hỗ trợ.

### 2. Kiểm tra package registry

GitLab PyPI index:

```text
https://gitlab.com/api/v4/projects/84844502/packages/pypi/simple
```

Xác nhận wheel native đã tồn tại:

```bash
python3.12 -m pip index versions he-sdk-fides \
  --index-url "https://gitlab.com/api/v4/projects/84844502/packages/pypi/simple"
```

Registry hiện phải trả về `0.3.3`. Project registry hiện public nên thông
thường không cần token. Nếu nhận `401/403`, dùng GitLab deploy token có scope
`read_package_registry` trong `~/.netrc`; không nhúng token vào notebook hoặc
command history:

```text
machine gitlab.com
login gitlab+deploy-token-REPLACE
password REPLACE_WITH_TOKEN
```

```bash
chmod 600 ~/.netrc
```

### 3. Tạo GPU environment và cài package

```bash
python3.12 -m venv .venv-he-gpu
source .venv-he-gpu/bin/activate
python -m pip install --upgrade pip

# Không cài extra [cpu] trong environment này.
python -m pip install \
  --extra-index-url "https://gitlab.com/api/v4/projects/84844502/packages/pypi/simple" \
  "he_looming_sdk[gpu]==0.6.4"
```

Không dùng `--no-deps`: pip phải tải native package `he-sdk-fides`. Không cần
clone repository và không cần chạy CMake trên máy người dùng.

Xác nhận đúng hai distribution đã cài:

```bash
python -m pip show he_looming_sdk he-sdk-fides
python -m pip check
```

`he_looming_sdk==0.6.4` pin GPU dependency về `he-sdk-fides==0.3.3`; không tự
nâng riêng một package nếu chưa kiểm tra compatibility.

### 4. Kiểm tra import và native runtime

Import không tạo HE session nhưng xác nhận wheel/native extension load được:

```bash
python - <<'PY'
import he_sdk
import he_sdk_fides

print("he_sdk:", he_sdk.__version__)
print("he_sdk_fides:", he_sdk_fides.__version__)
PY
```

Nếu lỗi nhắc `libcuda.so.1`, host driver hoặc NVIDIA Container Toolkit chưa
được expose cho process/container. Cài lại Python package không sửa được lỗi
driver này.

### 5. Chạy GPU smoke test

```bash
python - <<'PY'
from he_sdk import HESession, __version__

with HESession.create(device="gpu") as session:
    values = [1.0, 2.0, 3.0, 4.0]
    encrypted = session.encrypt(values)
    encrypted_sum = session.sum(encrypted)
    result = session.decrypt(encrypted_sum)

    print("SDK:", __version__)
    print("backend:", session.capabilities.backend)
    print("input:", values)
    print("encrypted:", encrypted)
    print("expected sum:", 10.0)
    print("sum:", result)
PY
```

Kết quả CKKS phải xấp xỉ `10.0`, không yêu cầu bằng tuyệt đối. Backend phải in
`fides` hoặc capability name tương ứng của FIDES adapter.

### 6. Chạy bằng prebuilt GPU notebook image

Nếu không muốn cài wheel trực tiếp trên host, nhánh `gpu-notebook-image` định
nghĩa image chứa sẵn FIDESlib, patched OpenFHE, binding, SDK và JupyterLab:

```bash
docker pull docker.io/dockerboi99/he_k8s:notebook-gpu-latest
docker run --rm --gpus all -p 8888:8888 \
  docker.io/dockerboi99/he_k8s:notebook-gpu-latest
```

Chỉ dùng lệnh này sau khi job `build-he-notebook-gpu` đã push tag. Docker host
phải cài NVIDIA Container Toolkit và lệnh sau phải chạy được:

```bash
docker run --rm --gpus all nvidia/cuda:12.9.1-base-ubuntu24.04 nvidia-smi
```

Google Colab hosted không chạy trực tiếp custom Docker image; image này dành
cho GPU server, workstation hoặc K3s GPU node.

### 7. Lỗi cài GPU thường gặp

| Lỗi | Nguyên nhân | Xử lý |
|---|---|---|
| `No matching distribution found` | Không dùng CPython 3.12, không phải Linux x86_64 hoặc glibc quá cũ | Kiểm tra Python/platform/glibc; không source-build tại consumer |
| `libcuda.so.1: cannot open` | NVIDIA driver/device chưa expose | Sửa driver hoặc NVIDIA Container Toolkit |
| `BackendUnavailableError` | Native extension load thất bại hoặc cài nhầm extra | Kiểm tra `pip check`, import `he_sdk_fides`, dùng GPU venv riêng |
| `no kernel image is available` | GPU architecture không có trong wheel | Dùng T4/sm_75 hoặc build/release wheel cho architecture đó |
| `Both CPU and GPU native backends are installed` | Cài cả `[cpu]` và `[gpu]` cùng environment | Tạo hai virtual environment riêng |
| GPU session tạo được nhưng operation lỗi | Runtime/CUDA/FIDES compatibility chưa đạt | Chạy `nvidia-smi`, smoke test nhỏ và xem native error trước benchmark |

## Chọn backend trong code

```python
from he_sdk import HESession

cpu_session = HESession.create(device="cpu")  # CPU environment
gpu_session = HESession.create(device="gpu")  # GPU environment
```

Không tạo hai session trên trong cùng một Python environment. Bình thường có
thể gọi `HESession.create()` không truyền `device`; SDK sẽ chọn component duy
nhất đã được cài trong environment.
