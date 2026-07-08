import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

ALLOWED_SCHEMES = {"http", "https"}
BLOCKED_HOST_SUFFIXES = (".local", ".internal")
BLOCKED_HOSTNAMES = {"localhost"}


def is_valid_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in ALLOWED_SCHEMES and bool(parsed.netloc)


def _is_blocked_hostname(hostname: str) -> bool:
    host = hostname.lower().rstrip(".")
    if host in BLOCKED_HOSTNAMES:
        return True
    return any(host.endswith(suffix) for suffix in BLOCKED_HOST_SUFFIXES)


def _is_blocked_ip(value: str) -> bool:
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        return False
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


async def _resolve_host_ips(hostname: str) -> list[str]:
    try:
        loop = asyncio.get_running_loop()
        infos = await loop.getaddrinfo(
            hostname, None, type=socket.SOCK_STREAM
        )
    except socket.gaierror as exc:
        raise ValueError(f"DNS resolution failed: {exc}") from exc

    ips: list[str] = []
    for info in infos:
        ip = info[4][0]
        if ip not in ips:
            ips.append(ip)
    return ips


async def is_safe_url(url: str) -> tuple[bool, str | None]:
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES or not parsed.hostname:
        return False, "Invalid URL"

    hostname = parsed.hostname.lower()
    if _is_blocked_hostname(hostname):
        return False, "Blocked hostname"

    if _is_blocked_ip(hostname):
        return False, "Blocked IP address"

    try:
        resolved_ips = await _resolve_host_ips(hostname)
    except ValueError as exc:
        return False, str(exc)

    for ip in resolved_ips:
        if _is_blocked_ip(ip):
            return False, f"Blocked IP address: {ip}"

    return True, None


async def is_safe_redirect_url(url: str) -> tuple[bool, str | None]:
    return await is_safe_url(url)
