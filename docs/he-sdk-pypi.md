# Publish SDK lên PyPI

Release `0.6.1` cho người dùng hai extras trên cùng package chính:

```sh
python3 -m pip install "he_looming_sdk[cpu]==0.6.1"
python3 -m pip install "he_looming_sdk[gpu]==0.6.1"
```

Mỗi lệnh phải chạy trong một virtual environment riêng. `cpu` kéo
`openfhe==1.5.1.0.24.4`; `gpu` kéo `he-sdk-fides==0.3.2`. Extra GPU không tự
build native code: project vẫn build và publish FIDES wheel riêng.

## GitLab variables

Hai project PyPI dùng hai token bảo vệ:

```text
PYPI_API_TOKEN        token của project he-looming-sdk
FIDES_PYPI_API_TOKEN  token có quyền publish project he-sdk-fides
```

Đặt cả hai là masked, hidden, protected và tắt variable expansion. Bảo vệ tag
patterns `v*` và `fides-v*`; không đưa token vào repository hoặc log.

## Thứ tự release

Version trong tag phải khớp chính xác với `pyproject.toml`. Luôn tag cùng commit
đã kiểm tra trên `origin/main`.

1. Publish native dependency trước:

```sh
git fetch origin main
git tag -a fides-v0.3.2 origin/main -m "Publish he-sdk-fides 0.3.2"
git push origin fides-v0.3.2
```

2. Chờ hai job publish FIDES thành công. Sau đó publish package chính:

```sh
git fetch origin main
git tag -a v0.6.1 origin/main -m "Publish he_looming_sdk 0.6.1"
git push origin v0.6.1
```

Không đẩy hai tag cùng lúc: pip phải tìm thấy `he-sdk-fides==0.3.2` khi người
dùng cài `he_looming_sdk[gpu]==0.6.1`.

## Kiểm tra sau release

Trên Python 3.12/Linux x86_64:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install "he_looming_sdk[cpu]==0.6.1"
python -c 'import he_sdk; print(he_sdk.__version__)'
HE_SDK_BACKEND=openfhe python -m he_sdk.smoke
```

Trên GPU host, tạo environment riêng:

```sh
python3 -m venv .venv-gpu
source .venv-gpu/bin/activate
python -m pip install --upgrade pip
python -m pip install "he_looming_sdk[gpu]==0.6.1"
HE_SDK_BACKEND=fides python -m he_sdk.smoke
```

Các extras cài native component tương ứng nhưng không cài NVIDIA driver hay
tạo GPU cho môi trường.
