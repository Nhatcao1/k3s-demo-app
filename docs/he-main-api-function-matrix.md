# Ma trận hàm HE cho API chính

Tài liệu này mô tả endpoint ciphertext `POST /v1/evaluate`. Đây là API chính,
không phải endpoint demo plaintext và không phải benchmark.

## Ma trận hỗ trợ

`Depth` dưới đây là ngân sách thiết kế CKKS gần đúng, không phải bảo đảm tuyệt
đối. Scaling technique, rescale và cách đánh giá biểu thức có thể thay đổi số
level thực tế.

| Hàm | Tham số riêng của phép toán | Evaluation key | Depth dự kiến | Rotation | FIDESlib GPU |
| --- | --- | --- | ---: | --- | --- |
| `add` | `ciphertext_a`, `ciphertext_b` | Không | 0 | Không | ✅ `EvalAdd` |
| `subtract` | `ciphertext_a`, `ciphertext_b` | Không | 0 | Không | ✅ `EvalSub` native |
| `multiply` | `ciphertext_a`, `ciphertext_b` | Multiplication/relinearization | 1 | Không | ✅ `EvalMult` |
| `square` | `ciphertext_a` | Multiplication/relinearization | 1 | Không | ✅ `EvalSquare` |
| `sum` | `ciphertext_a`, `valid_count` | Rotation/automorphism | 0 | Có | ✅ API `AccumulateSum` |
| `mean` | `ciphertext_a`, `valid_count` | Rotation/automorphism | 1 | Như `sum` | 🟡 `AccumulateSum`, sau đó `EvalMult(1/n)` |
| `weighted_sum` / `dot_product` | `ciphertext_a`, plaintext `weights` | Rotation/automorphism | 1 | Có | 🟡 `EvalMult(ct, pt)` + `AccumulateSum` |
| `variance` | `ciphertext_a`, `valid_count` | Multiplication/relinearization + rotation | 2 | Có | 🟡 Ghép `square`, `sum`, `mean` |
| `covariance` | `ciphertext_a`, `ciphertext_b`, `valid_count` | Multiplication/relinearization + rotation | 2 | Có | 🟡 Ghép `multiply`, `sum`, `mean` |
| `rolling_mean` | `ciphertext_a`, `window_size` | Rotation/automorphism | 1 | Theo cửa sổ | 🟡 `EvalRotate` + `EvalAdd` + nhân scalar |
| `polynomial_score` | `ciphertext_a`, public `coefficients` | Multiplication/relinearization; bootstrap nếu chain không đủ | Phụ thuộc cách tính | Thường không | 🟡 Ghép các primitive CKKS |
| `compare_threshold` | `ciphertext_a`, `threshold` | Scheme-switch/FHEW keys | — | Không | ❌ Không có trong API FIDESlib hiện tại |
| `max` | `ciphertext_a`, `valid_count` | Compare/scheme-switch keys | — | Nhiều vòng | ❌ Không có trong API FIDESlib hiện tại |

Với FIDESlib đang pin, `AccumulateSum` dùng nhóm rotation theo `bStep=4`.
Ví dụ 17 phần tử cần `1, 2, 3, 4, 8, 12, 16`; không chỉ cần
`1, 2, 4, ...`.

## Trạng thái API chính

Đã expose đồng nhất trên CPU và GPU:

- `add`, `subtract`, `multiply`
- `square`
- `sum`, `mean`

CPU gọi OpenFHE-Python trong `backends/openfhe_python.py`. GPU gọi FIDESlib C++
trong `gpu/worker/src/fides_backend.cpp`, qua transport
`gpu/worker/src/main.cpp`. `gpu/api/app.py` chỉ validate HTTP và chuyển các
artifact nhị phân; nó không thực hiện phép HE.

Mọi request đều cần `context` và `ciphertext_a`. GPU cần thêm `public_key` để
load context lên device. Trường `evaluation_keys` chứa đúng một loại key theo
phép toán:

| Phép toán | `ciphertext_b` | `evaluation_keys` | `valid_count` |
| --- | --- | --- | --- |
| `add`, `subtract` | Bắt buộc | Không | Không |
| `multiply` | Bắt buộc | Multiplication | Không |
| `square` | Không | Multiplication | Không |
| `sum`, `mean` | Không | Rotation | Bắt buộc |

Secret key và plaintext đầu vào không được nhận bởi `/v1/evaluate`; client giữ
secret key để giải mã ciphertext kết quả.

## Thứ tự phát triển tiếp

1. Kiểm tra correctness và benchmark sáu hàm hiện tại trên cả CPU/GPU.
2. Thêm `weighted_sum`: cần contract để nhận và serialize plaintext weights.
3. Đổi contract key từ một `evaluation_keys` thành hai bundle riêng
   `multiplication_keys` và `rotation_keys`, rồi mới thêm `variance` và
   `covariance`.
4. Tối ưu multiplicative depth, modulus chain, rescale, relinearization và
   rotation set sau khi toàn bộ hàm CPU/GPU chạy đúng.

Chưa nên thêm `compare_threshold` hoặc `max`: chúng cần một thiết kế
scheme-switch riêng và hiện không có đường tương đương trong FIDESlib GPU.
