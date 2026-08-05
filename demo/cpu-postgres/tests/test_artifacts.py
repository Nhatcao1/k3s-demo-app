from __future__ import annotations

from pathlib import Path
import sys
import unittest


DEMO_ROOT = Path(__file__).resolve().parents[1]
if str(DEMO_ROOT) not in sys.path:
    sys.path.insert(0, str(DEMO_ROOT))

from cpu_postgres_demo.artifacts import (  # noqa: E402
    ArtifactError,
    unwrap_secret_key,
    wrap_secret_key,
)


try:
    import cryptography  # noqa: F401
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False
else:
    CRYPTOGRAPHY_AVAILABLE = True


@unittest.skipUnless(CRYPTOGRAPHY_AVAILABLE, "cryptography is not installed")
class SecretKeyEnvelopeTests(unittest.TestCase):
    def test_round_trip_is_bound_to_session(self) -> None:
        key = b"w" * 32
        envelope = wrap_secret_key(b"private-material", key, "session-a")
        self.assertNotIn(b"private-material", envelope)
        self.assertEqual(
            unwrap_secret_key(envelope, key, "session-a"), b"private-material"
        )
        with self.assertRaises(Exception):
            unwrap_secret_key(envelope, key, "session-b")

    def test_wrong_key_is_rejected(self) -> None:
        envelope = wrap_secret_key(b"private-material", b"a" * 32, "session")
        with self.assertRaises(Exception):
            unwrap_secret_key(envelope, b"b" * 32, "session")


if __name__ == "__main__":
    unittest.main()
