"""One shared HTTP client for every platform.

Croma sits behind Akamai, which rejects ordinary Python/curl TLS fingerprints
(HTTP 403) and even headless Chrome. curl_cffi impersonates a real Chrome TLS
handshake, which is enough to be served like a normal browser.

Some sites refuse cloud-server IP addresses outright (Myntra answers with a fake
"Site Maintenance" page; Flipkart's product pages answer 429). When PROXY_URL is set
(e.g. a residential proxy, http://user:pass@host:port), only those requests go through
it -- residential proxies are billed by bandwidth, and everything else works directly.
"""
from __future__ import annotations

import asyncio
import logging
import os
from urllib.parse import urlparse

from curl_cffi.requests import AsyncSession, Response

log = logging.getLogger(__name__)

_session: AsyncSession | None = None

DEFAULT_HEADERS = {
    "Accept-Language": "en-IN,en;q=0.9",
}


def session() -> AsyncSession:
    global _session
    if _session is None:
        _session = AsyncSession(impersonate="chrome", headers=DEFAULT_HEADERS, timeout=20)
    return _session


async def close() -> None:
    global _session
    if _session is not None:
        await _session.close()
        _session = None


class FetchError(Exception):
    pass


PROXY_URL = os.getenv("PROXY_URL", "").strip().strip("'\"").strip() or None  # tolerate pasted quotes/spaces
# Which blocked sites go through the proxy: "myntra,flipkart" (default) or just "myntra" to save
# bandwidth -- Myntra costs ~0.1 MB per lookup, Flipkart product pages ~1.4 MB each.
PROXY_SCOPE = {s.strip() for s in os.getenv("PROXY_SCOPE", "myntra,flipkart").split(",") if s.strip()}
# Product pages opened per lookup when they go through the proxy. Same as direct (10) by default:
# fewer pages measurably misses style-code matches (2 of 40 in the live answer-key test at 3).
# Lower it (e.g. 3) only to stretch a small proxy data allowance.
PROXIED_PAGE_CHECKS = int(os.getenv("PROXIED_PAGE_CHECKS", "10"))


def proxy_for(url: str) -> str | None:
    """The proxy to use for this URL, or None for a direct request."""
    if not PROXY_URL:
        return None
    u = urlparse(url)
    host = u.netloc.lower()
    if host.endswith("myntra.com") and "myntra" in PROXY_SCOPE:
        return PROXY_URL
    if host.endswith("flipkart.com") and "/p/" in u.path and "flipkart" in PROXY_SCOPE:
        return PROXY_URL  # product pages; search works directly
    return None


async def get(url: str, *, params: dict | None = None, headers: dict | None = None,
              retries: int = 2, ok_statuses: tuple[int, ...] = (200,)) -> Response:
    last: Exception | None = None
    proxy = proxy_for(url)
    if proxy:  # proxies are slower and occasionally stall: fail fast rather than make the user wait
        retries = min(retries, 1)
    for attempt in range(retries + 1):
        try:
            r = await session().get(url, params=params, headers=headers, allow_redirects=True, proxy=proxy,
                                    timeout=20)
            if r.status_code in ok_statuses:
                return r
            last = FetchError(f"HTTP {r.status_code} from {url.split('?')[0]}")
            if r.status_code in (401, 404, 410):  # asking again the same way won't change the answer
                break
        except Exception as e:  # network errors, timeouts
            last = FetchError(f"{type(e).__name__}: {e}")
        await asyncio.sleep(0.4 * (attempt + 1))
    assert last is not None
    raise last
