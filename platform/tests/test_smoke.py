"""Smoke test cấu hình khởi tạo: import được các module chính."""


def test_settings_load():
    from core.config import get_settings

    s = get_settings()
    assert s.mqtt_public_port == 8883


def test_api_app_routes():
    from api.main import app

    paths = {r.path for r in app.routes}
    assert "/api/health" in paths


def test_worker_subscriptions():
    from worker.main import SUBSCRIPTIONS

    assert "gh/+/+/telemetry/+" in SUBSCRIPTIONS
