from __future__ import annotations

from types import SimpleNamespace
import unittest

from openfhe_cpu.runtime import (
    BATCH_SIZE,
    FIRST_MOD_SIZE,
    OPERATION_PROFILES,
    RING_DIMENSION,
    OpenFHECPU,
    create_operation_context_and_keys,
)


class FakeParameters:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def SetMultiplicativeDepth(self, value: int) -> None:
        self.values["depth"] = value

    def SetFirstModSize(self, value: int) -> None:
        self.values["first_mod"] = value

    def SetScalingModSize(self, value: int) -> None:
        self.values["scaling_mod"] = value

    def SetScalingTechnique(self, value: object) -> None:
        self.values["scaling"] = value

    def SetSecurityLevel(self, value: object) -> None:
        self.values["security"] = value

    def SetRingDim(self, value: int) -> None:
        self.values["ring"] = value

    def SetBatchSize(self, value: int) -> None:
        self.values["batch"] = value


class FakeContext:
    def __init__(self) -> None:
        self.enabled: list[object] = []
        self.mult_key_calls = 0
        self.sum_key_calls = 0

    def Enable(self, feature: object) -> None:
        self.enabled.append(feature)

    def KeyGen(self) -> SimpleNamespace:
        return SimpleNamespace(secretKey="secret", publicKey="public")

    def EvalMultKeyGen(self, secret_key: object) -> None:
        self.mult_key_calls += 1

    def EvalSumKeyGen(self, secret_key: object) -> None:
        self.sum_key_calls += 1


class FakeOpenFHE:
    FLEXIBLEAUTO = "FLEXIBLEAUTO"
    HEStd_128_classic = "HEStd_128_classic"
    PKE = "PKE"
    KEYSWITCH = "KEYSWITCH"
    LEVELEDSHE = "LEVELEDSHE"
    ADVANCEDSHE = "ADVANCEDSHE"

    def __init__(self) -> None:
        self.parameters: FakeParameters | None = None
        self.context: FakeContext | None = None

    def CCParamsCKKSRNS(self) -> FakeParameters:
        self.parameters = FakeParameters()
        return self.parameters

    def GenCryptoContext(self, parameters: FakeParameters) -> FakeContext:
        self.context = FakeContext()
        return self.context


class OperationProfileTests(unittest.TestCase):
    def test_profiles_match_the_reviewed_cpu_policy(self) -> None:
        expected = {
            "add": (0, 1, 45, False, False),
            "subtract": (0, 1, 45, False, False),
            "multiply": (1, 1, 50, True, False),
            "square": (1, 1, 50, True, False),
            "sum": (0, 1, 45, False, True),
            "mean": (1, 1, 50, False, True),
            "variance": (2, 3, 55, True, True),
        }
        actual = {
            name: (
                profile.operation_depth,
                profile.context_depth,
                profile.scaling_mod_size,
                profile.needs_multiplication_keys,
                profile.needs_rotation_keys,
            )
            for name, profile in OPERATION_PROFILES.items()
        }
        self.assertEqual(actual, expected)

    def test_context_uses_profile_and_generates_only_required_keys(self) -> None:
        for operation, profile in OPERATION_PROFILES.items():
            with self.subTest(operation=operation):
                module = FakeOpenFHE()
                context, keys = create_operation_context_and_keys(
                    module, operation
                )
                self.assertEqual(module.parameters.values["depth"], profile.context_depth)
                self.assertEqual(module.parameters.values["first_mod"], FIRST_MOD_SIZE)
                self.assertEqual(
                    module.parameters.values["scaling_mod"],
                    profile.scaling_mod_size,
                )
                self.assertEqual(module.parameters.values["ring"], RING_DIMENSION)
                self.assertEqual(module.parameters.values["batch"], BATCH_SIZE)
                self.assertEqual(
                    context.mult_key_calls,
                    int(profile.needs_multiplication_keys),
                )
                self.assertEqual(
                    context.sum_key_calls,
                    int(profile.needs_rotation_keys),
                )
                self.assertEqual(keys.secretKey, "secret")

    def test_direct_client_rejects_an_operation_from_another_profile(self) -> None:
        client = OpenFHECPU("add", FakeOpenFHE())
        with self.assertRaisesRegex(ValueError, "add profile, not variance"):
            client.variance("ciphertext", 4)


if __name__ == "__main__":
    unittest.main()
