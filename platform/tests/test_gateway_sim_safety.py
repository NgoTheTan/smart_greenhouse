"""Unit tests cho quy tắc an toàn tại Gateway: bơm, quạt, tự tắt, hết hạn (T5–T6, T10)."""

import uuid
from datetime import UTC, datetime, timedelta

from tools.simulator.gateway_client import GatewaySafetyEngine


def _cmd(
    actuator: str,
    action: str,
    duration_s: int | None = 20,
    expires_offset_s: int = 30,
    cmd_id: str | None = None,
) -> tuple[dict, datetime]:
    now = datetime(2026, 11, 5, 12, 0, 0, tzinfo=UTC)
    return (
        {
            "cmd_id": cmd_id or str(uuid.uuid4()),
            "actuator": actuator,
            "action": action,
            "duration_s": duration_s,
            "expires_at": (now + timedelta(seconds=expires_offset_s)).isoformat(),
            "source": "manual",
        },
        now,
    )


def test_fan_duration_cap_and_reject_unsupported_mist() -> None:
    """Từ chối thiết bị không hỗ trợ (mist) và chặn trần thời lượng bật quạt."""
    eng = GatewaySafetyEngine()

    c_mist, now = _cmd("mist", "on", duration_s=60)
    ack_mist = eng.apply_command(c_mist, now, now_mono=0.0)
    assert ack_mist is not None
    assert ack_mist["status"] == "rejected"
    assert ack_mist["reason"] == "invalid"
    assert "mist" not in eng.actuators

    # Chặn duration_s ở fan_max_on_s = 300s và tự tắt khi hết hạn
    c_fan, now = _cmd("fan", "on", duration_s=600)
    ack_fan = eng.apply_command(c_fan, now, now_mono=0.0)
    assert ack_fan is not None
    assert ack_fan["status"] == "applied"
    assert ack_fan["side_effects"] == []
    assert eng.actuators == {"pump_1": "off", "pump_2": "off", "fan": "on", "light": "off"}
    assert eng.tick(299.0) == []
    assert eng.tick(300.0) == ["fan"]
    assert eng.actuators["fan"] == "off"

    # Đèn chiếu sáng bật/tắt hợp lệ và bị giới hạn tối đa fan_max_on_s
    c_light, now = _cmd("light", "on", duration_s=60)
    ack_light = eng.apply_command(c_light, now, now_mono=301.0)
    assert ack_light is not None and ack_light["status"] == "applied"
    assert eng.actuators["light"] == "on"
    c_light_off, now = _cmd("light", "off", duration_s=None)
    ack_light_off = eng.apply_command(c_light_off, now, now_mono=310.0)
    assert ack_light_off is not None and ack_light_off["status"] == "applied"
    assert eng.actuators["light"] == "off"


def test_pump_duration_cap_auto_off_and_min_gap_max_total() -> None:
    """Tests T5 & T6: bơm tự tắt đúng max_run_s, chặn min_gap_s và max_total_s_per_hour."""
    eng = GatewaySafetyEngine()
    eng.apply_cfg(
        {
            "cfg_version": 2,
            "zones": [
                {
                    "zone": 1,
                    "pump": "pump_1",
                    "sample_interval_s": 10,
                    "limits": {
                        "irrigation_max_run_s": 15,
                        "irrigation_min_gap_s": 90,
                        "irrigation_max_total_s_per_hour": 30,
                        "fan_max_on_s": 300,
                    },
                }
            ],
        }
    )

    # Yêu cầu 60s -> tự chặn ở max_run_s = 15s
    c1, now = _cmd("pump_1", "on", duration_s=60)
    ack1 = eng.apply_command(c1, now, now_mono=0.0)
    assert ack1 is not None and ack1["status"] == "applied"
    assert eng.tick(14.0) == []
    assert eng.tick(15.0) == ["pump_1"]
    assert eng.actuators["pump_1"] == "off"

    # Chưa đủ min_gap_s = 90s (mới nghỉ 30s tại t=45) -> rejected min_gap
    c2, now = _cmd("pump_1", "on", duration_s=15)
    ack2 = eng.apply_command(c2, now, now_mono=45.0)
    assert ack2 is not None and ack2["status"] == "rejected" and ack2["reason"] == "min_gap"

    # Đủ min_gap tại t=110 -> chạy thêm 15s (tổng 30s/30s trong giờ), tự tắt ở t=125
    c3, now = _cmd("pump_1", "on", duration_s=15)
    ack3 = eng.apply_command(c3, now, now_mono=110.0)
    assert ack3 is not None and ack3["status"] == "applied"
    eng.tick(125.0)

    # Lần 3 tại t=250 (đã qua min_gap nhưng chạm max_total 30s/giờ) -> rejected max_total
    c4, now = _cmd("pump_1", "on", duration_s=10)
    ack4 = eng.apply_command(c4, now, now_mono=250.0)
    assert ack4 is not None and ack4["status"] == "rejected" and ack4["reason"] == "max_total"


def test_expired_and_duplicate_command_handling() -> None:
    """Test T10: lệnh hết hạn trả expired; gửi trùng cmd_id bị bỏ qua (idempotent)."""
    eng = GatewaySafetyEngine()
    cid = str(uuid.uuid4())
    c_exp, now = _cmd("fan", "on", duration_s=30, expires_offset_s=-2, cmd_id=cid)
    ack = eng.apply_command(c_exp, now, now_mono=0.0)
    assert ack is not None and ack["status"] == "expired"
    assert eng.actuators["fan"] == "off"

    # Trùng cmd_id -> bỏ qua
    assert eng.apply_command(c_exp, now, now_mono=1.0) is None
