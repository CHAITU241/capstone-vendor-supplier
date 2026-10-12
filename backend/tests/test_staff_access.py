"""Reviewer and admin authentication can be enabled independently for demos."""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.database import Base, get_db
from app.main import app


def _client(settings: Settings):
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def db_override():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_settings] = lambda: settings
    return engine, TestClient(app)


def test_staff_workspaces_are_one_click_by_default():
    engine, client = _client(Settings(_env_file=None))
    try:
        with client:
            config = client.get("/api/portal/auth/config")
            assert config.json() == {"reviewer_auth_enabled": False, "admin_auth_enabled": False}
            assert client.post("/api/portal/auth/reviewer-demo").status_code == 200
            assert client.post("/api/portal/auth/admin-demo").status_code == 200
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_staff_credentials_are_enforced_when_enabled():
    settings = Settings(
        _env_file=None,
        reviewer_auth_enabled=True,
        reviewer_email="reviewer@example.com",
        reviewer_password="reviewer-password",
        admin_auth_enabled=True,
        admin_email="admin@example.com",
        admin_password="admin-password",
    )
    engine, client = _client(settings)
    try:
        with client:
            assert client.post("/api/portal/auth/reviewer-demo").status_code == 403
            assert client.post("/api/portal/auth/admin-demo").status_code == 403
            reviewer = client.post("/api/portal/auth/reviewer", json={"email": "reviewer@example.com", "password": "reviewer-password"})
            admin = client.post("/api/portal/auth/admin", json={"email": "admin@example.com", "password": "admin-password"})
            assert reviewer.status_code == 200 and reviewer.json()["role"] == "reviewer"
            assert admin.status_code == 200 and admin.json()["role"] == "admin"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
