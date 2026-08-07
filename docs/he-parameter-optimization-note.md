# HE parameter profiles (CPU trial)

CPU OpenFHE không còn dùng một cấu hình lớn chung cho mọi function. Trusted
client chọn operation trước, sau đó `openfhe_cpu/runtime.py` tạo context và chỉ
sinh evaluation key cần cho operation đó. Đây vẫn là correctness-first trial
config, chưa phải kết quả tối ưu benchmark.

## Phần global và phần theo function

Các giá trị hiện dùng chung:

| Cấu hình | Giá trị |
| --- | ---: |
| Scheme | CKKS |
| Scaling technique | `FLEXIBLEAUTO` |
| First modulus | 60 bits |
| Ring dimension | 16384 |
| Batch size | 8192 |
| Security | `HEStd_128_classic` |

Profile theo operation:

| Function | Depth phép toán | Depth cấp cho context | Scaling modulus | Mult/relin key | Rotation/EvalSum key |
| --- | ---: | ---: | ---: | --- | --- |
| `add` | 0 | 1 | 45 | Không | Không |
| `subtract` | 0 | 1 | 45 | Không | Không |
| `multiply` | 1 | 1 | 50 | Có | Không |
| `square` | 1 | 1 | 50 | Có | Không |
| `sum` | 0 | 1 | 45 | Không | Có |
| `mean` | 0–1 | 1 | 50 | Không | Có |
| `variance` | 2–3 | 3 | 55 | Có | Có |

Depth 0 vẫn cấp `context_depth=1` để OpenFHE có modulus chain CKKS sử dụng
được. `variance` đang được cấp thận trọng depth 3 và scale 55 vì gồm square,
scalar multiplication, reductions và square của mean. Các giá trị này phải
được xác nhận bằng accuracy/latency/memory benchmark trên server trước khi
giảm hoặc tăng tiếp.

## Chi phí logic của function

| Function | Input | Output | Required key | Mult. depth | Rotations | Notes |
| --- | --- | --- | --- | ---: | ---: | --- |
| `encrypt` | `values: Sequence[float]` | `Enc(values)` | Public key | 0 | 0 | `len(values) <= BATCH_SIZE` |
| `decrypt` | `ciphertext`, `length` | `list[float]` | Secret key | 0 | 0 | Normally client-side only |
| `add` | `Enc(x)`, `Enc(y)` | `Enc(x+y)` | None | 0 | 0 | Same context and compatible level |
| `subtract` | `Enc(x)`, `Enc(y)` | `Enc(x-y)` | None | 0 | 0 | Same context and compatible level |
| `multiply` | `Enc(x)`, `Enc(y)` | `Enc(x*y)` | EvalMult/relinearization key | 1 | 0 | Consumes one multiplicative level |
| `square` | `Enc(x)` | `Enc(x^2)` | EvalMult/relinearization key | 1 | 0 | Usually cheaper than generic multiply |
| `sum` | `Enc(x)`, `valid_count` | `Enc(sum(x))` | Rotation/EvalSum keys | 0 | `ceil(log2(valid_count))` logical steps | Result normally stored in slot 0 |
| `mean` | `Enc(x)`, `valid_count` | `Enc(sum(x)/n)` | Rotation/EvalSum keys | 0–1 | `ceil(log2(valid_count))` logical steps | CT x plaintext constant may consume a level |
| `variance` | `Enc(x)`, `valid_count` | `Enc(E[x^2]-E[x]^2)` | EvalMult + Rotation/EvalSum keys | 2–3 | About `2*ceil(log2(valid_count))` logical steps | Highest-cost function in this set |

Số rotation thực tế phụ thuộc thuật toán/library. Bảng trên mô tả chi phí
logic; không được dùng nó để tự suy ra chính xác danh sách rotation index của
FIDESlib.

## Ranh giới bắt buộc

- Chọn profile trước keygen và encrypt.
- Không trộn ciphertext hoặc evaluation key giữa các context/profile.
- `/v1/evaluate` không tự chọn lại parameter; nó thực thi context serialized
  do trusted client gửi vào.
- Một request demo chỉ chạy một operation nên dùng profile nhỏ theo function.
- Một workflow ghép nhiều operation trên cùng ciphertext phải phân tích toàn
  DAG và tạo **một workflow profile** đủ cho đường nhân sâu nhất. Không được
  đổi sang profile khác giữa workflow.
- Với `FLEXIBLEAUTO`, code hiện không gọi `Rescale` thủ công.

Sau khi correctness CPU và GPU ổn định, benchmark từng workload rồi tune
depth, scaling modulus, ring dimension, batch size, key set, precision và sai
số. Faster nhưng vượt accuracy tolerance không được xem là tối ưu thành công.
