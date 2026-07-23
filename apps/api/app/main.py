from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, auth, dashboard, model_profiles, reports, runs, suites, tasks
from app.config import get_settings
from app.database import SessionLocal, create_schema
from app.platform import ensure_platform_settings
from app.seed import seed_canonical_task
from app.version import VERSION


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_schema()
    with SessionLocal() as session:
        ensure_platform_settings(session)
        seed_canonical_task(session)
        session.commit()
    yield


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version=VERSION,
    description=(
        "Control plane for evidence-grounded, container-isolated, "
        "repository-scale AI incident-response evaluation."
    ),
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin, "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
for api_router in [
    auth.router,
    admin.router,
    dashboard.router,
    suites.router,
    tasks.router,
    model_profiles.router,
    runs.router,
    reports.router,
]:
    app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "evil-repository-api", "version": VERSION}
