"""Environment configuration and validation for the demo Jobs."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import json
import math
import os
import re
from typing import Mapping

from openfhe_cpu.runtime import BATCH_SIZE


SESSION_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


class DemoConfigError(ValueError):
    """A required demo setting is absent or unsafe."""


def _required(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "").strip()
    if not value:
        raise DemoConfigError(f"{name} is required")
    return value


def parse_session_id(environment: Mapping[str, str]) -> str:
    session_id = _required(environment, "DEMO_SESSION_ID")
    if not SESSION_ID_PATTERN.fullmatch(session_id):
        raise DemoConfigError(
            "DEMO_SESSION_ID must contain only lowercase letters, digits, dot, "
            "underscore, or hyphen and be at most 128 characters"
        )
    return session_id


def parse_salaries(environment: Mapping[str, str]) -> tuple[float, ...]:
    raw = _required(environment, "DEMO_SALARIES_JSON")
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as error:
        raise DemoConfigError("DEMO_SALARIES_JSON must be valid JSON") from error
    if not isinstance(values, list) or not values:
        raise DemoConfigError("DEMO_SALARIES_JSON must be a non-empty JSON array")
    if len(values) > BATCH_SIZE:
        raise DemoConfigError(f"salary count must not exceed {BATCH_SIZE}")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
        raise DemoConfigError("every salary must be a number")
    salaries = tuple(float(value) for value in values)
    if not all(math.isfinite(value) for value in salaries):
        raise DemoConfigError("salaries must not contain NaN or infinity")
    return salaries


def parse_kpi(environment: Mapping[str, str]) -> float:
    raw = _required(environment, "DEMO_KPI")
    try:
        kpi = float(raw)
    except ValueError as error:
        raise DemoConfigError("DEMO_KPI must be a number") from error
    if not math.isfinite(kpi):
        raise DemoConfigError("DEMO_KPI must not be NaN or infinity")
    return kpi


def parse_wrap_key(environment: Mapping[str, str]) -> bytes:
    raw = _required(environment, "DEMO_KEY_WRAP_KEY")
    try:
        key = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as error:
        raise DemoConfigError("DEMO_KEY_WRAP_KEY must be valid base64") from error
    if len(key) != 32:
        raise DemoConfigError("DEMO_KEY_WRAP_KEY must decode to exactly 32 bytes")
    return key


def parse_tolerance(environment: Mapping[str, str]) -> float:
    raw = environment.get("DEMO_TOLERANCE", "0.01").strip()
    try:
        tolerance = float(raw)
    except ValueError as error:
        raise DemoConfigError("DEMO_TOLERANCE must be a number") from error
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise DemoConfigError("DEMO_TOLERANCE must be a positive finite number")
    return tolerance


@dataclass(frozen=True)
class DemoInputs:
    session_id: str
    salaries: tuple[float, ...]
    kpi: float
    wrap_key: bytes
    tolerance: float

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> "DemoInputs":
        selected = os.environ if environment is None else environment
        return cls(
            session_id=parse_session_id(selected),
            salaries=parse_salaries(selected),
            kpi=parse_kpi(selected),
            wrap_key=parse_wrap_key(selected),
            tolerance=parse_tolerance(selected),
        )
