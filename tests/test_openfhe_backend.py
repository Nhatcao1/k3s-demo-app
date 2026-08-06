from __future__ import annotations

import unittest

from backends.openfhe_python import OpenFHEPythonBackend


class FakeContext:
    def EvalAdd(self, left: object, right: object) -> tuple[object, ...]:
        return ("add", left, right)

    def EvalSub(self, left: object, right: object) -> tuple[object, ...]:
        return ("subtract", left, right)

    def EvalMult(self, left: object, right: object) -> tuple[object, ...]:
        return ("multiply", left, right)

    def EvalSquare(self, encrypted: object) -> tuple[object, ...]:
        return ("square", encrypted)

    def EvalSum(self, encrypted: object, count: int) -> tuple[object, ...]:
        return ("sum", encrypted, count)


class OpenFHEBackendTests(unittest.TestCase):
    def test_each_method_maps_directly_to_openfhe(self) -> None:
        backend = OpenFHEPythonBackend()
        context = FakeContext()

        self.assertEqual(backend.add(context, "a", "b"), ("add", "a", "b"))
        self.assertEqual(
            backend.subtract(context, "a", "b"), ("subtract", "a", "b")
        )
        self.assertEqual(
            backend.multiply(context, "a", "b"), ("multiply", "a", "b")
        )
        self.assertEqual(backend.square(context, "a"), ("square", "a"))
        self.assertEqual(backend.sum(context, "a", 8), ("sum", "a", 8))
        self.assertEqual(
            backend.mean(context, "a", 8),
            ("multiply", ("sum", "a", 8), 0.125),
        )


if __name__ == "__main__":
    unittest.main()
