"""Isolated HEIR/OpenFHE trial for one fixed encrypted calculation."""

from __future__ import annotations

import importlib
import math
import threading
import time
from typing import Any, Sequence


HEIR_TRIAL_WIDTH = 4


class HeirUnavailableError(RuntimeError):
    """Raised when the optional HEIR runtime cannot be loaded."""


def adjusted_net_total_mlir(width: int = HEIR_TRIAL_WIDTH) -> str:
    """Build a single-result CKKS circuit for SUM((income-expenses)*adjustment)."""
    if width < 2:
        raise ValueError("HEIR trial width must be at least two")

    tensor = f"tensor<{width}xf64>"
    lines = [
        "func.func @adjusted_net_total(",
        f"    %income: {tensor} {{secret.secret}},",
        f"    %expenses: {tensor} {{secret.secret}},",
        f"    %adjustment: {tensor} {{secret.secret}}",
        ") -> f64 {",
        f"  %net = arith.subf %income, %expenses : {tensor}",
        f"  %adjusted = arith.mulf %net, %adjustment : {tensor}",
    ]

    current: list[str] = []
    for index in range(width):
        lines.append(f"  %index_{index} = arith.constant {index} : index")
        lines.append(
            f"  %value_{index} = tensor.extract "
            f"%adjusted[%index_{index}] : {tensor}"
        )
        current.append(f"%value_{index}")

    level = 0
    while len(current) > 1:
        next_level: list[str] = []
        for index in range(0, len(current), 2):
            if index + 1 == len(current):
                next_level.append(current[index])
                continue
            is_final = len(current) == 2
            name = "%total" if is_final else f"%sum_{level}_{index // 2}"
            lines.append(
                f"  {name} = arith.addf "
                f"{current[index]}, {current[index + 1]} : f64"
            )
            next_level.append(name)
        current = next_level
        level += 1

    lines.extend(["  return %total : f64", "}"])
    return "\n".join(lines) + "\n"


def _vector(values: Sequence[float], *, name: str) -> Any:
    materialized = [float(value) for value in values]
    if len(materialized) != HEIR_TRIAL_WIDTH:
        raise ValueError(
            f"{name} must contain exactly {HEIR_TRIAL_WIDTH} values"
        )
    if not all(math.isfinite(value) for value in materialized):
        raise ValueError(f"{name} must contain only finite numbers")

    try:
        import numpy as np
    except ImportError as error:
        raise HeirUnavailableError(
            "NumPy is required by the HEIR tensor interface"
        ) from error
    return np.asarray(materialized, dtype=np.float64)


class HeirAdjustedNetTrial:
    """Compile one HEIR program once and reuse its OpenFHE context and keys."""

    def __init__(self) -> None:
        self._program: Any | None = None
        self._compile_seconds: float | None = None
        self._setup_seconds: float | None = None
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        try:
            importlib.import_module("heir")
            importlib.import_module("numpy")
        except (ImportError, OSError):
            return False
        return True

    def _setup(self) -> Any:
        if self._program is not None:
            return self._program
        if not self.available:
            raise HeirUnavailableError(
                "install heir_py[python,openfhe] to enable the HEIR trial"
            )

        from heir import compile as heir_compile

        started = time.perf_counter()
        program = heir_compile(
            mlir_str=adjusted_net_total_mlir(),
            scheme="ckks",
            debug=False,
        )
        self._compile_seconds = time.perf_counter() - started

        started = time.perf_counter()
        program.setup()
        self._setup_seconds = time.perf_counter() - started
        self._program = program
        return program

    def evaluate(
        self,
        income: Sequence[float],
        expenses: Sequence[float],
        adjustment: Sequence[float],
    ) -> dict[str, float | int | str | bool]:
        """Encrypt three vectors, run the compiled circuit, and audit-decrypt."""
        packed = (
            _vector(income, name="income"),
            _vector(expenses, name="expenses"),
            _vector(adjustment, name="adjustment"),
        )

        with self._lock:
            program = self._setup()
            encryptors = program.compilation_result.arg_enc_funcs or {}
            if len(encryptors) != 3:
                raise RuntimeError(
                    "expected three encrypted inputs from compiled HEIR program"
                )

            started = time.perf_counter()
            encrypted_inputs = [
                getattr(program, f"encrypt_{name}")(value)
                for name, value in zip(encryptors, packed, strict=True)
            ]
            encrypt_seconds = time.perf_counter() - started

            started = time.perf_counter()
            encrypted_result = program.eval(*encrypted_inputs)
            evaluation_seconds = time.perf_counter() - started

            started = time.perf_counter()
            result = float(program.decrypt_result(encrypted_result))
            decrypt_seconds = time.perf_counter() - started

        return {
            "program": "adjusted_net_total",
            "scheme": "CKKS",
            "width": HEIR_TRIAL_WIDTH,
            "result": result,
            "compile_seconds_once": float(self._compile_seconds or 0.0),
            "setup_seconds_once": float(self._setup_seconds or 0.0),
            "encrypt_seconds": encrypt_seconds,
            "evaluation_seconds": evaluation_seconds,
            "decrypt_seconds": decrypt_seconds,
            "heir_generated": True,
        }
