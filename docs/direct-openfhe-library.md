# Chạy trực tiếp OpenFHE-Python CPU

Đây là cách kiểm tra function layer trực tiếp, không qua Docker, HTTP, K3s hay
benchmark. Máy chạy lệnh phải cài được `openfhe-python`.

## Cài và chạy

Từ thư mục `k3s-demo-app`:

```sh
python3 -m venv .venv-openfhe
source .venv-openfhe/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
python3 -m client.direct_openfhe_cpu_test
```

Script kiểm tra bảy hàm bằng dữ liệu nhỏ rồi decrypt để so sánh kết quả:

```text
add, subtract, multiply, square, sum, mean, variance
```

## Code đi qua đâu

```text
client/direct_openfhe_cpu_test.py
  -> OpenFHECPU trong openfhe_cpu/runtime.py
  -> OpenFHE-Python
  -> encrypt -> evaluate -> decrypt -> kiểm tra sai số
```

Mỗi case tạo `OpenFHECPU("<operation>")`. Class chọn profile của function trước
khi tạo context, public key, secret key và ciphertext. Các context khác profile
không được trộn ciphertext hay evaluation key với nhau.

`OpenFHECPU` giữ key trong cùng process vì đây là test trực tiếp đáng tin cậy.
Nó khác `/v1/evaluate`: service chính chỉ nhận ciphertext/evaluation keys và
không nhận secret key.

Profile CKKS hiện vẫn là correctness-first trial config trong
`openfhe_cpu/runtime.py`. Xem `docs/he-parameter-optimization-note.md` để biết
giá trị của từng function và giới hạn khi ghép nhiều function thành workflow.
