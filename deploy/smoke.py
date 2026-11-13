"""Проверка собранного стека без создания пользователей.

По умолчанию — локальный стенд http://127.0.0.1:8080. Рабочий стек за общим входом —
PGWEB_SMOKE_ORIGIN=https://<домен>; PGWEB_SMOKE_INSECURE=1 только для проверочного
сертификата CI. Для HTTPS дополнительно проверяются HSTS и cookie с префиксом __Host-.
"""

import json
import os
import ssl
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import urlopen

ORIGIN = os.environ.get("PGWEB_SMOKE_ORIGIN", "http://127.0.0.1:8080").rstrip("/")
HTTPS = ORIGIN.startswith("https://")
assert urlsplit(ORIGIN).scheme in {"http", "https"}, ORIGIN
CONTEXT = ssl.create_default_context()
if os.environ.get("PGWEB_SMOKE_INSECURE") == "1":
    CONTEXT.check_hostname = False
    CONTEXT.verify_mode = ssl.CERT_NONE


def read(path: str):
    return urlopen(ORIGIN + path, timeout=10, context=CONTEXT)  # noqa: S310 — адрес проверки


with read("/api/ready") as response:
    assert response.status == 200

with read("/") as response:
    assert response.status == 200
    assert "text/html" in response.headers["Content-Type"]
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert "Server" not in response.headers
    if HTTPS:
        assert response.headers["Strict-Transport-Security"].startswith("max-age=")

with read("/client/runtime.html") as response:
    assert response.status == 200
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert "frame-ancestors 'self'" in response.headers["Content-Security-Policy"]

with read("/api/auth/csrf") as response:
    payload = json.load(response)
    assert isinstance(payload.get("csrf_token"), str)
    assert "Set-Cookie" in response.headers
    if HTTPS:
        cookie = response.headers["Set-Cookie"]
        assert cookie.startswith("__Host-csrf=") and "Secure" in cookie, cookie

try:
    read("/api/downloads")
except HTTPError as error:
    assert error.code == 401, error.code
else:
    raise AssertionError("Неавторизованный запрос получил каталог загрузок")

# Лента обновлений: без токена устройства — 401, поддельный билет на файл — 403
try:
    read("/api/app/updates?platform=windows")
except HTTPError as error:
    assert error.code == 401, error.code
else:
    raise AssertionError("Лента обновлений ответила без токена устройства")

try:
    read("/api/app/updates/files/AAAA." + "A" * 43)
except HTTPError as error:
    assert error.code == 403, error.code
    assert json.load(error) == {"error": {"code": "invalid_ticket"}}
else:
    raise AssertionError("Поддельный билет получил файл обновления")

print(f"7 проверок стека {ORIGIN}: PASS")
