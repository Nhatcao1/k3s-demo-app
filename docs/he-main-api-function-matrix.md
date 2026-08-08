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
| `matrix_vector_multiply` | PT/CT matrix, encrypted vector, public dimensions/layout | Phụ thuộc PT×CT hay CT×CT + rotation | Phụ thuộc layout | Có | 🟡 GPU-first; phải chốt packing/tiling trước |
| `matrix_multiply` | PT/CT matrix A, CT matrix B, public dimensions/layout | Multiplication/relinearization + rotation | Phụ thuộc layout | Nhiều | 🟡 GPU-first experimental |
| `linear_layer` | encrypted input, plaintext weights và bias | Rotation; multiplication key nếu dùng CT weights | Ít nhất 1 | Có | 🟡 GPU-first trên `matrix_vector_multiply` |
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

## Lộ trình function tiếp theo

`encrypt` và `decrypt` thuộc trusted client, không đưa plaintext hoặc secret
key vào evaluator. Context được chọn cho toàn calculation graph; nhiều
function trên cùng ciphertext phải dùng cùng context và union evaluation keys.
Trước mắt client có thể gửi lại cùng serialized artifacts cho mỗi request;
`context_id`/`ciphertext_id` persistence là bước riêng, không chặn function
benchmark.

| Function | CPU OpenFHE | GPU FIDESlib | Ưu tiên | Điều phải chốt trước |
| --- | --- | --- | ---: | --- |
| `encrypt` / `decrypt` | Client implementation + correctness reference | Demo/native client implementation | 0 | Cùng context với toàn workload; secret key không vào evaluator |
| `add`, `subtract`, `multiply`, `square`, `sum`, `mean`, `variance` | Đã expose | Đã expose | 0 | Sửa accuracy hiện tại và ghi lại parameter baseline |
| `weighted_sum` | Implement đầy đủ | Implement đầy đủ | 1 | Plaintext-weight contract, length và packed-slot layout |
| `rolling_mean` | Implement đầy đủ | Implement đầy đủ | 2 | Trailing hay centered, padding, output length, không wrap slot ngoài ý muốn |
| `polynomial_score` | Implement đầy đủ | Implement đầy đủ | 3 | Coefficient order, degree limit, input range và evaluation strategy |
| `matrix_vector_multiply` | Reference + small correctness test | GPU-first implementation/benchmark | 4 | PT hay CT matrix, row/diagonal packing, dimensions và tiling |
| `linear_layer` | Reference + small correctness test | GPU-first implementation/benchmark | 5 | Dùng contract/layout của matrix-vector; plaintext weights/bias trước |
| `matrix_multiply` | Chỉ reference nhỏ lúc đầu | GPU-first experimental | 6 | PT×CT trước CT×CT; matrix layout, padding, tiling và output layout |

`matrix_vector_multiply`, `linear_layer`, và `matrix_multiply` không bắt buộc
chạy CPU ở kích thước lớn. CPU implementation nhỏ dùng làm oracle correctness;
GPU mới là target performance chính. Không tuyên bố FIDESlib support trước khi
prototype native C++ gọi được trên T4.

Mỗi function vẫn phải hoàn thành đủ vertical slice:

1. Backend CPU và GPU theo scope trong bảng.
2. Ciphertext contract `/v1/evaluate` và plaintext `/v1/demo/evaluate` để test
   nhanh.
3. Capability metadata, validation, unit/contract test và K3s command.
4. Deterministic data generator, plaintext expected result và benchmark.
5. Accuracy report trước, sau đó mới dùng latency để so sánh.

## Dữ liệu và benchmark cần thêm

Không dùng một generator chung giả vờ phù hợp cho mọi workload. Mỗi nhóm cần
generator nhỏ, deterministic bằng `--seed`, lưu input dưới `data/` của GitOps
(đã git-ignore) và ghi metadata cạnh result.

| Nhóm | Generator tối thiểu | Tham số benchmark chính | Baseline |
| --- | --- | --- | --- |
| `weighted_sum` | values + weights | count, value/weight range, sparsity | Python/NumPy dot product |
| `rolling_mean` | time series có trend, noise và edge cases | count, window, padding policy | Pandas rolling mean |
| `polynomial_score` | x trong range kiểm soát + coefficients cố định | count, degree, x range | NumPy polynomial evaluation |
| Matrix-vector | matrix + vector, dense trước | rows, columns, PT/CT matrix, packing layout | NumPy `matmul` |
| Linear layer | input batch + weights + bias | batch, in/out features | NumPy `x @ W + b` |
| Matrix-matrix | hai matrix nhỏ trước | M, K, N, PT×CT/CT×CT, tile size | NumPy `matmul` |

Mọi benchmark ghi ít nhất `max_abs_error`, `max_relative_error`, thời gian
context/keygen, encrypt, evaluate, decrypt, tổng thời gian, peak memory và GPU
memory nếu lấy được. Size tăng dần; không bắt đầu bằng dataset lớn trước khi
case nhỏ pass correctness.

## Thứ tự thực hiện gần nhất

1. Chốt lại parameter baseline chung và làm `variance` pass accuracy CPU/GPU.
2. Hoàn thiện benchmark bảy function hiện có.
3. Implement + benchmark `weighted_sum` trên cả CPU và GPU.
4. Implement `rolling_mean`, sau đó `polynomial_score` trên cả hai backend.
5. Prototype native GPU `matrix_vector_multiply`; CPU chỉ làm oracle nhỏ.
6. Xây `linear_layer` trên layout đã kiểm chứng.
7. Chỉ bắt đầu `matrix_multiply` sau khi matrix-vector ổn định.
8. Tối ưu depth, modulus chain, scale/rescale, relinearization và rotation set
   theo từng workload graph, không theo từng function call rời rạc.

`compare_threshold` và `max` chưa được expose: OpenFHE CPU có API scheme
switch CKKS/FHEW nhưng service hiện chưa có context/key/serialization contract
cho chúng; FIDESlib đang pin không có API tương đương. `rolling_mean` cũng chưa
được expose vì phải chốt trailing/centered, padding và có cho phép wrap-around
packed-slot hay không. `/v1/capabilities` báo chúng trong `not_implemented`,
không đưa vào `operations`.
