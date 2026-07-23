from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import dashboard, model_profiles, reports, runs, tasks
from app.config import get_settings
from app.database import SessionLocal, create_schema
from app.seed import seed_canonical_task


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_schema()
    with SessionLocal() as session:
        seed_canonical_task(session)
    yield


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Control plane for evidence-hostile, container-isolated AI agent evaluation.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin, "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
for api_router in [
    dashboard.router,
    tasks.router,
    model_profiles.router,
    runs.router,
    reports.router,
]:
    app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "evil-repository-api"}
