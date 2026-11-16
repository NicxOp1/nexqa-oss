from contextlib import asynccontextmanager

from fastapi import FastAPI
from webhook_server.router import router
from webhook_server.config import settings
import logging

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    log.info("NEXQA Webhook Server starting...")
    if not settings.verify_signatures:
        log.warning("VERIFY_SIGNATURES=false: webhook requests are NOT authenticated.")
    yield


app = FastAPI(
    title="NEXQA Webhook Server",
    lifespan=lifespan,
    description="Multi-tenant webhook server for Retell AI voice agents",
    version="1.0.0",
)

app.include_router(router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.host, port=settings.port)
