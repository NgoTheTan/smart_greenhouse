"""Smoke test cấu hình khởi tạo: import được các module chính."""


def test_settings_load():
    from core.config import get_settings

    s = get_settings()
    assert s.mqtt_public_port == 8883


def test_api_app_routes():
    from api.main import app

    paths = set(app.openapi()["paths"].keys())
    assert "/api/health" in paths
    assert "/api/auth/login" in paths
    assert "/api/greenhouses/{gh_id}/commands" in paths
    assert "/api/nodes/{mac}/pair" in paths


def test_worker_subscriptions():
    from worker.main import SUBSCRIPTIONS

    assert "gh/+/+/telemetry/+" in SUBSCRIPTIONS
