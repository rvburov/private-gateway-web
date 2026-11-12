"""Сведения о подключении для списков устройств и журналов: без лишних персональных данных."""

import ipaddress

from fastapi import Request


def mask_ip(value: str | None) -> str | None:
    """Адрес без последних октетов: видно сеть, но не конкретного абонента."""
    try:
        address = ipaddress.ip_address(value or "")
    except ValueError:
        return None
    prefix = 24 if address.version == 4 else 48
    network = ipaddress.ip_network(f"{address}/{prefix}", strict=False)
    return f"{network.network_address}/{prefix}"


def user_agent(request: Request) -> str | None:
    value = request.headers.get("user-agent", "").strip()
    return value[:300] if value else None


def device_label(agent: str | None) -> str:
    """Короткое имя «браузер · ОС» из User-Agent для списка устройств."""
    if not agent:
        return "—"
    systems = (
        ("Android", "Android"),
        ("iPhone", "iOS"),
        ("iPad", "iPadOS"),
        ("Windows", "Windows"),
        ("Mac OS X", "macOS"),
        ("Macintosh", "macOS"),
        ("CrOS", "ChromeOS"),
        ("Linux", "Linux"),
    )
    browsers = (
        ("Edg/", "Edge"),
        ("OPR/", "Opera"),
        ("YaBrowser/", "Yandex"),
        ("Firefox/", "Firefox"),
        ("Chrome/", "Chrome"),
        ("Safari/", "Safari"),
    )
    system = next((name for marker, name in systems if marker in agent), "")
    browser = next((name for marker, name in browsers if marker in agent), "")
    return " · ".join(part for part in (browser, system) if part) or agent[:40]
