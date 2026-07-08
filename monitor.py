import asyncio
import logging
from datetime import datetime, timezone

import httpx

import security

logger = logging.getLogger(__name__)

TRANSIENT_ERRORS = {"Timeout", "Connection Error"}


def is_valid_url(url: str) -> bool:
    return security.is_valid_url(url)


def _make_result(
    url: str,
    *,
    status_code: int | None,
    is_ok: bool,
    response_time: float | None,
    error: str | None,
) -> dict:
    return {
        "url": url,
        "status_code": status_code,
        "is_ok": is_ok,
        "response_time": response_time,
        "timestamp": datetime.now(timezone.utc),
        "error": error,
    }


def _is_transient(result: dict) -> bool:
    if result.get("status_code") is not None:
        return False
    error = result.get("error") or ""
    if error in TRANSIENT_ERRORS:
        return True
    return error.startswith("Request error:")


async def check_website(
    client: httpx.AsyncClient,
    url: str,
    timeout: int = 10,
    user_agent: str = "SiteMonitorBot/1.0",
) -> dict:
    safe, reason = await security.is_safe_url(url)
    if not safe:
        return _make_result(
            url,
            status_code=None,
            is_ok=False,
            response_time=None,
            error=reason or "Blocked URL",
        )

    try:
        response = await client.get(
            url,
            timeout=timeout,
            headers={"User-Agent": user_agent},
            follow_redirects=True,
        )
        return _make_result(
            url,
            status_code=response.status_code,
            is_ok=response.status_code == 200,
            response_time=response.elapsed.total_seconds(),
            error=None,
        )
    except httpx.TimeoutException:
        return _make_result(
            url,
            status_code=None,
            is_ok=False,
            response_time=None,
            error="Timeout",
        )
    except httpx.ConnectError:
        return _make_result(
            url,
            status_code=None,
            is_ok=False,
            response_time=None,
            error="Connection Error",
        )
    except httpx.HTTPError as exc:
        return _make_result(
            url,
            status_code=None,
            is_ok=False,
            response_time=None,
            error=f"Request error: {exc}",
        )
    except Exception as exc:
        return _make_result(
            url,
            status_code=None,
            is_ok=False,
            response_time=None,
            error=str(exc),
        )


async def check_website_with_retry(
    client: httpx.AsyncClient,
    url: str,
    timeout: int,
    user_agent: str,
    max_retries: int,
    retry_delay: int,
    rate_limiter,
) -> dict:
    attempts = max(1, max_retries)
    result: dict | None = None

    for attempt in range(attempts):
        await rate_limiter.wait_for_host(url)
        result = await check_website(client, url, timeout, user_agent)
        if not _is_transient(result) or attempt == attempts - 1:
            return result
        await asyncio.sleep(retry_delay)

    return result  # type: ignore[return-value]


def build_http_client(user_agent: str) -> httpx.AsyncClient:
    async def on_request(request: httpx.Request) -> None:
        safe, reason = await security.is_safe_redirect_url(str(request.url))
        if not safe:
            raise httpx.RequestError(f"Blocked redirect: {reason or 'unsafe URL'}")

    return httpx.AsyncClient(
        event_hooks={"request": [on_request]},
        follow_redirects=True,
        headers={"User-Agent": user_agent},
    )
