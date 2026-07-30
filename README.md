# HE application for the K3s lab

This GitLab repository is now the development source for the homomorphic
encryption application deployed to the K3s lab. The previous counter web
application remains available in Git history but is no longer built or
deployed.

Current trial:

```text
HEClient without OpenFHE
  -> one trusted gateway
  -> OpenFHE add / subtract / multiply / sum / mean
  -> explicit result decryption
```

The caller uses a normal Python interface:

```python
from he_client import HEClient

with HEClient("http://he-dev.k3s.test") as he:
    installment = he.encrypt([12, 25, 41])
    payment = he.encrypt([10, 20, 30])

    difference = installment - payment
    total = difference.sum()
    average = difference.mean()

    print(total.decrypt())
    print(average.decrypt())
```

Supported operations are ciphertext `+`, `-`, `*`, `sum()`, and `mean()`.
Mean divides by the public logical vector length. The gateway is trusted: it
receives plaintext and retains session secret keys in memory, which is why the
caller does not install OpenFHE.

## GitLab pipeline

Every pipeline validates files and runs dependency-free contract tests. A
commit on the default branch also builds and pushes the deployable gateway
container image:

```text
registry.gitlab.com/nhatcao99uetwork/k3s-demo-app/openfhe-gateway:<full-commit-sha>
```

The immutable GitLab application commit is the image tag promoted by the
GitOps repository. No Docker Hub credential or manual server build is needed
for the K3s lab. The image defaults to `python -m gateway.app`; Kubernetes
does not need to replace an unrelated application command.

## Local contract tests

These tests use fake cryptography and do not install OpenFHE:

```sh
python3 -m unittest discover -s tests -v
```

The actual OpenFHE package is installed when the Ubuntu image is built.

## Repository roles

```text
k3s-demo-app
  -> HE source, tests, Dockerfile, GitLab CI

k3s-demo-gitops
  -> Kustomize manifests, image promotion, Argo CD

he_k8s
  -> kept separately for the later production-server path
```

Future HE development for the K3s trial should be committed here first so
GitLab CI and Argo CD always refer to the same source commit.

## Current limits

- one gateway replica with in-memory sessions;
- equal-length vectors within a session;
- bounded CKKS multiplication depth;
- no TLS or authentication yet;
- no variance, min/max, dot product, or scoring functions.
