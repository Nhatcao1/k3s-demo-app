# HE parameter reminder

We are first proving that `add`, `subtract`, `multiply`, `sum`, and later
functions such as `mean` and `variance` work correctly as exposed services.
The current OpenFHE settings are test defaults, not final optimized settings.
They live in one place: `openfhe_cpu/runtime.py`.

Current trial values are depth `1`, first modulus `60`, scaling modulus `50`,
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

## Optimization checkpoint

Keep the defaults while establishing correctness and baseline measurements.
After all planned CPU and GPU functions pass their benchmarks, return here
and tune parameters per workload. Every change must rerun both accuracy and
performance tests; an optimization that is faster but breaks precision does
not pass.
