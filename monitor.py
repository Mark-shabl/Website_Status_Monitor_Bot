from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

ALLOWED_SCHEMES = {"http", "https"}


def is_valid_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in ALLOWED_SCHEMES and bool(parsed.netloc)


def check_website(url: str, timeout: int = 10, user_agent: str = "SiteMonitorBot/1.0") -> dict:
    """Checks a single URL and returns a result dict.

    Mirrors the spec's check_website(): status_code/is_ok/response_time on
    success, or an error string on timeout/connection/other failures.
    """
    try:
        response = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": user_agent},
            allow_redirects=True,
        )
        return {
            "url": url,
            "status_code": response.status_code,
            "is_ok": response.status_code == 200,
            "response_time": response.elapsed.total_seconds(),
            "timestamp": datetime.now(timezone.utc),
            "error": None,
        }
    except requests.exceptions.Timeout:
        return {
            "url": url,
            "status_code": None,
            "is_ok": False,
            "response_time": None,
            "timestamp": datetime.now(timezone.utc),
            "error": "Timeout",
        }
    except requests.exceptions.ConnectionError:
        return {
            "url": url,
            "status_code": None,
            "is_ok": False,
            "response_time": None,
            "timestamp": datetime.now(timezone.utc),
            "error": "Connection Error",
        }
    except Exception as e:
        return {
            "url": url,
            "status_code": None,
            "is_ok": False,
            "response_time": None,
            "timestamp": datetime.now(timezone.utc),
            "error": str(e),
        }
