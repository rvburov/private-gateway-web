"""Общая проверка метаданных файлов из манифеста выпуска клиента."""

import json
import re

ASSET_MAX_BYTES = 2 * 1024**3
FILE_NAME = re.compile(r"[A-Za-z0-9_~+-][A-Za-z0-9._~+-]{0,199}")
SHA256 = re.compile(r"[0-9a-f]{64}")


def asset_metadata(value: object) -> dict | None:
    """Имя без пути, SHA-256 и размер с теми же пределами, что у программы."""
    if not isinstance(value, dict):
        return None
    name, sha256, size = value.get("file"), value.get("sha256"), value.get("size")
    if not isinstance(name, str) or not FILE_NAME.fullmatch(name):
        return None
    if not isinstance(sha256, str) or not SHA256.fullmatch(sha256):
        return None
    if type(size) is not int or not 1 <= size <= ASSET_MAX_BYTES:
        return None
    return {"file": name, "sha256": sha256, "size": size}


def manifest_assets(manifest: bytes) -> dict[str, dict]:
    """Только проверенные метаданные; неизвестные виды фильтрует вызывающая сторона."""
    try:
        assets = json.loads(manifest).get("assets")
    except (ValueError, AttributeError):
        return {}
    if not isinstance(assets, dict):
        return {}
    found = {}
    for kind, value in assets.items():
        asset = asset_metadata(value)
        if asset is not None:
            found[kind] = asset
    return found
