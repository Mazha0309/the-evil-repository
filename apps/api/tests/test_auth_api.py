from collections.abc import Generator

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import admin, auth, model_profiles
from app.database import Base, get_session


def build_client() -> TestClient:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    app = FastAPI()
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(admin.router, prefix="/api/v1")
    app.include_router(model_profiles.router, prefix="/api/v1")

    def override_session() -> Generator[Session, None, None]:
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    return TestClient(app)


def test_setup_login_registration_admin_and_tenant_model_scope() -> None:
    client = build_client()

    config = client.get("/api/v1/auth/config")
    assert config.status_code == 200
    assert config.json()["setup_required"] is True

    setup = client.post(
        "/api/v1/auth/setup",
        json={
            "username": "ADMIN",
            "password": "correct horse battery staple",
        },
    )
    assert setup.status_code == 201
    assert setup.json()["user"]["role"] == "admin"
    assert setup.json()["user"]["username"] == "admin"
    csrf = setup.json()["csrf_token"]

    rejected = client.patch(
        "/api/v1/admin/settings",
        json={"registration_enabled": True},
    )
    assert rejected.status_code == 403

    enabled = client.patch(
        "/api/v1/admin/settings",
        headers={"X-CSRF-Token": csrf},
        json={"registration_enabled": True},
    )
    assert enabled.status_code == 200
    assert enabled.json()["registration_enabled"] is True
    assert enabled.json()["runner_concurrency"] == 2

    concurrency = client.patch(
        "/api/v1/admin/settings",
        headers={"X-CSRF-Token": csrf},
        json={"runner_concurrency": 4},
    )
    assert concurrency.status_code == 200
    assert concurrency.json()["runner_concurrency"] == 4
    assert concurrency.json()["registration_enabled"] is True

    monitor = client.get("/api/v1/admin/monitor")
    assert monitor.status_code == 200
    assert monitor.json()["database"]["healthy"] is True

    logout = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert logout.status_code == 204

    registered = client.post(
        "/api/v1/auth/register",
        json={
            "username": "agent",
            "password": "another strong password",
        },
    )
    assert registered.status_code == 201
    user_csrf = registered.json()["csrf_token"]

    renamed = client.patch(
        "/api/v1/auth/me",
        headers={"X-CSRF-Token": user_csrf},
        json={"username": "测试员"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["username"] == "测试员"

    no_models = client.get("/api/v1/models")
    assert no_models.status_code == 200
    assert no_models.json() == []

    created = client.post(
        "/api/v1/models",
        headers={"X-CSRF-Token": user_csrf},
        json={
            "name": "My Claude",
            "provider": "anthropic",
            "base_url": "https://api.anthropic.com/v1",
            "model_id": "claude-test",
            "api_key": "secret",
            "native_tools": True,
            "parameters": {"max_tokens": 4096},
            "enabled": True,
        },
    )
    assert created.status_code == 201
    assert client.get("/api/v1/models").json()[0]["name"] == "My Claude"
    updated = client.patch(
        f"/api/v1/models/{created.json()['id']}",
        headers={"X-CSRF-Token": user_csrf},
        json={
            "name": "My Claude · high",
            "model_id": "claude-updated",
            "parameters": {
                "temperature": 0.2,
                "max_tokens": 16_384,
                "output_config": {"effort": "high"},
            },
            "native_tools": False,
            "enabled": False,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "My Claude · high"
    assert updated.json()["model_id"] == "claude-updated"
    assert updated.json()["parameters"]["output_config"]["effort"] == "high"
    assert updated.json()["has_api_key"] is True
    assert updated.json()["native_tools"] is False
    assert updated.json()["enabled"] is False

    cleared = client.patch(
        f"/api/v1/models/{created.json()['id']}",
        headers={"X-CSRF-Token": user_csrf},
        json={"api_key": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["has_api_key"] is False

    unsafe = client.post(
        "/api/v1/models",
        headers={"X-CSRF-Token": user_csrf},
        json={
            "name": "Unsafe profile",
            "provider": "openai_responses",
            "base_url": "https://api.openai.com/v1",
            "model_id": "gpt-test",
            "parameters": {"model": "attacker-controlled", "temperature": 3},
        },
    )
    assert unsafe.status_code == 422

    forbidden_admin = client.get("/api/v1/admin/users")
    assert forbidden_admin.status_code == 403

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["csrf_token"]


def test_login_is_case_insensitive_and_rate_limited() -> None:
    client = build_client()
    setup = client.post(
        "/api/v1/auth/setup",
        json={
            "username": "evil.admin",
            "password": "correct horse battery staple",
        },
    )
    csrf = setup.json()["csrf_token"]
    assert client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 204

    login = client.post(
        "/api/v1/auth/login",
        json={"username": "EVIL.ADMIN", "password": "correct horse battery staple"},
    )
    assert login.status_code == 200
    assert login.json()["user"]["username"] == "evil.admin"
    assert (
        client.post(
            "/api/v1/auth/logout",
            headers={"X-CSRF-Token": login.json()["csrf_token"]},
        ).status_code
        == 204
    )

    for _ in range(5):
        rejected = client.post(
            "/api/v1/auth/login",
            json={"username": "evil.admin", "password": "wrong password"},
        )
        assert rejected.status_code == 401
    limited = client.post(
        "/api/v1/auth/login",
        json={"username": "evil.admin", "password": "wrong password"},
    )
    assert limited.status_code == 429
