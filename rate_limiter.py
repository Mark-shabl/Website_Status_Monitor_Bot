import asyncio
import time
from urllib.parse import urlparse


class HostRateLimiter:
    def __init__(self, min_interval: float) -> None:
        self._min_interval = min_interval
        self._last_request: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    async def _get_lock(self, host: str) -> asyncio.Lock:
        async with self._global_lock:
            if host not in self._locks:
                self._locks[host] = asyncio.Lock()
            return self._locks[host]

    async def wait_for_host(self, url: str) -> None:
        host = urlparse(url).hostname
        if not host:
            return

        host = host.lower()
        lock = await self._get_lock(host)
        async with lock:
            now = time.monotonic()
            last = self._last_request.get(host)
            if last is not None:
                remaining = self._min_interval - (now - last)
                if remaining > 0:
                    await asyncio.sleep(remaining)
            self._last_request[host] = time.monotonic()
