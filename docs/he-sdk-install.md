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
| GPU | `he_looming_sdk[gpu]==0.6.5` + `he-sdk-fides==0.3.6` | Chưa dùng được: `he-sdk-fides` chưa có trong GitLab Package Registry |

Không dùng lệnh GPU ở môi trường người dùng cho tới khi cả hai package GPU
được kiểm tra thấy trong registry.

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

Yêu cầu runtime:

- Linux x86_64 và Python 3.12;
- NVIDIA GPU, driver và CUDA runtime tương thích;
- CPU và GPU nằm trong hai virtual environment riêng;
- không cài stock OpenFHE CPU cùng FIDESlib patched OpenFHE trong một process.

GitLab PyPI index:

```text
https://gitlab.com/api/v4/projects/84844502/packages/pypi/simple
```

Sau khi pipeline đã publish `he-sdk-fides==0.3.6` và core `0.6.5`, lệnh cài
đặt mục tiêu là:

```bash
python3.12 -m venv .venv-he-gpu
source .venv-he-gpu/bin/activate
python -m pip install --upgrade pip
python -m pip install \
  --extra-index-url "https://gitlab.com/api/v4/projects/84844502/packages/pypi/simple" \
  "he_looming_sdk[gpu]==0.6.5"
```

Không dùng `--no-deps`: pip phải tải thêm native package `he-sdk-fides`.
Không cần clone repository và không cần chạy CMake trên máy người dùng.

Kiểm tra GPU sau khi package đã publish:

```bash
python - <<'PY'
from he_sdk import HESession, __version__

with HESession.create(device="gpu") as session:
    encrypted = session.encrypt([1.0, 2.0, 3.0])
    result = session.decrypt(session.sum(encrypted))
    print("SDK:", __version__)
    print("backend:", session.capabilities.backend)
    print("sum:", result)
PY
```

Trước khi thử cài, có thể xác nhận native GPU wheel đã xuất hiện:

```bash
python -m pip index versions he-sdk-fides \
  --index-url "https://gitlab.com/api/v4/projects/84844502/packages/pypi/simple"
```

Nếu lệnh trả về `No matching distribution found`, GPU SDK vẫn chưa được phát
hành và `pip install he_looming_sdk[gpu]` chắc chắn sẽ thất bại.

## Chọn backend trong code

```python
from he_sdk import HESession

cpu_session = HESession.create(device="cpu")  # CPU environment
gpu_session = HESession.create(device="gpu")  # GPU environment
```

Không tạo hai session trên trong cùng một Python environment. Bình thường có
thể gọi `HESession.create()` không truyền `device`; SDK sẽ chọn component duy
nhất đã được cài trong environment.
