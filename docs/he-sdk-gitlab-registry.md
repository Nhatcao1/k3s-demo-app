# HE SDK private GitLab registry

Public PyPI là đường cài chính. GitLab Package Registry giữ bản private của cả
core và native FIDES component tại:

```text
https://gitlab.com/api/v4/projects/nhatcao99uetwork%2Fk3s-demo-app/packages/pypi/simple
```

Hai tag release kích hoạt hai job private tương ứng:

```text
fides-v0.3.0 -> publish-fides-sdk-gitlab
v0.6.0       -> publish-sdk-gitlab
```

Thứ tự tag giống public release: FIDES trước, core sau. Xem
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

## Cài một lệnh từ private registry

Trên Python 3.12/Linux x86_64:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install \
  --extra-index-url "https://gitlab.com/api/v4/projects/nhatcao99uetwork%2Fk3s-demo-app/packages/pypi/simple" \
  he_looming_sdk==0.6.0
```

Pip lấy core và FIDES component từ GitLab; OpenFHE dependency có thể lấy từ
public PyPI. Không dùng `--no-deps`, nếu không all-in-one installation sẽ bị
vô hiệu hóa.

Kiểm tra:

```sh
python -c 'import he_sdk; print(he_sdk.__version__)'
HE_SDK_BACKEND=openfhe python -m he_sdk.smoke
```

GPU smoke phải chạy ở process mới trên CUDA host:

```sh
HE_SDK_BACKEND=fides python -m he_sdk.smoke
```
