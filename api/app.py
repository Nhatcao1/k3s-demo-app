import os
import socket

from flask import Flask, jsonify
from redis import Redis
from redis.exceptions import RedisError


def create_app(redis_connection=None):
    application = Flask(__name__)
    redis_client = redis_connection or Redis(
        host=os.getenv("REDIS_HOST", "redis"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )

    @application.get("/health")
    def health():
        try:
            redis_client.ping()
            return jsonify(status="ok", redis="connected"), 200
        except RedisError as exc:
            return jsonify(status="degraded", error=str(exc)), 503

    @application.get("/api/visit")
    def visit():
        try:
            visits = redis_client.incr("visits")
            return jsonify(
                visits=visits,
                hostname=socket.gethostname(),
                environment=os.getenv("APP_ENV", "unknown"),
            )
        except RedisError as exc:
            return jsonify(error=str(exc)), 503

    @application.get("/api/info")
    def info():
        return jsonify(
            application=os.getenv("APP_NAME", "counter-api"),
            environment=os.getenv("APP_ENV", "unknown"),
            hostname=socket.gethostname(),
        )

    return application


app = create_app()
