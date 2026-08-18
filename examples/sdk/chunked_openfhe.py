"""SDK 0.5 development example: 20,000 values, three ciphertext chunks."""

from __future__ import annotations

from he_sdk import HESession


def input_values(count: int):
    """Yield values lazily so plaintext file-sized inputs stay memory bounded."""
    for value in range(1, count + 1):
        yield float(value)


def main() -> None:
    count = 20_000
    with HESession.create(backend="openfhe") as he:
        encrypted = he.encrypt_iter(input_values(count))
        print("logical values:", encrypted.metadata.valid_count)
        print("ciphertext chunks:", encrypted.chunk_count)
        print("chunk valid counts:", [item.valid_count for item in encrypted.chunks])

        encrypted_sum = he.sum(encrypted)
        encrypted_mean = he.mean(encrypted)
        encrypted_variance = he.variance(encrypted)

        print("sum:", he.decrypt(encrypted_sum))
        print("mean:", he.decrypt(encrypted_mean))
        print("population variance:", he.decrypt(encrypted_variance))


if __name__ == "__main__":
    main()
