# Hướng dẫn nhanh `he_looming_sdk`

`he_looming_sdk` là Python package cung cấp API đơn giản để thử nghiệm mã hóa
đồng hình CKKS. Tên package dùng khi cài đặt là `he_looming_sdk`, còn tên module
dùng trong Python là `he_sdk`.

SDK hiện hỗ trợ:

- Mã hóa và giải mã vector số thực.
- `add`, `subtract`, `multiply`, `square` trên ciphertext.
- `sum`, `mean`, `variance` trên ciphertext.
- Lưu và đọc ciphertext bằng SDK workspace.
- Chỉ cấp quyền giải mã kết quả tổng hợp cho analyst.

Backend ổn định hiện tại là OpenFHE chạy CPU. FIDESlib/GPU vẫn là backend tùy
chọn đang chờ kiểm thử trên GPU server; SDK không tự động chuyển CPU/GPU.

## 1. Cài đặt

Khuyến nghị tạo virtual environment riêng:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install "he_looming_sdk[openfhe]==0.4.1"
```

Kiểm tra package:

```bash
python -c "import he_sdk; print(he_sdk.__version__)"
```

Kết quả mong đợi:

```text
0.4.1
```

OpenFHE wheel được dùng chủ yếu trên Linux. Nếu máy cá nhân không cài được
extra `openfhe`, hãy chạy phần HE trên Linux server, Docker image hoặc GitLab
runner. Không cần build OpenFHE trên laptop chỉ để sử dụng SDK.

## 2. Ví dụ cơ bản

```python
from he_sdk import HESession


def show(name, value):
    """Làm tròn output để ví dụ CKKS dễ đọc."""
    if isinstance(value, list):
        value = [round(item, 4) for item in value]
    else:
        value = round(value, 4)
    print(f"{name}: {value}")


with HESession.create(backend="openfhe") as he:
    # Plaintext chỉ xuất hiện tại trusted client này.
    encrypted_a = he.encrypt([1.0, 2.0, 3.0])
    encrypted_b = he.encrypt([10.0, 20.0, 30.0])

    print("encrypted_a:", encrypted_a)

    show("add", he.decrypt(he.add(encrypted_a, encrypted_b)))
    show("subtract", he.decrypt(he.subtract(encrypted_a, encrypted_b)))
    show("multiply", he.decrypt(he.multiply(encrypted_a, encrypted_b)))
    show("square", he.decrypt(he.square(encrypted_a)))
    show("sum", he.decrypt(he.sum(encrypted_a)))
    show("mean", he.decrypt(he.mean(encrypted_a)))
    show("variance", he.decrypt(he.variance(encrypted_a)))
```

Output gần đúng:

```text
encrypted_a: EncryptedVector(backend='openfhe', shape=(3,), ...)
add: [11.0, 22.0, 33.0]
subtract: [-9.0, -18.0, -27.0]
multiply: [10.0, 40.0, 90.0]
square: [1.0, 4.0, 9.0]
sum: 6.0
mean: 2.0
variance: 0.6667
```

CKKS là approximate homomorphic encryption. Kết quả thực tế có thể là
`5.9999` thay vì đúng tuyệt đối `6.0`; ứng dụng cần so sánh bằng tolerance.

## 3. Các hàm hiện có

| Hàm | Input | Output sau khi decrypt | Ghi chú |
|---|---|---|---|
| `encrypt(values)` | Một sequence số thực | `EncryptedVector` | Từ 1 đến 8192 phần tử |
| `decrypt(value)` | `EncryptedVector` hoặc `EncryptedScalar` | `list[float]` hoặc `float` | Chỉ session có secret key dùng được |
| `add(a, b)` | Hai vector cùng shape | Cộng theo từng phần tử | Không cộng plaintext trực tiếp |
| `subtract(a, b)` | Hai vector cùng shape | Trừ theo từng phần tử | `a - b` |
| `multiply(a, b)` | Hai vector cùng shape | Nhân theo từng phần tử | Tiêu tốn một multiplication level |
| `square(a)` | Một vector | Bình phương từng phần tử | Tiêu tốn một multiplication level |
| `sum(a)` | Một vector | Một scalar | Tổng các phần tử hợp lệ |
| `mean(a)` | Một vector | Một scalar | Trung bình cộng |
| `variance(a)` | Một vector | Một scalar | Population variance, chia cho `N` |

Input mặc định phải là số hữu hạn trong khoảng `[-40000, 40000]`. `add`,
`subtract` và `multiply` yêu cầu hai ciphertext có cùng context, key bundle,
packing layout và shape. SDK sẽ báo lỗi thay vì âm thầm trộn ciphertext không
tương thích.

SDK hiện xử lý tối đa một CKKS batch, mặc định 8192 giá trị. Automatic chunking
chưa thuộc stable API. Với dữ liệu lớn hơn, client phải chia chunk; đặc biệt
`mean` và `variance` toàn cục cần tổng hợp theo count, không được lấy trung bình
đơn giản của các kết quả chunk.

## 4. Ciphertext và secret key nằm ở đâu?

`HESession.create()` tạo một CKKS context và key pair:

```python
owner = HESession.create(backend="openfhe")
encrypted = owner.encrypt([10.0, 20.0, 30.0])
result = owner.sum(encrypted)
print(owner.decrypt(result))
owner.close()
```

`EncryptedVector` và `EncryptedScalar` là SDK wrapper. Application không cần
làm việc trực tiếp với object riêng của OpenFHE.

Secret key hiện chỉ nằm trong owner session và không được SDK ghi vào
workspace. Khi owner session bị đóng hoặc mất, ciphertext đã lưu không thể
được owner giải mã lại trong phiên bản hiện tại. Việc lưu secret key lâu dài
cần một keystore hoặc HSM riêng, không dùng chung workspace với compute.

## 5. Lưu ciphertext bằng SDK

Lưu và đọc lại trong một compatible session:

```python
from pathlib import Path
from he_sdk import HESession

workspace = Path("./he-workspace")
owner = HESession.create(backend="openfhe")

encrypted = owner.encrypt([10.0, 20.0, 30.0])
owner.save(encrypted, workspace, name="input")

loaded = owner.load(workspace, name="input")
print(owner.decrypt(loaded))

owner.close()
```

Workspace cơ bản:

```text
he-workspace/
├── manifest.json
├── material/
│   ├── context.bin
│   ├── public-key.bin
│   ├── multiplication-keys.bin
│   └── rotation-keys.bin
└── ciphertexts/
    └── input.bin
```

`manifest.json` chứa metadata và checksum. Workspace không chứa plaintext hoặc
secret key, nhưng có thể lộ metadata như backend, operation name, shape và số
phần tử.

SDK chỉ yêu cầu một filesystem path:

- Local development có thể dùng thư mục tạm hoặc local disk.
- Kubernetes có thể mount path đó từ PVC.
- Object storage có thể được dùng nếu deployment tải artifact xuống filesystem
  trước khi gọi SDK.
- PostgreSQL không bắt buộc. Nếu dùng, nên ưu tiên lưu run metadata, artifact
  URI, checksum, recipient ID và audit state. Việc lưu ciphertext blob trực
  tiếp là lựa chọn của deployment, không phải yêu cầu của SDK.

Không lưu plaintext, owner secret key, analyst secret key hoặc khóa chuyển đổi
kết quả trong PostgreSQL, PVC dùng chung hay object storage công khai.

## 6. Compute không có secret key

Owner có thể xuất một secretless workspace cho process hoặc notebook khác:

```python
# Compute process riêng
from he_sdk import HESession

with HESession.open_workspace("./he-workspace") as compute:
    encrypted = compute.load("./he-workspace", name="input")
    encrypted_sum = compute.sum(encrypted)
    compute.save(encrypted_sum, "./he-workspace", name="sum")

    # compute.decrypt(encrypted) sẽ báo SecretKeyUnavailableError.
```

Owner session còn sống có thể đọc và giải mã kết quả:

```python
encrypted_sum = owner.load("./he-workspace", name="sum")
print(owner.decrypt(encrypted_sum))
```

Với OpenFHE binding hiện tại, owner và compute nên chạy ở hai process hoặc hai
notebook kernel riêng để cô lập global context/key state.

## 7. Analyst chỉ xem kết quả được release

Ví dụ nhỏ dưới đây tạo analyst key khác owner key, rồi chỉ release kết quả
`sum`:

```python
from he_sdk import HESession, ResultReleaseError

with HESession.create(backend="openfhe") as owner:
    encrypted_input = owner.encrypt([10.0, 20.0, 30.0])
    encrypted_sum = owner.sum(encrypted_input)

    analyst = owner.create_result_recipient()
    released_sum = owner.reencrypt_for_recipient(
        encrypted_sum,
        analyst.public_key,
    )

    print(analyst.decrypt(released_sum))  # xấp xỉ 60.0

    try:
        analyst.decrypt(encrypted_input)
    except ResultReleaseError:
        print("PASS: analyst không thể dùng API để decrypt input")
```

Chỉ `sum`, `mean` và `variance` dạng `EncryptedScalar` được SDK cho phép
release. Khóa chuyển đổi được tạo và sử dụng bên trong
`reencrypt_for_recipient()`; SDK không trả khóa này ra ngoài.

Trong production, analyst key generation, owner release authority và compute
worker phải là các trust boundary riêng. Cơ chế release kết quả trong `0.4.1`
dùng OpenFHE `INDCPA`; cần review security profile, authorization, minimum
cohort, rate limit và audit trước khi dùng với dữ liệu thật.

## 8. Khi dùng trong notebook hoặc server

- Sau khi upgrade package, restart Jupyter kernel để tránh giữ class cũ trong
  memory.
- Kiểm tra version trong đúng kernel:

  ```python
  import he_sdk
  print(he_sdk.__version__)
  ```

- Nếu gặp `AttributeError` sau khi upgrade, kiểm tra kernel đang dùng đúng
  virtual environment.
- Nếu OpenFHE không cài được trên laptop, chỉ edit code local rồi để CI/Linux
  server cài wheel và chạy native integration test.

Các notebook demo đầy đủ nằm cùng thư mục `examples/sdk/`. Phần Docker,
PostgreSQL, PVC, Kubernetes và GitOps là deployment concern; application dùng
HE SDK không cần các thành phần đó để chạy local in-memory example.
