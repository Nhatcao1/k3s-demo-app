"""Result-only proxy re-encryption types.

The analyst secret key does not decrypt ciphertexts created under the data
owner's key.  The owner/release authority re-encrypts only approved aggregate
results to the analyst key.  Keep this release authority separate from the
compute worker: PRE keys are ciphertext-wide and are not function-bound.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from he_sdk.ciphertext import CiphertextMetadata
from he_sdk.errors import IncompatibleCiphertextError, ResultReleaseError


ALLOWED_RESULT_OPERATIONS = frozenset({"sum", "mean", "variance"})


@dataclass(frozen=True, repr=False)
class ReleasedResult:
    """An aggregate scalar re-encrypted from the owner key to one analyst."""

    metadata: CiphertextMetadata
    recipient_id: str
    _handle: Any = field(repr=False, compare=False)

    def __repr__(self) -> str:
        return (
            "ReleasedResult("
            f"operation={self.metadata.result_operation!r}, "
            f"recipient={self.recipient_id[:8]!r}, "
            f"context={self.metadata.context_id[:8]!r})"
        )


class ResultRecipient:
    """Analyst key boundary that can decrypt only PRE-released results.

    This object deliberately exposes no generic ciphertext decryption method.
    More importantly, its native secret key differs from the owner key, so an
    owner ciphertext is not decryptable even if an analyst bypasses this SDK's
    Python type checks and calls OpenFHE directly.
    """

    def __init__(
        self,
        *,
        recipient_id: str,
        context_id: str,
        context_fingerprint: str,
        session_id: str,
        public_key: Any,
        secret_key: Any,
        decryptor: Callable[[Any, Any, int], list[float]],
    ) -> None:
        self.recipient_id = recipient_id
        self.context_id = context_id
        self.context_fingerprint = context_fingerprint
        self._session_id = session_id
        self._public_key = public_key
        self._secret_key = secret_key
        self._decryptor = decryptor

    def __repr__(self) -> str:
        return (
            "ResultRecipient("
            f"recipient={self.recipient_id[:8]!r}, "
            f"context={self.context_id[:8]!r})"
        )

    def decrypt(self, value: ReleasedResult) -> float:
        """Decrypt one aggregate that was explicitly released to this key."""
        if not isinstance(value, ReleasedResult):
            raise ResultReleaseError(
                "analyst keys accept only ReleasedResult objects; owner input "
                "ciphertexts are not analyst-decryptable"
            )
        if value.recipient_id != self.recipient_id:
            raise IncompatibleCiphertextError(
                "released result belongs to a different analyst key"
            )
        if value.metadata.context_id != self.context_id:
            raise IncompatibleCiphertextError(
                "released result belongs to a different HE context"
            )
        if value.metadata.context_fingerprint != self.context_fingerprint:
            raise IncompatibleCiphertextError(
                "released result uses a different HE configuration"
            )
        if value.metadata.result_operation not in ALLOWED_RESULT_OPERATIONS:
            raise ResultReleaseError(
                "released result has no approved aggregate provenance"
            )
        plaintext = self._decryptor(value._handle, self._secret_key, 1)
        if not plaintext:
            raise RuntimeError("backend returned an empty released result")
        return float(plaintext[0])
