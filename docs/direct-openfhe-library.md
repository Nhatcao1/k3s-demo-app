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

`OpenFHECPU` giữ context, public key và secret key trong cùng process vì đây là
test trực tiếp đáng tin cậy. Nó khác `/v1/evaluate`: service chính chỉ nhận
ciphertext/evaluation keys và không nhận secret key.

Các tham số CKKS hiện vẫn là trial defaults trong `openfhe_cpu/runtime.py`.
Chỉ tối ưu depth, modulus chain, scaling/rescale, relinearization và rotations
sau khi các hàm CPU/GPU đã chạy đúng.
