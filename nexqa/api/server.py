"""
NEXQA v1.0 — API Server

FastAPI backend for:
- Agent management (Retell integration)
- QA runs (Engine orchestration)
- Human QA sessions (Script distribution, feedback collection)
- Dashboard metrics

Usage:
  uvicorn nexqa.api.server:app --reload
"""

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Dict

from nexqa.api import routes
from nexqa.storage.config import Config
from nexqa.storage.database import close_db
from nexqa.storage.logger import logger


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Reject requests without valid API key. Skips /health for Render health checks."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health" or request.url.path == "/docs" or request.url.path == "/openapi.json":
            return await call_next(request)

        api_key = Config.NEXQA_API_KEY
        if not api_key:
            # No key configured = dev mode, allow all
            return await call_next(request)

        request_key = request.headers.get("X-API-Key", "")
        if request_key != api_key:
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

        return await call_next(request)


app = FastAPI(
    title="NEXQA API",
    version="1.0.0",
    description="Backend for Voice AI QA & Optimization Platform",
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

    Used by Hermes AgentCompiler to apply voice best practices
    during agent creation (shift-left), preventing predictable
    NexQA test failures.
    """
    from nexqa.optimizer.voice_corpus import voice_corpus
    return voice_corpus.get_universal_rules()

@app.on_event("startup")
def startup_event():
    Config.validate()
    logger.info(f"NEXQA API Started (CORS origins: {_allowed_origins})")

@app.on_event("shutdown")
async def shutdown_event():
    await close_db()
    logger.info("NEXQA API shutdown — MongoDB connection closed")

if __name__ == "__main__":
    uvicorn.run("nexqa.api.server:app", host="0.0.0.0", port=8000, reload=True)
