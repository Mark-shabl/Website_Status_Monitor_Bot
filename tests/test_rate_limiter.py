import time

import pytest

from rate_limiter import HostRateLimiter


@pytest.mark.asyncio
async def test_rate_limiter_enforces_interval():
    limiter = HostRateLimiter(min_interval=0.2)

    await limiter.wait_for_host("https://example.com/a")
    start = time.monotonic()
    await limiter.wait_for_host("https://example.com/b")
    elapsed = time.monotonic() - start

    assert elapsed >= 0.15


@pytest.mark.asyncio
async def test_rate_limiter_different_hosts_parallel():
    limiter = HostRateLimiter(min_interval=0.2)

    await limiter.wait_for_host("https://a.example.com")
    start = time.monotonic()
    await limiter.wait_for_host("https://b.example.com")
    elapsed = time.monotonic() - start

    assert elapsed < 0.1
