import os
import unittest
from unittest.mock import patch

from redis.exceptions import ConnectionError

from app import create_app


class FakeRedis:
    def __init__(self):
        self.visits = 0

    def ping(self):
        return True

    def incr(self, _key):
        self.visits += 1
        return self.visits


class BrokenRedis:
    def ping(self):
        raise ConnectionError("redis unavailable")

    def incr(self, _key):
        raise ConnectionError("redis unavailable")


class CounterApiTest(unittest.TestCase):
    def setUp(self):
        self.redis = FakeRedis()
        self.client = create_app(self.redis).test_client()

    def test_health_reports_connected_redis(self):
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")

    def test_visit_increments_persistent_counter(self):
        first = self.client.get("/api/visit")
        second = self.client.get("/api/visit")

        self.assertEqual(first.get_json()["visits"], 1)
        self.assertEqual(second.get_json()["visits"], 2)

    def test_info_uses_environment_configuration(self):
        with patch.dict(os.environ, {"APP_NAME": "demo", "APP_ENV": "test"}):
            response = self.client.get("/api/info")

        self.assertEqual(
            response.get_json()["application"],
            "demo",
        )
        self.assertEqual(response.get_json()["environment"], "test")

    def test_redis_failure_returns_service_unavailable(self):
        client = create_app(BrokenRedis()).test_client()

        self.assertEqual(client.get("/health").status_code, 503)
        self.assertEqual(client.get("/api/visit").status_code, 503)


if __name__ == "__main__":
    unittest.main()
