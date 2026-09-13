# Publish SDK lên PyPI

Release core `0.6.5` ưu tiên CPU. GPU là component tùy chọn, phát hành độc lập
sau khi core đã ổn định:

```sh
python3 -m pip install "he_looming_sdk[cpu]==0.6.5"
python3 -m pip install "he_looming_sdk[gpu]==0.6.5"
```

Mỗi lệnh phải chạy trong một virtual environment riêng. `cpu` kéo
`openfhe==1.5.1.0.24.4`; `gpu` kéo `he-sdk-fides==0.3.6`. Extra GPU không tự
build native code: project vẫn build và publish FIDES wheel riêng.

## GitLab variables

Core CPU chỉ cần token đầu tiên. FIDES mặc định phát hành lên GitLab Package
Registry; token thứ hai chỉ dùng nếu sau này public PyPI chấp thuận wheel lớn:

```text
PYPI_API_TOKEN        token của project he-looming-sdk
FIDES_PYPI_API_TOKEN  token có quyền publish project he-sdk-fides
```

Đặt cả hai là masked, hidden, protected và tắt variable expansion. Bảo vệ tag
patterns `v*` và `fides-v*`; không đưa token vào repository hoặc log.

## Release CPU trước

Version trong tag phải khớp chính xác với `pyproject.toml`. Core không chờ FIDES
và pipeline core không tải thử package GPU từ public PyPI:

```sh
git fetch origin main
git tag -a v0.6.5 origin/main -m "Publish he_looming_sdk 0.6.5"
git push origin v0.6.5
```

Tag này build wheel core, cài thử chính wheel đó với extra `[cpu]`, import
`openfhe`, rồi publish lên GitLab registry và public PyPI.

Các image notebook, worker, evaluator, Postgres và GPU không chạy trong luồng
release core. Chỉ bật chúng trong một pipeline riêng bằng variable:

```text
ENABLE_OPTIONAL_BUILDS=true
```

## GPU sau, khi cần

```sh
git fetch origin main
git tag -a fides-v0.3.6 origin/main -m "Publish he-sdk-fides 0.3.6"
git push origin fides-v0.3.6
```

GPU build/publish lỗi không ảnh hưởng package CPU đã phát hành. Job GitLab
Registry chạy tự động; job public PyPI là manual/optional vì wheel hiện lớn hơn
giới hạn mặc định của PyPI.

## Kiểm tra sau release

Trên Python 3.12/Linux x86_64:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install "he_looming_sdk[cpu]==0.6.5"
python -c 'import he_sdk; print(he_sdk.__version__)'
HE_SDK_BACKEND=openfhe python -m he_sdk.smoke
```

Trên GPU host, tạo environment riêng:

```sh
python3 -m venv .venv-gpu
source .venv-gpu/bin/activate
python -m pip install --upgrade pip
python -m pip install \
  --extra-index-url "https://gitlab.com/api/v4/projects/nhatcao99uetwork%2Fk3s-demo-app/packages/pypi/simple" \
  "he_looming_sdk[gpu]==0.6.5"
HE_SDK_BACKEND=fides python -m he_sdk.smoke
```

Các extras cài native component tương ứng nhưng không cài NVIDIA driver hay
tạo GPU cho môi trường.
