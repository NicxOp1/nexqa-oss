from fastapi import FastAPI
from webhook_server.router import router
from webhook_server.config import settings
import logging

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

app = FastAPI(
    title="NEXQA Webhook Server",
    description="Multi-tenant webhook server for Retell AI voice agents",
    version="1.0.0",
)

app.include_router(router)


@app.on_event("startup")
async def startup():
    logging.getLogger(__name__).info("NEXQA Webhook Server starting...")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.host, port=settings.port)
