from __future__ import annotations

import asyncio
import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import http, service
from .amazon import AmazonError
from .models import MatchResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
STATIC = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await http.close()


app = FastAPI(title="Same product, other platforms", lifespan=lifespan)


class MatchRequest(BaseModel):
    url: str


@app.post("/api/match", response_model=MatchResponse)
async def api_match(req: MatchRequest) -> MatchResponse:
    try:
        return await service.match(req.url)
    except AmazonError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True}


# Fixed, read-only probes: can this server reach each platform, and does it get real data back?
# (Sites treat cloud servers differently from home connections; this shows how, per platform.)
_PROBES = {
    "amazon_product": "https://www.amazon.in/dp/B0CHX1W1XY",
    "flipkart_search": "https://www.flipkart.com/search?q=apple+iphone+15",
    "flipkart_product": "https://www.flipkart.com/adidas-grand-court-3-0-sneakers-men/p/itm7feb0e2e799fe?pid=SHOHJJ8KMECR4HZM",
    "croma_search_api": "https://api.croma.com/searchservices/v1/search?currentPage=0&query=iphone%2015%3Arelevance&fields=FULL&channel=WEB&channelCode=400049",
    "myntra_search_page": "https://www.myntra.com/puma-smashic?rawQuery=puma%20smashic",
    "myntra_search_api": "https://www.myntra.com/gateway/v2/search/puma-smashic?rawQuery=puma%20smashic&rows=5&o=0",
}
_MARKERS = {"amazon_product": "productTitle", "flipkart_search": "__INITIAL_STATE__", "flipkart_product": "Article Number",
            "croma_search_api": '"products"', "myntra_search_page": "__myx", "myntra_search_api": '"products"'}


@app.get("/api/diag")
async def diag() -> dict:
    async def probe(name: str, url: str) -> dict:
        try:
            headers = {"x-meta-app": "channel=web", "x-myntraweb": "Yes"} if "gateway" in url else None
            if "gateway" in url:  # the API needs the homepage's cookies
                await http.session().get("https://www.myntra.com/", proxy=http.proxy_for(url), timeout=25)
            r = await http.session().get(url, headers=headers, allow_redirects=True, proxy=http.proxy_for(url),
                                         timeout=25)
            title = re.search(r"<title[^>]*>([^<]{0,80})", r.text or "")
            return {"status": r.status_code, "bytes": len(r.text or ""), "has_data": _MARKERS[name] in (r.text or ""),
                    "title": title.group(1).strip() if title else None, "via_proxy": bool(http.proxy_for(url))}
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"[:200]}

    results = dict(zip(_PROBES, await asyncio.gather(*(probe(n, u) for n, u in _PROBES.items()))))
    if http.PROXY_URL:  # where does the proxy exit? (Cloudflare's trace page reports the visitor's IP/country)
        try:
            r = await http.session().get("https://www.cloudflare.com/cdn-cgi/trace", proxy=http.PROXY_URL, timeout=15)
            info = dict(line.split("=", 1) for line in r.text.split() if "=" in line)
            results["proxy_exit"] = {k: info.get(k) for k in ("loc", "colo")}
        except Exception as e:
            results["proxy_exit"] = {"error": f"{type(e).__name__}: {e}"[:200]}
    results["proxy_scope"] = sorted(http.PROXY_SCOPE) if http.PROXY_URL else None
    results["proxy_config"] = _describe_proxy(os.getenv("PROXY_URL"))
    return results


def _describe_proxy(raw: str | None) -> dict | None:
    """The shape of the configured PROXY_URL without revealing it: enough to spot a pasting mistake
    (stray quotes/spaces, a cut-off username, a wrong port) by comparing with the provider's dashboard."""
    if not raw:
        return None
    u = urlsplit(raw.strip().strip("'\""))
    return {"scheme": u.scheme, "host": u.hostname, "port": u.port,
            "username_length": len(u.username or ""), "username_ends_with": (u.username or "")[-10:],
            "password_length": len(u.password or ""),
            "raw_has_spaces_or_quotes": raw != raw.strip() or any(c in raw for c in " '\"\n"),
            "raw_starts_with": raw[:7]}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
