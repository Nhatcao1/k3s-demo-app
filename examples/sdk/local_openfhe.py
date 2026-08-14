#!/usr/bin/env python3
"""Small local SDK example; run on Linux with the OpenFHE extra installed."""

from __future__ import annotations

from he_sdk import CKKSConfig, HESession


def main() -> None:
    config = CKKSConfig.profile("ckks-balanced-v1")
    with HESession.create(backend="openfhe", config=config) as he:
        left = he.encrypt([1.25, -2.0, 3.5, 4.0])
        right = he.encrypt([0.75, 5.0, -1.5, 2.0])

        print("add:", he.decrypt(he.add(left, right)))
        print("sum:", he.decrypt(he.sum(left)))
        print("variance:", he.decrypt(he.variance(left)))


if __name__ == "__main__":
    main()
