# Feature: Device Shadow & Đồng bộ cấu hình `cfg` có phiên bản (`platform/worker/shadow.py`)

> Nguồn đặc tả: `docs/greenhub-spec.md` mục 4.3, 5, 6.1, 6.3, 9, 15 (Kịch bản C); `docs/DECISIONS.md`.

## 1. Mục tiêu & Phạm vi

Quản lý cặp trạng thái **Device Shadow** (`device_state.desired` và `device_state.reported`) cho mỗi nhà kính, đồng thời biên dịch cấu hình từ DB (`zones`, `crop_profiles`, `device_nodes`) thành bản tin `cfg` có số phiên bản tăng dần (`cfg_version_desired`) và publish dạng **MQTT retained** xuống Gateway.

## 2. Trạng thái hiện thực trong repo

- **Đã hoàn thiện (M2):**
  - `platform/worker/shadow.py`:
    - `ensure_device_state(session, greenhouse_id)`
    - `bump_cfg_version(session, greenhouse_id)`
    - `build_gateway_cfg(session, greenhouse_id)` → sinh `CfgPayload` đầy đủ.
    - `ShadowPublisher` (`reset_cache`, `publish_cfg`, `sync_unsynced`).
  - Kích hoạt tức thời qua `worker_events` (`type = "cfg_updated"`) khi gọi `POST /gateways`, `POST /nodes/{mac}/pair`, `PUT /zones/{id}/calibration`, `PUT /zones/{id}` (đổi crop profile), `PUT /crop-profiles/{id}`, và `tools/seed_dev.py`.
  - Đồng bộ bù định kỳ mỗi 5 s (`scheduler.py`: `sync_unsynced`) và ngay khi `worker` reconnect MQTT.

## 3. Cấu trúc Device Shadow (`device_state`)

Mỗi `greenhouse_id` có đúng 1 dòng trong `device_state`:
- **`desired` (JSONB):** Lưu chế độ điều khiển từng actuator (`modes`) và trạng thái mong muốn:
  ```json
  {
    "modes": {
      "pump_1": {"mode": "auto", "until": null},
      "pump_2": {"mode": "auto", "until": null},
      "fan": {"mode": "manual", "until": "2026-10-14T08:30:00+00:00"},
      "mist": {"mode": "auto", "until": null}
    }
  }
  ```
  - Mặc định khi chưa có key trong `modes`: coi là `"auto"`.
  - Khi `mode == "manual"` và `until` đã quá hạn (`until <= now`), `worker.commands.expire_manual_modes()` trong tick 5 s tự động trả về `{"mode": "auto", "until": None}`.
- **`reported` (JSONB):** Cập nhật từ 2 nguồn của gateway:
  1. `status` (heartbeat 30 s): `actuators`, `uptime_s`, `heap`, `queue_len`, `nodes`.
  2. `ack/{cmd_id}`: cập nhật ngay `reported["actuators"]` theo `payload.state` (kể cả `side_effects` như `mist_off`).
- **`cfg_version_desired` vs `cfg_version_reported`:**
  - `cfg_version_desired`: khởi tạo `1` khi tạo nhà kính; tăng `+1` qua `bump_cfg_version()` mỗi khi thay đổi node ghép, hiệu chuẩn đất, crop profile của zone hoặc tham số crop profile.
  - `cfg_version_reported`: cập nhật từ trường `cfg_version` trong gói `status` của gateway.
  - Trạng thái trên API (`GET /api/greenhouses/{id}/config-sync`) & Web Console:
    - `synced = (cfg_version_reported >= cfg_version_desired)` → hiển thị `"Đã đồng bộ"` / `"Đang chờ đồng bộ"`.

## 4. Payload `cfg` (MQTT Retained, QoS 1)

Topic: `gh/{farm_id}/{greenhouse_id}/cfg` (`retain=True`, `qos=1`).

```json
{
  "cfg_version": 3,
  "offline_failsafe_after_s": 60,
  "nodes": [
    {"mac": "AA:BB:CC:DD:EE:01", "zone": 1},
    {"mac": "AA:BB:CC:DD:EE:02", "zone": 2}
  ],
  "zones": [
    {
      "zone": 1,
      "pump": "pump_1",
      "sample_interval_s": 10,
      "soil_cal": {"dry_raw": 2900, "wet_raw": 1300},
      "limits": {
        "irrigation_max_run_s": 15,
        "irrigation_min_gap_s": 90,
        "irrigation_max_total_s_per_hour": 120,
        "fan_max_on_s": 300,
        "mist_max_on_s": 300
      },
      "failsafe": {
        "temp_critical_high_c": 35.0,
        "soil_moisture_critical_low_pct": 30.0
      }
    }
  ]
}
```

### Quy tắc ánh xạ trong `build_gateway_cfg`
- `nodes`: chỉ lấy các `DeviceNode` thuộc `greenhouse_id` có `status == 'paired'` và `zone_id IS NOT NULL`, sắp xếp theo `mac_address`.
- `zones`: lấy tất cả `Zone` của nhà kính (sắp xếp theo `zone_index`), join `CropProfile` (fallback `DEFAULT_DEMO_PARAMS` nếu chưa gắn profile).
- `pump`: `f"pump_{zone.pump_channel or zone.zone_index}"`.
- `soil_cal`: dùng `zone.soil_dry_raw` (fallback `2900`) và `zone.soil_wet_raw` (fallback `1300`).

## 5. Cơ chế đồng bộ & tối ưu phát lại (`ShadowPublisher`)

- `ShadowPublisher._published_versions` lưu `cfg_version` đã publish lên Mosquitto trong phiên kết nối MQTT hiện tại (bị xóa bởi `reset_cache()` mỗi lần worker reconnect broker).
- Khi nhận `worker_events` (`cfg_updated`): gọi `publish_cfg(..., force=True)` để ép gửi ngay xuống Mosquitto.
- Trong `sync_unsynced()` (tick 5 s): tìm mọi nhà kính có `cfg_version_desired > cfg_version_reported`, gọi `publish_cfg(..., force=False)` → tránh spam Mosquitto mỗi 5 s nếu cùng version đã được publish retained trên broker rồi (gateway chỉ cần kết nối lại và subscribe `cfg` là tự động nhận ngay bản retained từ Mosquitto!).

## 6. Kiểm tra & Xác nhận

- Khi cập nhật `soil_dry_raw` hoặc ghép node mới, `cfg_version_desired` tăng, worker publish `cfg` retained ngay (< 1 s nhờ `pg_notify`), gateway/simulator nhận được và phản hồi `status` mới → `GET /config-sync` trả `synced: true`.
- Khi gateway mất kết nối rồi kết nối lại (Kịch bản C), broker tự gửi lại `cfg` retained mới nhất và gateway đồng bộ lại `cfg_version_reported`.
