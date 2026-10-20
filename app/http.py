"""One shared HTTP client for every platform.

Croma sits behind Akamai, which rejects ordinary Python/curl TLS fingerprints
(HTTP 403) and even headless Chrome. curl_cffi impersonates a real Chrome TLS
handshake, which is enough to be served like a normal browser.
"""
from __future__ import annotations

import asyncio
import logging

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


async def get(url: str, *, params: dict | None = None, headers: dict | None = None,
              retries: int = 2, ok_statuses: tuple[int, ...] = (200,)) -> Response:
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            r = await session().get(url, params=params, headers=headers, allow_redirects=True)
            if r.status_code in ok_statuses:
                return r
            last = FetchError(f"HTTP {r.status_code} from {url.split('?')[0]}")
            if r.status_code in (404, 410):
                break
        except Exception as e:  # network errors, timeouts
            last = FetchError(f"{type(e).__name__}: {e}")
        await asyncio.sleep(0.4 * (attempt + 1))
    assert last is not None
    raise last
