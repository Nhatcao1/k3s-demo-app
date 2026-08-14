# HE parameter reminder

We are first proving that `add`, `subtract`, `multiply`, `square`, `sum`,
`mean`, and population `variance` work correctly as exposed services.
The current OpenFHE settings are test defaults, not final optimized settings.
They live in one place: `openfhe_cpu/runtime.py`.

Current trial values are depth `3`, first modulus `60`, scaling modulus `50`,
ring dimension `16384`, batch size `8192`, and `FLEXIBLEAUTO` scaling. The
runtime also creates multiplication/relinearization keys and SUM rotation
keys. A client should use `OpenFHECPU()` instead of repeating this setup.

There is no single best HE parameter set for every workload. A longer chain
of multiplications, a reduction, and a simple addition have different needs.
Precision, security, memory, ciphertext size, CPU/GPU time, and supported
calculation depth trade against each other.

Important settings and behavior to revisit include:

- multiplicative depth;
- multiplication/relinearization and rotation keys;
- CKKS scaling modulus and first modulus;
- automatic rescaling/scaling behavior;
- ring dimension, batch size, precision, and error tolerance.

For CKKS, do not treat a plaintext modulus `p` like the BFV/BGV setting. CKKS
mainly needs its scaling and modulus chain tuned for the calculation depth and
required precision.

The CPU-only BGV multiplication-range demo is deliberately separate. Its
plaintext modulus is `200000045057`, multiplicative depth is `1`, ring
dimension is `16384`, and batch size is `8192`. The centered signed range is
`±100000022528`, covering SUM targets through 100 billion and the default
multiplication products. Crossing that range is modular wraparound, not a CKKS
precision failure.

## Optimization checkpoint

Keep the defaults while establishing correctness and baseline measurements.
After all planned CPU and GPU functions pass their benchmarks, return here
and tune parameters per workload. Every change must rerun both accuracy and
performance tests; an optimization that is faster but breaks precision does
not pass.
