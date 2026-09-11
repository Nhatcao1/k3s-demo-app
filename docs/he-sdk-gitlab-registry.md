# HE SDK private GitLab registry

Public PyPI là đường cài chính. GitLab Package Registry giữ bản private của cả
core và native FIDES component tại:

```text
https://gitlab.com/api/v4/projects/nhatcao99uetwork%2Fk3s-demo-app/packages/pypi/simple
```

Hai tag release kích hoạt hai job private tương ứng:

```text
v0.6.3       -> publish-sdk-gitlab
fides-v0.3.3 -> publish-fides-sdk-gitlab
```

Core CPU được release trước; GPU là release tùy chọn riêng. Xem
`he-sdk-pypi.md`.

## Deploy token chỉ đọc

Trên GitLab mở **Settings > Repository > Deploy tokens**, tạo token có scope
`read_package_registry`, rồi lưu username/token vào `~/.netrc` của service
account:

```text
machine gitlab.com
login gitlab+deploy-token-123456
password REPLACE_WITH_DEPLOY_TOKEN
```

```sh
chmod 600 ~/.netrc
```

Không commit `.netrc` hoặc token.

## Cài từ private registry

GPU environment trên Python 3.12/Linux x86_64:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install \
  --extra-index-url "https://gitlab.com/api/v4/projects/nhatcao99uetwork%2Fk3s-demo-app/packages/pypi/simple" \
  "he_looming_sdk[gpu]==0.6.3"
```

Pip lấy core và FIDES component từ GitLab. Tạo CPU environment riêng; cùng
index private nhưng chỉ cài OpenFHE extra:

```sh
python3 -m venv .venv-cpu
source .venv-cpu/bin/activate
python -m pip install --upgrade pip
python -m pip install \
  --extra-index-url "https://gitlab.com/api/v4/projects/nhatcao99uetwork%2Fk3s-demo-app/packages/pypi/simple" \
  "he_looming_sdk[cpu]==0.6.3"
```

Không dùng `--no-deps`, nếu không dependency của extra sẽ không được cài.

Kiểm tra trong CPU environment:

```sh
python -c 'import he_sdk; print(he_sdk.__version__)'
HE_SDK_BACKEND=openfhe python -m he_sdk.smoke
```

GPU smoke chạy trong GPU environment trên CUDA host:

```sh
HE_SDK_BACKEND=fides python -m he_sdk.smoke
```
