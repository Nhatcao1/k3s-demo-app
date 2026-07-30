from __future__ import annotations

import base64
import unittest

from encryptor.app import RequestError, decode_ciphertext, validate_vectors


class ValidateVectorsTests(unittest.TestCase):
    def test_accepts_matching_numeric_vectors(self) -> None:
        left, right = validate_vectors(
            {"left": [1, 2.5], "right": [10, 20]}
        )
        self.assertEqual(left, [1.0, 2.5])
        self.assertEqual(right, [10.0, 20.0])

    def test_rejects_different_lengths(self) -> None:
        with self.assertRaisesRegex(RequestError, "same length"):
            validate_vectors({"left": [1, 2], "right": [10]})

    def test_rejects_secret_key_field(self) -> None:
        with self.assertRaisesRegex(RequestError, "unexpected fields"):
            validate_vectors(
                {
                    "left": [1],
                    "right": [2],
                    "secret_key": "not-accepted",
                }
            )


class DecodeCiphertextTests(unittest.TestCase):
    def test_decodes_result(self) -> None:
        encoded = base64.b64encode(b"result").decode("ascii")
        self.assertEqual(decode_ciphertext({"ciphertext": encoded}), b"result")

    def test_rejects_extra_fields(self) -> None:
        with self.assertRaisesRegex(RequestError, "only ciphertext"):
            decode_ciphertext({"ciphertext": "abc", "secret_key": "no"})


if __name__ == "__main__":
    unittest.main()
