"""Smoke tests for the FastAPI application."""

from unittest.mock import patch

from fastapi.testclient import TestClient


def test_health_returns_ok():
    with patch("app.main.init_db", return_value=None):
        from app.main import app

        with TestClient(app) as client:
            response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "complass-service"


def test_app_has_correct_title():
    from app.main import app

    assert app.title == "合规罗盘后端服务"


def test_api_v1_routes_are_registered():
    from app.main import app

    routes = {r.path for r in app.routes}
    assert "/health" in routes
    api_routes = [p for p in routes if p.startswith("/api/v1/")]
    assert len(api_routes) > 0, "Expected at least one /api/v1/ route"


def test_cors_middleware_is_configured():
    from app.main import app

    cors_middlewares = [
        m for m in app.user_middleware
        if m.cls.__name__ == "CORSMiddleware"
    ]
    assert len(cors_middlewares) == 1
