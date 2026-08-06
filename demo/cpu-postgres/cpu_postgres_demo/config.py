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
ALLOWED_KPIS = frozenset(
    Decimal(value) for value in ("0.8", "0.9", "1.0", "1.1", "1.2")
)


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


def parse_salary_rows(
    environment: Mapping[str, str],
) -> tuple[tuple[int, ...], tuple[Decimal, ...]]:
    path = Path(_required(environment, "DEMO_SALARIES_CSV"))
    try:
        rows = list(csv.reader(path.read_text(encoding="utf-8").splitlines()))
    except OSError as error:
        raise DemoConfigError(f"could not read salary CSV: {path}") from error
    if rows and rows[0] == ["salary", "kpi"]:
        rows = rows[1:]
    if not rows or len(rows) > BATCH_SIZE:
        raise DemoConfigError(f"salary CSV must contain 1 to {BATCH_SIZE} rows")

    salaries: list[int] = []
    kpis: list[Decimal] = []
    for number, row in enumerate(rows, start=2):
        if len(row) != 2:
            raise DemoConfigError(
                f"salary CSV row {number} must contain salary and kpi"
            )
        try:
            salary = int(row[0])
        except ValueError as error:
            raise DemoConfigError(f"salary CSV row {number} is not an integer") from error
        if not MIN_SALARY <= salary <= MAX_SALARY:
            raise DemoConfigError(
                f"salary CSV row {number} must be between {MIN_SALARY} and {MAX_SALARY}"
            )
        try:
            kpi = Decimal(row[1])
        except InvalidOperation as error:
            raise DemoConfigError(f"salary CSV row {number} KPI is invalid") from error
        if not kpi.is_finite() or kpi not in ALLOWED_KPIS:
            raise DemoConfigError(
                f"salary CSV row {number} KPI must be 0.8, 0.9, 1.0, 1.1 or 1.2"
            )
        salaries.append(salary)
        kpis.append(kpi)
    return tuple(salaries), tuple(kpis)


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
    kpis: tuple[Decimal, ...]
    kpi_scale: int
    kpis_scaled: tuple[int, ...]
    bgv_plaintext_modulus: int
    wrap_key: bytes
    tolerance: float

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> "DemoInputs":
        selected = os.environ if environment is None else environment
        scheme = parse_scheme(selected)
        salaries, kpis = parse_salary_rows(selected)
        kpi_scale = parse_positive_integer(selected, "DEMO_KPI_SCALE", 10)
        scaled = tuple(kpi * kpi_scale for kpi in kpis)
        if any(value != value.to_integral_value() for value in scaled):
            raise DemoConfigError("CSV KPI must be exact at DEMO_KPI_SCALE")
        kpis_scaled = tuple(int(value) for value in scaled)
        modulus = parse_positive_integer(
            selected, "DEMO_BGV_PLAINTEXT_MODULUS", BGV_PLAINTEXT_MODULUS
        )
        if scheme == "bgv":
            if modulus.bit_length() > 60 or (modulus - 1) % (2 * BATCH_SIZE):
                raise DemoConfigError("BGV plaintext modulus is not batch compatible")
            weighted_total = sum(
                salary * kpi for salary, kpi in zip(salaries, kpis_scaled)
            )
            if weighted_total >= modulus // 2:
                raise DemoConfigError("BGV result would wrap around the plaintext modulus")
        return cls(
            session_id=parse_session_id(selected),
            scheme=scheme,
            salaries=salaries,
            kpis=kpis,
            kpi_scale=kpi_scale,
            kpis_scaled=kpis_scaled,
            bgv_plaintext_modulus=modulus,
            wrap_key=parse_wrap_key(selected),
            tolerance=parse_tolerance(selected),
        )
