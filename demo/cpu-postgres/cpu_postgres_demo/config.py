"""Environment and CSV input for the K3s demo."""

from __future__ import annotations

import base64
import binascii
import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import math
import os
from pathlib import Path
import re
from typing import Mapping

from openfhe_cpu.runtime import BATCH_SIZE, BGV_PLAINTEXT_MODULUS


SESSION_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
MIN_SALARY = 10_000_000
MAX_SALARY = 200_000_000
MIN_KPI = Decimal("0.8")
MAX_KPI = Decimal("1.2")


class DemoConfigError(ValueError):
    """A required demo setting is absent or invalid."""


def _required(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "").strip()
    if not value:
        raise DemoConfigError(f"{name} is required")
    return value


def parse_session_id(environment: Mapping[str, str]) -> str:
    session_id = _required(environment, "DEMO_SESSION_ID")
    if not SESSION_ID_PATTERN.fullmatch(session_id):
        raise DemoConfigError("DEMO_SESSION_ID has an invalid format")
    return session_id


def parse_scheme(environment: Mapping[str, str]) -> str:
    scheme = environment.get("DEMO_SCHEME", "ckks").strip().lower()
    if scheme not in ("ckks", "bgv"):
        raise DemoConfigError("DEMO_SCHEME must be ckks or bgv")
    return scheme


def parse_salaries(environment: Mapping[str, str]) -> tuple[int, ...]:
    path = Path(_required(environment, "DEMO_SALARIES_CSV"))
    try:
        rows = list(csv.reader(path.read_text(encoding="utf-8").splitlines()))
    except OSError as error:
        raise DemoConfigError(f"could not read salary CSV: {path}") from error
    if rows and rows[0] == ["salary"]:
        rows = rows[1:]
    if not rows or len(rows) > BATCH_SIZE:
        raise DemoConfigError(f"salary CSV must contain 1 to {BATCH_SIZE} rows")

    salaries: list[int] = []
    for number, row in enumerate(rows, start=2):
        if len(row) != 1:
            raise DemoConfigError(f"salary CSV row {number} must contain one value")
        try:
            salary = int(row[0])
        except ValueError as error:
            raise DemoConfigError(f"salary CSV row {number} is not an integer") from error
        if not MIN_SALARY <= salary <= MAX_SALARY:
            raise DemoConfigError(
                f"salary CSV row {number} must be between {MIN_SALARY} and {MAX_SALARY}"
            )
        salaries.append(salary)
    return tuple(salaries)


def parse_kpi(environment: Mapping[str, str]) -> Decimal:
    try:
        kpi = Decimal(_required(environment, "DEMO_KPI"))
    except InvalidOperation as error:
        raise DemoConfigError("DEMO_KPI must be a decimal number") from error
    if not kpi.is_finite() or not MIN_KPI <= kpi <= MAX_KPI:
        raise DemoConfigError("DEMO_KPI must be between 0.8 and 1.2")
    return kpi


def parse_positive_integer(
    environment: Mapping[str, str], name: str, default: int
) -> int:
    try:
        value = int(environment.get(name, str(default)))
    except ValueError as error:
        raise DemoConfigError(f"{name} must be an integer") from error
    if value < 1:
        raise DemoConfigError(f"{name} must be positive")
    return value


def parse_wrap_key(environment: Mapping[str, str]) -> bytes:
    try:
        key = base64.b64decode(
            _required(environment, "DEMO_KEY_WRAP_KEY"), validate=True
        )
    except (binascii.Error, ValueError) as error:
        raise DemoConfigError("DEMO_KEY_WRAP_KEY must be valid base64") from error
    if len(key) != 32:
        raise DemoConfigError("DEMO_KEY_WRAP_KEY must decode to 32 bytes")
    return key


def parse_tolerance(environment: Mapping[str, str]) -> float:
    try:
        tolerance = float(environment.get("DEMO_TOLERANCE", "0.000001"))
    except ValueError as error:
        raise DemoConfigError("DEMO_TOLERANCE must be a number") from error
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise DemoConfigError("DEMO_TOLERANCE must be positive")
    return tolerance


@dataclass(frozen=True)
class DemoInputs:
    session_id: str
    scheme: str
    salaries: tuple[int, ...]
    kpi: Decimal
    kpi_scale: int
    kpi_scaled: int
    bgv_plaintext_modulus: int
    wrap_key: bytes
    tolerance: float

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> "DemoInputs":
        selected = os.environ if environment is None else environment
        scheme = parse_scheme(selected)
        salaries = parse_salaries(selected)
        kpi = parse_kpi(selected)
        kpi_scale = parse_positive_integer(selected, "DEMO_KPI_SCALE", 10)
        scaled = kpi * kpi_scale
        if scaled != scaled.to_integral_value():
            raise DemoConfigError("DEMO_KPI must be exact at DEMO_KPI_SCALE")
        kpi_scaled = int(scaled)
        modulus = parse_positive_integer(
            selected, "DEMO_BGV_PLAINTEXT_MODULUS", BGV_PLAINTEXT_MODULUS
        )
        if scheme == "bgv":
            if modulus.bit_length() > 60 or (modulus - 1) % (2 * BATCH_SIZE):
                raise DemoConfigError("BGV plaintext modulus is not batch compatible")
            if sum(salaries) * kpi_scaled >= modulus // 2:
                raise DemoConfigError("BGV result would wrap around the plaintext modulus")
        return cls(
            session_id=parse_session_id(selected),
            scheme=scheme,
            salaries=salaries,
            kpi=kpi,
            kpi_scale=kpi_scale,
            kpi_scaled=kpi_scaled,
            bgv_plaintext_modulus=modulus,
            wrap_key=parse_wrap_key(selected),
            tolerance=parse_tolerance(selected),
        )
