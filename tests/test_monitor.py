import httpx
import pytest
import respx
from unittest.mock import AsyncMock, patch

import monitor
from rate_limiter import HostRateLimiter


@pytest.mark.asyncio
@respx.mock
@patch("monitor.security.is_safe_url", AsyncMock(return_value=(True, None)))
async def test_check_website_success():
    respx.get("https://example.com").mock(return_value=httpx.Response(200))

    async with httpx.AsyncClient() as client:
        result = await monitor.check_website(client, "https://example.com")

    assert result["is_ok"] is True
    assert result["status_code"] == 200
    assert result["response_time"] is not None


@pytest.mark.asyncio
@respx.mock
@patch("monitor.security.is_safe_url", AsyncMock(return_value=(True, None)))
async def test_check_website_http_error():
    respx.get("https://example.com/missing").mock(return_value=httpx.Response(404))

    async with httpx.AsyncClient() as client:
        result = await monitor.check_website(client, "https://example.com/missing")

    assert result["is_ok"] is False
    assert result["status_code"] == 404


@pytest.mark.asyncio
@respx.mock
@patch("monitor.security.is_safe_url", AsyncMock(return_value=(True, None)))
async def test_check_website_timeout():
    respx.get("https://slow.example.com").mock(side_effect=httpx.TimeoutException("timeout"))

    async with httpx.AsyncClient() as client:
        result = await monitor.check_website(client, "https://slow.example.com")

    assert result["is_ok"] is False
    assert result["error"] == "Timeout"


@pytest.mark.asyncio
@respx.mock
@patch("monitor.security.is_safe_url", AsyncMock(return_value=(True, None)))
async def test_check_website_with_retry_recovers():
    route = respx.get("https://flaky.example.com")
    route.side_effect = [
        httpx.ConnectError("down"),
        httpx.Response(200),
    ]

    async with httpx.AsyncClient() as client:
        limiter = HostRateLimiter(0)
        result = await monitor.check_website_with_retry(
            client,
            "https://flaky.example.com",
            timeout=5,
            user_agent="TestBot/1.0",
            max_retries=2,
            retry_delay=0,
            rate_limiter=limiter,
        )

    assert result["is_ok"] is True
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
@patch("monitor.security.is_safe_url", AsyncMock(return_value=(True, None)))
async def test_check_website_with_retry_exhausted():
    respx.get("https://down.example.com").mock(side_effect=httpx.ConnectError("down"))

    async with httpx.AsyncClient() as client:
        limiter = HostRateLimiter(0)
        result = await monitor.check_website_with_retry(
            client,
            "https://down.example.com",
            timeout=5,
            user_agent="TestBot/1.0",
            max_retries=3,
            retry_delay=0,
            rate_limiter=limiter,
        )

    assert result["is_ok"] is False
    assert result["error"] == "Connection Error"


def test_is_valid_url():
    assert monitor.is_valid_url("https://example.com") is True
    assert monitor.is_valid_url("ftp://example.com") is False
    assert monitor.is_valid_url("not-a-url") is False
