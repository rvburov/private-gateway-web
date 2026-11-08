"""Проверка собранного локального стека без создания пользователей."""

import json
from urllib.error import HTTPError
from urllib.request import urlopen

ORIGIN = "http://127.0.0.1:8080"


def read(path: str):
    return urlopen(ORIGIN + path, timeout=10)  # noqa: S310 — фиксированный loopback


with read("/api/ready") as response:
    assert response.status == 200

with read("/") as response:
    assert response.status == 200
    assert "text/html" in response.headers["Content-Type"]
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]

with read("/client/runtime.html") as response:
    assert response.status == 200
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert "frame-ancestors 'self'" in response.headers["Content-Security-Policy"]

with read("/api/auth/csrf") as response:
    payload = json.load(response)
    assert isinstance(payload.get("csrf_token"), str)
    assert "Set-Cookie" in response.headers

try:
    read("/api/downloads")
except HTTPError as error:
    assert error.code == 401, error.code
else:
    raise AssertionError("Неавторизованный запрос получил каталог загрузок")

print("5 проверок локального Docker-стека: PASS")
