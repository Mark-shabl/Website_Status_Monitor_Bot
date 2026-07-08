from unittest.mock import AsyncMock, patch

import pytest

import security


@pytest.mark.asyncio
async def test_blocks_localhost():
    ok, reason = await security.is_safe_url("http://localhost/admin")
    assert ok is False
    assert reason is not None


@pytest.mark.asyncio
async def test_blocks_private_ip_literal():
    ok, reason = await security.is_safe_url("http://127.0.0.1/")
    assert ok is False
    assert "Blocked IP" in reason


@pytest.mark.asyncio
async def test_blocks_private_resolved_ip():
    with patch(
        "security._resolve_host_ips",
        AsyncMock(return_value=["127.0.0.1"]),
    ):
        ok, reason = await security.is_safe_url("http://example.com")

    assert ok is False
    assert "127.0.0.1" in reason


@pytest.mark.asyncio
async def test_allows_public_url():
    with patch(
        "security._resolve_host_ips",
        AsyncMock(return_value=["93.184.216.34"]),
    ):
        ok, reason = await security.is_safe_url("https://example.com")

    assert ok is True
    assert reason is None
