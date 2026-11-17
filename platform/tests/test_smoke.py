"""Smoke test cấu hình khởi tạo: import được các module chính & bất biến firmware."""

from pathlib import Path

from core.quality import FLAG_AHT_ERR, FLAG_BH_ERR, FLAG_SOIL_ERR, QualityConfig

REPO_ROOT = Path(__file__).resolve().parents[2]


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


def test_firmware_invariants_and_completeness():
    packets_h = (
        REPO_ROOT / "firmware" / "common" / "gh_common" / "src" / "gh_packets.h"
    ).read_text(encoding="utf-8")
    config_h = (
        REPO_ROOT / "firmware" / "common" / "gh_common" / "src" / "gh_config.h"
    ).read_text(encoding="utf-8")
    node_ini = (REPO_ROOT / "firmware" / "node" / "platformio.ini").read_text(encoding="utf-8")
    node_cpp = (REPO_ROOT / "firmware" / "node" / "src" / "main.cpp").read_text(encoding="utf-8")
    gw_cpp = (REPO_ROOT / "firmware" / "gateway" / "src" / "main.cpp").read_text(encoding="utf-8")

    # Cờ lỗi gói tin ESP-NOW phải khớp bitmask trong core.quality
    assert FLAG_AHT_ERR == 1
    assert FLAG_SOIL_ERR == 2
    assert FLAG_BH_ERR == 4
    assert "FLAG_AHT_ERR = 1 << 0" in packets_h
    assert "FLAG_SOIL_ERR = 1 << 1" in packets_h
    assert "FLAG_BH_ERR = 1 << 2" in packets_h
    assert "GH_AIR_T_NONE" in packets_h
    assert "GH_AIR_RH_NONE" in packets_h
    assert "sizeof(TelemetryPkt) == 20" in packets_h
    assert "sizeof(CfgPkt) == 10" in packets_h

    # Dải vật lý & chu kỳ đo khớp QualityConfig
    q_cfg = QualityConfig()
    assert f"SOIL_RAW_MIN = {q_cfg.soil_raw_min}" in config_h
    assert f"SOIL_RAW_MAX = {q_cfg.soil_raw_max}" in config_h
    assert "CFG_RX_WINDOW_MS = 200" in config_h
    assert "SENSOR_MEASURE_INTERVAL_S = 5" in config_h
    assert f"SPIKE_AIR_T_C = {q_cfg.spike_air_t_c}f" in config_h
    assert f"SPIKE_AIR_RH_PCT = {q_cfg.spike_air_rh_pct}f" in config_h

    # Không còn TODO(M1) bỏ trống và đầy đủ luồng chính cho Node (ESP32/ESP8266) & Gateway
    assert "TODO(M1)" not in node_cpp
    assert "TODO(M1)" not in gw_cpp
    for env_name in ("[env:node_dht11]", "[env:node_esp8266]"):
        assert env_name in node_ini
    for token in (
        "Adafruit_AHTX0",
        "USE_SHT30",
        "USE_DHT11",
        "NO_AIR_SENSOR",
        "NO_LIGHT_SENSOR",
        "ESP8266",
        "BH1750",
        "esp_deep_sleep",
        "readSoilMedianRaw",
        "SENSOR_MEASURE_INTERVAL_S",
    ):
        assert token in node_cpp
    for token in (
        "WiFiManager",
        "setCACert",
        "PubSubClient",
        "initRelaysOff",
        "handleCommandPayload",
        "tickFailsafeAndBuzzer",
        "findSharedAirSample",
        "preprocessZoneTelemetry",
        "SENSOR_MEASURE_INTERVAL_S",
        "MQTT_QUEUE_SIZE",
    ):
        assert token in gw_cpp
