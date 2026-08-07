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
- `sum`, `mean`, `variance` (population variance)

CPU gọi OpenFHE-Python trong `backends/openfhe_python.py`. GPU gọi FIDESlib C++
trong `gpu/worker/src/fides_backend.cpp`, qua transport
`gpu/worker/src/main.cpp`. `gpu/api/app.py` chỉ validate HTTP và chuyển các
artifact nhị phân; nó không thực hiện phép HE.

Mọi request đều cần `context` và `ciphertext_a`. GPU cần thêm `public_key` để
load context lên device. Hàm cũ vẫn nhận trường `evaluation_keys` chứa đúng
một loại key. `variance` cần đồng thời hai loại nên dùng hai trường riêng:

| Phép toán | `ciphertext_b` | Evaluation key | `valid_count` |
| --- | --- | --- | --- |
| `add`, `subtract` | Bắt buộc | Không | Không |
| `multiply` | Bắt buộc | Multiplication | Không |
| `square` | Không | Multiplication | Không |
| `sum`, `mean` | Không | Rotation | Bắt buộc |
| `variance` | Không | `multiplication_keys` + `rotation_keys` | Bắt buộc |

Secret key và plaintext đầu vào không được nhận bởi `/v1/evaluate`; client giữ
secret key để giải mã ciphertext kết quả.

## Quy tắc hoàn thành một function

Từ bây giờ, thêm function nào thì phải triển khai cùng operation đó theo một
vertical slice, không chỉ thêm vào backend chính:

1. Hàm HE trong CPU OpenFHE và GPU FIDESlib nếu library hỗ trợ.
2. Contract ciphertext trong `POST /v1/evaluate`.
3. Contract plaintext cùng tên trong `POST /v1/demo/evaluate`; demo phải thật
   sự keygen, encrypt, evaluate và decrypt bằng HE backend.
4. Unit/contract test và một lệnh gọi trực tiếp nhỏ để kiểm tra image trên K3s.
5. Benchmark case so sánh correctness và timing với Python/Pandas plaintext.

Demo nhận plaintext để kiểm tra nhanh library, CUDA, image và operation. Demo
không thay thế test `/v1/evaluate`, vì API chính mới kiểm tra boundary không
đưa secret key hoặc plaintext vào evaluator.

Trạng thái hiện tại:

| Backend | `/v1/evaluate` | Demo hiện có | Gap cần làm ngay |
| --- | --- | --- | --- |
| CPU | bảy hàm | `/v1/demo/evaluate`: đủ bảy hàm; `/v1/demo/sum`: SUM lớn | benchmark từng hàm ngoài SUM |
| GPU | bảy hàm | `/v1/demo/evaluate`: đủ bảy hàm; `/v1/demo/sum`: SUM lớn | benchmark từng hàm ngoài SUM |

## Thứ tự phát triển tiếp

1. Build hai image và kiểm tra correctness của `square`, `mean`, `variance`
   qua demo CPU/GPU trên K3s.
2. Mở rộng benchmark hiện tại từ SUM sang bảy hàm đã expose.
3. Thêm `weighted_sum` theo đầy đủ quy tắc function ở trên; cần contract để
   nhận và serialize plaintext weights.
4. Thêm `covariance`; dùng cùng contract hai bundle key của `variance`.
5. Tối ưu multiplicative depth, modulus chain, rescale, relinearization và
   rotation set sau khi toàn bộ hàm CPU/GPU chạy đúng.

`compare_threshold` và `max` chưa được expose: OpenFHE CPU có API scheme
switch CKKS/FHEW nhưng service hiện chưa có context/key/serialization contract
cho chúng; FIDESlib đang pin không có API tương đương. `rolling_mean` cũng chưa
được expose vì phải chốt trailing/centered, padding và có cho phép wrap-around
packed-slot hay không. `/v1/capabilities` báo chúng trong `not_implemented`,
không đưa vào `operations`.
