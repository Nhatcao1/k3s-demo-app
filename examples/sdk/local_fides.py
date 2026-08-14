"""Run the same public SDK contract through the optional FIDES GPU plugin."""

from he_sdk import HESession


def main() -> None:
    with HESession.create(backend="fides") as he:
        encrypted = he.encrypt([1.0, 2.0, 3.0, 4.0])
        encrypted_result = he.variance(encrypted)
        print(he.decrypt(encrypted_result))


if __name__ == "__main__":
    main()
