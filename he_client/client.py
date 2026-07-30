"""Small HTTP client that presents remote ciphertexts as Python objects."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class HEClientError(RuntimeError):
    """Raised when the HE gateway rejects or cannot complete a request."""


@dataclass(frozen=True)
class RemoteCiphertext:
    """An opaque ciphertext stored in one trusted gateway session."""

    _client: "HEClient"
    _session_id: str
    _ciphertext_id: str

    def __add__(self, other: object) -> "RemoteCiphertext":
        if not isinstance(other, RemoteCiphertext):
            return NotImplemented
        return self._client.add(self, other)

    def __sub__(self, other: object) -> "RemoteCiphertext":
        if not isinstance(other, RemoteCiphertext):
            return NotImplemented
        return self._client.subtract(self, other)

    def __mul__(self, other: object) -> "RemoteCiphertext":
        if not isinstance(other, RemoteCiphertext):
            return NotImplemented
        return self._client.multiply(self, other)

    def decrypt(self) -> list[float]:
        return self._client.decrypt(self)

    def sum(self) -> "RemoteCiphertext":
        return self._client.sum(self)

    def mean(self) -> "RemoteCiphertext":
        return self._client.mean(self)

    def __repr__(self) -> str:
        return (
            f"RemoteCiphertext(session={self._session_id[:8]!r}, "
            f"id={self._ciphertext_id[:8]!r})"
        )


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

        return RemoteCiphertext(self, self._session_id, ciphertext_id)

    def _evaluate(
        self,
        operation: str,
        left: RemoteCiphertext,
        right: RemoteCiphertext | None = None,
    ) -> RemoteCiphertext:
        self._owned(left)
        if right is not None:
            self._owned(right)
        assert self._session_id is not None
        payload = {
            "operation": operation,
            "left": left._ciphertext_id,
        }
        if right is not None:
            payload["right"] = right._ciphertext_id
        result = self._request(
            "POST",
            f"/sessions/{self._session_id}/evaluate",
            payload,
        )
        ciphertext_id = result.get("ciphertext_id")
        if not isinstance(ciphertext_id, str):
            raise HEClientError("gateway did not return a ciphertext ID")
        return RemoteCiphertext(self, self._session_id, ciphertext_id)

    def add(
        self, left: RemoteCiphertext, right: RemoteCiphertext
    ) -> RemoteCiphertext:
        return self._evaluate("add", left, right)

    def subtract(
        self, left: RemoteCiphertext, right: RemoteCiphertext
    ) -> RemoteCiphertext:
        return self._evaluate("subtract", left, right)

    def multiply(
        self, left: RemoteCiphertext, right: RemoteCiphertext
    ) -> RemoteCiphertext:
        return self._evaluate("multiply", left, right)

    def sum(self, ciphertext: RemoteCiphertext) -> RemoteCiphertext:
        return self._evaluate("sum", ciphertext)

    def mean(self, ciphertext: RemoteCiphertext) -> RemoteCiphertext:
        return self._evaluate("mean", ciphertext)

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
