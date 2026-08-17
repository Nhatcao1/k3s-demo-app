# SDK-only two-notebook demo

This demo uses the public `he_sdk` API only. It does not call an HTTP evaluator,
PostgreSQL, Docker, or Kubernetes.

1. Run `01_owner_encrypt.ipynb` through `OWNER_ENCRYPT=PASS` and keep its kernel
   running.
2. Open `02_compute_encrypted.ipynb` with a separate kernel and run it through
   `COMPUTE_ONLY=PASS`.
3. Return to notebook 01, decrypt the three results, and close the owner session.

Both notebooks default to `~/he-sdk-notebook-workspace`. Override the path for
both kernels with `HE_SDK_WORKSPACE`. The shared workspace contains only public
HE material, metadata, and ciphertext. The owner secret key remains in the
owner kernel and is never saved.
