# Homomorphic Encryption API Trial

## Purpose

This trial exposes OpenFHE calculations as a small service running on K3s.
A normal Python program can call the service through `HEClient` without
installing OpenFHE on the caller machine.

The current goal is to prove that encrypted vector operations can be composed
behind a simple Python interface. It is a trial service, not yet a production
security design.

## How it works

```text
Python program
  -> HEClient sends an HTTP request
  -> K3s Service routes it to the HE gateway Pod
  -> OpenFHE performs CKKS encrypted calculations
  -> HEClient receives the requested final result
```

OpenFHE and its C++ runtime are installed only inside the container image.
The Kubernetes Service is named `he-gateway` in the `he-dev` namespace.

## Supported operations

| Python expression | HE operation | Output |
| --- | --- | --- |
| `left + right` | Ciphertext addition | Encrypted vector |
| `left - right` | Ciphertext subtraction | Encrypted vector |
| `left * right` | Ciphertext multiplication | Encrypted vector |
| `value.square()` | Ciphertext square | Encrypted vector |
| `value.sum()` | Sum of encrypted vector slots | Encrypted scalar |
| `value.mean()` | Mean of encrypted vector slots | Encrypted scalar |
| `he.variance_components(x)` | Sum and sum of squares | Two encrypted scalars and public count |
| `he.covariance_components(x, y)` | Sums and sum of products | Three encrypted scalars and public count |
| `he.correlation_components(x, y)` | Sums, squared sums and product sum | Five encrypted scalars and public count |
| `he.weighted_sum(x, weights)` | Public-weighted encrypted sum | Encrypted scalar |
| `he.risk_score(x, weights, bias)` | Weighted sum plus public bias | Encrypted scalar |
| `value.decrypt()` | Decryption | Python list of numbers |
| `he.adjusted_net_total(...)` | Fixed HEIR-compiled calculation | Audited scalar and timings |

Binary arithmetic accepts another encrypted vector, a `PublicVector`, or a
`PublicScalar`. Inputs are non-empty numeric vectors. Vectors used together
must have the same length and encrypted values must belong to the same client
session. CKKS uses approximate arithmetic, so decrypted results can contain a
small numerical error.

## Recommended Python interface

```python
from he_client import HEClient

with HEClient("http://127.0.0.1:18082") as he:
    income = he.encrypt([120, 150, 180, 200])
    expenses = he.encrypt([80, 90, 110, 130])
    adjustment = he.encrypt([1.0, 0.9, 1.1, 1.0])

    net = income - expenses
    adjusted_net = net * adjustment

    total = adjusted_net.sum().decrypt()[0]
    average = adjusted_net.mean().decrypt()[0]

print(total)
print(average)
```

The intermediate values `net`, `adjusted_net`, and the reduction results remain
remote ciphertext objects. This example decrypts only the final total and
average.

For the included values, the expected results are approximately:

```text
total   = 241.0
average = 60.25
```

Public values and analytics compositions use the same client:

```python
from he_client import HEClient, PublicScalar, PublicVector

with HEClient("http://127.0.0.1:18082") as he:
    features = he.encrypt([2, 4, 6, 8])
    weights = PublicVector([0.1, 0.2, 0.3, 0.4])

    variance = he.variance_components(features)
    score = he.risk_score(features, weights, PublicScalar(1.5))

    print(variance.sum_x.decrypt())
    print(variance.sum_x_square.decrypt())
    print(variance.count)
    print(score.decrypt())
```

Component methods intentionally return encrypted sufficient statistics rather
than decrypting variance, covariance, or correlation inside the library.

## Running the trial

Forward the K3s Service from the server:

```sh
kubectl -n he-dev port-forward service/he-gateway 18082:8080
```

In another terminal, from the application repository:

```sh
python3 -m client.boss_demo --url http://127.0.0.1:18082

python3 -m client.easy_operations_bench \
  --url http://127.0.0.1:18082
```

The scripts compare HE results with ordinary Python calculations and print
`"status": "PASS"` when the difference is within the configured tolerance.

## HTTP API summary

Most callers should use `HEClient`, but the service underneath provides these
HTTP endpoints:

| Method and path | Input | Output |
| --- | --- | --- |
| `GET /healthz` | None | Service health |
| `GET /readyz` | None | OpenFHE readiness |
| `GET /v1/capabilities` | None | Scheme and supported operations |
| `POST /v1/sessions` | `values`, optional `multiplicative_depth` | Session ID and ciphertext ID |
| `POST /v1/sessions/{id}/ciphertexts` | `values` | New ciphertext ID |
| `POST /v1/sessions/{id}/evaluate` | Operation, ciphertext ID and optional ciphertext/public operand | Result ciphertext ID |
| `POST /v1/sessions/{id}/decrypt` | Ciphertext ID | Decrypted numeric values |
| `DELETE /v1/sessions/{id}` | None | Deletes the in-memory session |

Ciphertexts are represented to the caller by opaque IDs. The actual OpenFHE
objects and keys stay inside the gateway process.

## HEIR proof

The gateway also contains one isolated HEIR program:

```text
SUM((income - expenses) * adjustment)
```

It accepts three four-value vectors through
`POST /v1/heir/adjusted-net`. HEIR compiles the complete single-result CKKS
circuit and uses its own OpenFHE context. Its ciphertexts are not passed to or
from the generic `openfhe-python` sessions.

Run the proof with:

```sh
python3 -m client.heir_trial --url http://127.0.0.1:18082
```

The first call performs compilation and key setup. Later calls reuse the live
program while the gateway Pod remains running.

## Current trust model and limits

This is a **trusted gateway** trial:

- plaintext input enters the gateway before it is encrypted;
- secret keys and ciphertext sessions are held in Pod memory;
- sessions disappear when the Pod restarts or their time limit expires;
- the deployment currently uses one gateway replica;
- authentication and TLS are not implemented yet.

A later version can move encryption and decryption to the client so the service
receives only ciphertext. The current version focuses on proving the callable
HE service and Kubernetes deployment flow.
