from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

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


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
