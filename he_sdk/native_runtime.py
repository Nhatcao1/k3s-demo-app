"""Protect one process from loading incompatible native HE runtimes."""

from __future__ import annotations

import threading

from he_sdk.errors import BackendUnavailableError


_lock = threading.Lock()
_selected_backend: str | None = None


def claim_native_runtime(backend: str) -> None:
    """Select the only in-process native HE runtime for this interpreter.

    The all-in-one installation contains both backend packages.  Importing
    both native OpenFHE implementations into one Python process is still
    unsafe because FIDESlib is compiled against its patched OpenFHE build.
    """
    global _selected_backend

    with _lock:
        if _selected_backend is None:
            _selected_backend = backend
            return
        if _selected_backend != backend:
            raise BackendUnavailableError(
                f"This process already loaded the {_selected_backend!r} HE "
                f"runtime and cannot also load {backend!r}. Start a fresh "
                "Python process to change CPU/GPU backend."
            )


__all__ = ["claim_native_runtime"]
