import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import accounts, analytics, auth, content, dashboard, media, monitoring, publishing
from app.config import settings
from app.db import init_db

logging.basicConfig(
    level=logging.INFO, format='{"level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}'
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logging.getLogger("api").info("API pronta")
    yield


app = FastAPI(title="X Content Panel", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (
    auth.router,
    accounts.router,
    monitoring.router,
    content.router,
    media.router,
    publishing.router,
    dashboard.router,
    analytics.router,
):
    app.include_router(router)


@app.get("/health")
async def health():
    return {"status": "ok"}
