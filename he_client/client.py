"""Small HTTP client that presents remote ciphertexts as Python objects."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class HEClientError(RuntimeError):
    """Raised when the HE gateway rejects or cannot complete a request."""


def _finite_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number")
    return number


@dataclass(frozen=True)
class PublicVector:
    """A vector intentionally sent to the gateway without encryption."""

    values: tuple[float, ...]

    def __init__(self, values: list[float] | tuple[float, ...]) -> None:
        if not isinstance(values, (list, tuple)) or not values:
            raise ValueError("PublicVector requires a non-empty numeric list")
        object.__setattr__(
            self,
            "values",
            tuple(_finite_number(value, "public vector value") for value in values),
        )

    def _payload(self) -> dict[str, object]:
        return {"kind": "public_vector", "values": list(self.values)}


@dataclass(frozen=True)
class PublicScalar:
    """A scalar intentionally sent to the gateway without encryption."""

    value: float

    def __init__(self, value: float) -> None:
        object.__setattr__(
            self, "value", _finite_number(value, "public scalar")
        )

    def _payload(self) -> dict[str, object]:
        return {"kind": "public_scalar", "value": self.value}


@dataclass(frozen=True)
class RemoteCiphertext:
    """An opaque ciphertext stored in one trusted gateway session."""

    _client: "HEClient"
    _session_id: str
    _ciphertext_id: str
    _logical_length: int

    def __add__(self, other: object) -> "RemoteCiphertext":
        if not isinstance(
            other, (RemoteCiphertext, PublicVector, PublicScalar)
        ):
            return NotImplemented
        return self._client.add(self, other)

    def __sub__(self, other: object) -> "RemoteCiphertext":
        if not isinstance(
            other, (RemoteCiphertext, PublicVector, PublicScalar)
        ):
            return NotImplemented
        return self._client.subtract(self, other)

    def __mul__(self, other: object) -> "RemoteCiphertext":
        if not isinstance(
            other, (RemoteCiphertext, PublicVector, PublicScalar)
        ):
            return NotImplemented
        return self._client.multiply(self, other)

    def decrypt(self) -> list[float]:
        return self._client.decrypt(self)

    def sum(self) -> "RemoteCiphertext":
        return self._client.sum(self)

    def mean(self) -> "RemoteCiphertext":
        return self._client.mean(self)

    def square(self) -> "RemoteCiphertext":
        return self._client.square(self)

    def __repr__(self) -> str:
        return (
            f"RemoteCiphertext(session={self._session_id[:8]!r}, "
            f"id={self._ciphertext_id[:8]!r}, "
            f"logical_length={self._logical_length})"
        )


@dataclass(frozen=True)
class VarianceComponents:
    sum_x: RemoteCiphertext
    sum_x_square: RemoteCiphertext
    count: int


@dataclass(frozen=True)
class CovarianceComponents:
    sum_x: RemoteCiphertext
    sum_y: RemoteCiphertext
    sum_xy: RemoteCiphertext
    count: int


@dataclass(frozen=True)
class CorrelationComponents:
    sum_x: RemoteCiphertext
    sum_y: RemoteCiphertext
    sum_x_square: RemoteCiphertext
    sum_y_square: RemoteCiphertext
    sum_xy: RemoteCiphertext
    count: int


PublicOperand = PublicVector | PublicScalar
BinaryOperand = RemoteCiphertext | PublicOperand


class HEClient:
    """Connect to one gateway and compose encrypted vector operations."""

    def __init__(
        self,
        gateway_url: str | None = None,
        *,
        multiplicative_depth: int = 3,
        timeout: float = 120.0,
    ) -> None:
        selected_url = gateway_url or os.getenv(
            "HE_GATEWAY_URL", "http://127.0.0.1:18082"
        )
        api_url = selected_url.rstrip("/")
        self._api_url = api_url if api_url.endswith("/v1") else api_url + "/v1"
        self._multiplicative_depth = multiplicative_depth
        self._timeout = timeout
        self._session_id: str | None = None
        self._closed = False

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {} if data is None else {"Content-Type": "application/json"}
        request = Request(
            self._api_url + path,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:
                if response.status == 204:
                    return {}
                result = json.load(response)
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise HEClientError(
                f"gateway returned HTTP {error.code}: {detail}"
            ) from error
        except URLError as error:
            raise HEClientError(f"could not reach HE gateway: {error}") from error
        if not isinstance(result, dict):
            raise HEClientError("gateway did not return a JSON object")
        return result

    def _require_open(self) -> None:
        if self._closed:
            raise HEClientError("HEClient is closed")

    def _owned(self, ciphertext: RemoteCiphertext) -> None:
        self._require_open()
        if (
            ciphertext._client is not self
            or ciphertext._session_id != self._session_id
        ):
            raise HEClientError(
                "ciphertexts must belong to this HEClient session"
            )

    def encrypt(self, values: list[float]) -> RemoteCiphertext:
        self._require_open()
        if self._session_id is None:
            result = self._request(
                "POST",
                "/sessions",
                {
                    "values": values,
                    "multiplicative_depth": self._multiplicative_depth,
                },
            )
            session_id = result.get("session_id")
            ciphertext_id = result.get("ciphertext_id")
            if not isinstance(session_id, str) or not isinstance(
                ciphertext_id, str
            ):
                raise HEClientError(
                    "gateway did not return session and ciphertext IDs"
                )
            self._session_id = session_id
        else:
            result = self._request(
                "POST",
                f"/sessions/{self._session_id}/ciphertexts",
                {"values": values},
            )
            ciphertext_id = result.get("ciphertext_id")
            if not isinstance(ciphertext_id, str):
                raise HEClientError("gateway did not return a ciphertext ID")

        return RemoteCiphertext(
            self,
            self._session_id,
            ciphertext_id,
            len(values),
        )

    def _evaluate(
        self,
        operation: str,
        left: RemoteCiphertext,
        right: BinaryOperand | None = None,
    ) -> RemoteCiphertext:
        self._owned(left)
        if isinstance(right, RemoteCiphertext):
            self._owned(right)
        assert self._session_id is not None
        payload = {
            "operation": operation,
            "left": left._ciphertext_id,
        }
        if isinstance(right, RemoteCiphertext):
            payload["right"] = right._ciphertext_id
        elif isinstance(right, (PublicVector, PublicScalar)):
            if (
                isinstance(right, PublicVector)
                and len(right.values) != left._logical_length
            ):
                raise HEClientError(
                    "public vector must match ciphertext logical length"
                )
            payload["right"] = right._payload()
        result = self._request(
            "POST",
            f"/sessions/{self._session_id}/evaluate",
            payload,
        )
        ciphertext_id = result.get("ciphertext_id")
        if not isinstance(ciphertext_id, str):
            raise HEClientError("gateway did not return a ciphertext ID")
        logical_length = (
            1 if operation in {"sum", "mean"} else left._logical_length
        )
        return RemoteCiphertext(
            self,
            self._session_id,
            ciphertext_id,
            logical_length,
        )

    def add(
        self, left: RemoteCiphertext, right: BinaryOperand
    ) -> RemoteCiphertext:
        return self._evaluate("add", left, right)

    def subtract(
        self, left: RemoteCiphertext, right: BinaryOperand
    ) -> RemoteCiphertext:
        return self._evaluate("subtract", left, right)

    def multiply(
        self, left: RemoteCiphertext, right: BinaryOperand
    ) -> RemoteCiphertext:
        return self._evaluate("multiply", left, right)

    def square(self, ciphertext: RemoteCiphertext) -> RemoteCiphertext:
        return self._evaluate("square", ciphertext)

    def sum(self, ciphertext: RemoteCiphertext) -> RemoteCiphertext:
        return self._evaluate("sum", ciphertext)

    def mean(self, ciphertext: RemoteCiphertext) -> RemoteCiphertext:
        return self._evaluate("mean", ciphertext)

    def variance_components(
        self, ciphertext: RemoteCiphertext
    ) -> VarianceComponents:
        self._owned(ciphertext)
        return VarianceComponents(
            sum_x=ciphertext.sum(),
            sum_x_square=ciphertext.square().sum(),
            count=ciphertext._logical_length,
        )

    def covariance_components(
        self,
        left: RemoteCiphertext,
        right: RemoteCiphertext,
    ) -> CovarianceComponents:
        self._owned(left)
        self._owned(right)
        if left._logical_length != right._logical_length:
            raise HEClientError(
                "ciphertexts must have the same logical length"
            )
        return CovarianceComponents(
            sum_x=left.sum(),
            sum_y=right.sum(),
            sum_xy=(left * right).sum(),
            count=left._logical_length,
        )

    def correlation_components(
        self,
        left: RemoteCiphertext,
        right: RemoteCiphertext,
    ) -> CorrelationComponents:
        self._owned(left)
        self._owned(right)
        if left._logical_length != right._logical_length:
            raise HEClientError(
                "ciphertexts must have the same logical length"
            )
        return CorrelationComponents(
            sum_x=left.sum(),
            sum_y=right.sum(),
            sum_x_square=left.square().sum(),
            sum_y_square=right.square().sum(),
            sum_xy=(left * right).sum(),
            count=left._logical_length,
        )

    def weighted_sum(
        self,
        ciphertext: RemoteCiphertext,
        weights: PublicVector,
    ) -> RemoteCiphertext:
        if not isinstance(weights, PublicVector):
            raise TypeError("weights must be a PublicVector")
        return (ciphertext * weights).sum()

    def risk_score(
        self,
        features: RemoteCiphertext,
        weights: PublicVector,
        bias: PublicScalar,
    ) -> RemoteCiphertext:
        if not isinstance(bias, PublicScalar):
            raise TypeError("bias must be a PublicScalar")
        return self.weighted_sum(features, weights) + bias

    def adjusted_net_total(
        self,
        income: list[float],
        expenses: list[float],
        adjustment: list[float],
    ) -> dict[str, Any]:
        """Run the isolated HEIR adjusted-net program through the gateway."""
        result = self._request(
            "POST",
            "/heir/adjusted-net",
            {
                "income": income,
                "expenses": expenses,
                "adjustment": adjustment,
            },
        )
        value = result.get("result")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise HEClientError("gateway did not return a HEIR numeric result")
        result["result"] = float(value)
        return result

    def decrypt(self, ciphertext: RemoteCiphertext) -> list[float]:
        self._owned(ciphertext)
        assert self._session_id is not None
        result = self._request(
            "POST",
            f"/sessions/{self._session_id}/decrypt",
            {"ciphertext_id": ciphertext._ciphertext_id},
        )
        values = result.get("values")
        if not isinstance(values, list):
            raise HEClientError("gateway did not return decrypted values")
        return [float(value) for value in values]

    def close(self) -> None:
        if self._closed:
            return
        if self._session_id is not None:
            self._request("DELETE", f"/sessions/{self._session_id}")
        self._closed = True
        self._session_id = None

    def __enter__(self) -> "HEClient":
        self._require_open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
