"""
NEXQA v1.0 — API Server

FastAPI backend for:
- Agent management (Retell; prompt reads on any provider)
- QA runs (Engine orchestration)
- Human QA sessions (Script distribution, feedback collection)
- Dashboard metrics

Usage:
  uvicorn nexqa.api.server:app --reload
"""

import hmac
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Dict

from nexqa.storage.config import Config
from nexqa.storage.database import close_db
from nexqa.storage.logger import logger


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Reject requests without valid API key. Skips /health for Render health checks."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path in ("/health", "/docs", "/openapi.json"):
            return await call_next(request)

        api_key = Config.NEXQA_API_KEY
        if not api_key:
            # No key configured = dev mode, allow all
            return await call_next(request)

        request_key = request.headers.get("X-API-Key", "")
        if not hmac.compare_digest(request_key, api_key):
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

        return await call_next(request)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Config.validate()
    if not Config.NEXQA_API_KEY:
        logger.warning(
            "NEXQA_API_KEY is not set: the API accepts unauthenticated requests. "
            "Set it before exposing the server beyond localhost."
        )
    logger.info(f"NEXQA API started (CORS origins: {_allowed_origins})")
    yield
    await close_db()
    logger.info("NEXQA API shutdown, MongoDB connection closed")


app = FastAPI(
    title="NEXQA API",
    version="1.0.0",
    description="Backend for Voice AI QA & Optimization Platform",
    lifespan=lifespan,
)

# CORS — read allowed origins from env var, fall back to localhost for dev
_raw_origins = Config.ALLOWED_ORIGINS
if _raw_origins:
    _allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]
else:
    _allowed_origins = ["http://localhost:3000", "http://localhost:3001"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(APIKeyMiddleware)

# Routes
from nexqa.api.routes import agents, runs, human_qa
app.include_router(agents.router, prefix="/agents", tags=["Agents"])
app.include_router(runs.router, prefix="/runs", tags=["Runs"])
app.include_router(human_qa.router, prefix="/human-qa", tags=["Human QA"])

@app.get("/health")
def health_check() -> Dict[str, str]:
    return {"status": "ok", "version": "1.0.0"}

@app.get("/voice-corpus/rules")
def get_voice_corpus_rules():
    """Return structured voice AI rules for external consumption.

    Lets an agent builder apply voice best practices while it creates
    an agent, before NEXQA ever tests it.
    """
    from nexqa.optimizer.voice_corpus import voice_corpus
    return voice_corpus.get_universal_rules()

if __name__ == "__main__":
    uvicorn.run("nexqa.api.server:app", host="127.0.0.1", port=8000, reload=True)
