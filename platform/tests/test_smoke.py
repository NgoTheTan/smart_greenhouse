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
    assert "/api/zones/{zone_id}/cycles" in paths
    assert "/api/greenhouses/{gh_id}/recommendations" in paths
    assert "/api/models" in paths
    assert "/api/models/active" in paths
    assert "/api/experiments" not in paths
    assert not any("yield-samples" in p or "yield_samples" in p for p in paths)


def test_worker_subscriptions():
    from worker.main import SUBSCRIPTIONS

    assert "gh/+/+/telemetry/+" in SUBSCRIPTIONS
