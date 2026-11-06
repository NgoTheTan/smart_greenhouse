"""Unit tests cho quy tắc an toàn tại Gateway: interlock, bơm, tự tắt, hết hạn (T3–T6, T10)."""

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


def test_interlock_fan_overrides_mist_and_blocks_mist_when_fan_on() -> None:
    """Tests T3 & T4: bật quạt tắt máy tạo ẩm (side_effects); bật mist khi quạt chạy bị chặn."""
    eng = GatewaySafetyEngine()

    c1, now = _cmd("mist", "on", duration_s=60)
    ack1 = eng.apply_command(c1, now, now_mono=0.0)
    assert ack1 is not None and ack1["status"] == "applied"
    assert eng.actuators["mist"] == "on"

    # T3: bật quạt khi mist đang chạy -> mist tự tắt + side_effects=["mist_off"]
    c2, now = _cmd("fan", "on", duration_s=60)
    ack2 = eng.apply_command(c2, now, now_mono=5.0)
    assert ack2 is not None
    assert ack2["status"] == "applied"
    assert ack2["side_effects"] == ["mist_off"]
    assert eng.actuators == {"pump_1": "off", "pump_2": "off", "fan": "on", "mist": "off"}

    # T4: bật mist khi fan đang chạy -> rejected (interlock)
    c3, now = _cmd("mist", "on", duration_s=30)
    ack3 = eng.apply_command(c3, now, now_mono=10.0)
    assert ack3 is not None
    assert ack3["status"] == "rejected"
    assert ack3["reason"] == "interlock"


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
                        "mist_max_on_s": 300,
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
