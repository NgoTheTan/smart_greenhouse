# Feature: Mô hình dữ liệu miền, Crop Profiles, Cấu hình & Core PubSub (`platform/core/`)

> Nguồn đặc tả: `docs/greenhub-spec.md` mục 0, 1, 3.2, 6.1, 7, 7.1, 9, 12, 13.4; `docs/DECISIONS.md`.

## 1. Mục tiêu & Phạm vi

Định nghĩa mô hình dữ liệu chuyên biệt cho nhà kính thông minh (`Farm → User → Greenhouse → Gateway / Zone → CropProfile → DeviceNode`), bộ tham số sinh học có cấu hình (`parameters_json` với 2 thang thời gian `real` và `demo`), cấu hình tập trung qua `.env`, giao tiếp nội bộ `api ↔ worker` không cần Redis, và tiện ích bảo mật mật khẩu/JWT.

## 2. Trạng thái hiện thực trong repo

- **Đã hoàn thiện (M2):**
  - `platform/core/config.py`: `Settings` (`pydantic-settings`), đọc `.env` từ gốc repo hoặc CWD, cache qua `get_settings()`.
  - `platform/core/db.py`: `engine` SQLAlchemy async (`asyncpg`), `SessionLocal`, `Base`, `get_session()`.
  - `platform/core/models.py`: 18 ORM models SQLAlchemy 2.0 khớp toàn bộ 17 bảng nghiệp vụ trong spec mục 7 (cộng `Base`).
  - `platform/core/schemas.py`: toàn bộ MQTT payload schemas (`TelemetryPayload`, `GatewayStatusPayload`, `GatewayEventPayload`, `DiscoveryPayload`, `CommandMqttPayload`, `AckPayload`, `CfgPayload`) và REST schemas đã dùng ở M2 + `normalize_mac`.
  - `platform/core/crop_templates.py`: Pydantic validator `CropParameters` (`schema_version = 1`) và 4 template hệ thống (`SYSTEM_CROP_TEMPLATES`) với UUID cố định.
  - `platform/core/security.py`: Argon2id (`hash_password`, `verify_password`) và JWT HS256 (`create_access_token`, `decode_access_token`).
  - `platform/core/pubsub.py`: `pg_notify` (gọi trong transaction SQLAlchemy) và `listen_loop` (kết nối `asyncpg` riêng kèm ping 15 s & exponential backoff) cho `CHANNEL_WS = "ws_events"` và `CHANNEL_WORKER = "worker_events"`.
  - `platform/core/log.py`: cấu hình logging thống nhất theo `Settings.log_level`.
- **Cần bổ sung thêm khi làm M3–M5:**
  - Thêm Pydantic response/request schemas vào `platform/core/schemas.py` cho các endpoint M3–M5:
    - Cảnh báo: `AlertResponse`, `AlertFeedbackRequest` (`true_positive` | `false_positive`).
    - Web Push & Tuỳ chọn thông báo: `PushPublicKeyResponse`, `PushSubscribeRequest` (`endpoint`, `keys: {p256dh, auth}`, `user_agent`), `NotificationPrefUpdateRequest`, `NotificationPrefResponse`.
    - AI/ML & Thí nghiệm: `PredictionResponse`, `MlModelResponse`, `ExperimentCreateRequest`, `ExperimentResponse`, `ExperimentKpiResponse`.

## 3. Phân cấp mô hình miền & Bảng `crop_profiles`

### 3.1 Phân cấp sở hữu (Multi-tenant)
- `farms` (gốc tenant) → `users` (`farm_id`, `role ∈ {'owner','operator','viewer'}`).
- `farms` → `greenhouses` (`1 greenhouse = 1 gateway` qua `UNIQUE(greenhouse_id)` trên `gateways` và `1 device_state` qua `PRIMARY KEY(greenhouse_id)`).
- `greenhouses` → `zones` (`UNIQUE(greenhouse_id, zone_index)`, `zone_index = 1..N`, `pump_channel`, `control_strategy ∈ {'fixed','adaptive'}`, `soil_dry_raw`, `soil_wet_raw`).
- `device_nodes`: `mac_address` chuẩn `AA:BB:CC:DD:EE:01`, `status ∈ {'discovered','paired'}`.

### 3.2 Cấu trúc `crop_profiles.parameters_json` (`schema_version = 1`)

Được validate chặt qua `core.crop_templates.CropParameters`:

```json
{
  "schema_version": 1,
  "vpd": {"optimal": [0.8, 1.2], "low_crit": 0.4, "low_off": 0.6, "high_crit": 1.6, "leaf_offset_c": 1.0},
  "temp_c": {"optimal": [20.0, 28.0]},
  "soil_moisture_pct": {"min": 60.0, "max": 75.0},
  "disease": {"rh_gt": 85.0, "temp_range_c": [15.0, 25.0], "fungal_minutes_alert": 360},
  "irrigation": {"max_run_s": 300, "min_gap_s": 1800, "max_total_s_per_hour": 420, "soil_settle_s": 300},
  "fan": {"min_on_s": 300, "max_on_s": 1800},
  "mist": {"max_on_s": 900, "lockout_s": 900},
  "risk": {"vpd_low_duration_min": 60, "horizon_min": 120, "trend_windows_min": [30, 60]},
  "sample_interval_s": 60,
  "failsafe": {"temp_critical_high_c": 35.0, "soil_moisture_critical_low_pct": 30.0}
}
```

### 3.3 Bốn template hệ thống (`farm_id = NULL`, MUST)

| UUID cố định | `crop_name` | `variety` | `vpd.optimal` | `temp_c.optimal` | `soil_moisture_pct` | `failsafe.temp_critical_high_c` | `disease.rh_gt` |
|---|---|---|---|---|---|---|---|
| `00000000-0000-4000-8000-000000000001` | Cà chua bi | `real` | `[0.8, 1.2]` | `[20, 28]` | `[60, 75]` | `35.0` | `85.0` |
| `00000000-0000-4000-8000-000000000002` | Cà chua bi | `demo` | `[0.8, 1.2]` | `[20, 28]` | `[60, 75]` | `35.0` | `85.0` |
| `00000000-0000-4000-8000-000000000003` | Dâu tây | `real` | `[0.6, 0.9]` | `[18, 24]` | `[50, 65]` | `30.0` | `90.0` |
| `00000000-0000-4000-8000-000000000004` | Dâu tây | `demo` | `[0.6, 0.9]` | `[18, 24]` | `[50, 65]` | `30.0` | `90.0` |

*Lưu ý:* Cả 4 template dùng chung `vpd.low_crit = 0.4`, `low_off = 0.6`, `high_crit = 1.6`, `leaf_offset_c = 1.0`, `disease.temp_range_c = [15.0, 25.0]`, `failsafe.soil_moisture_critical_low_pct = 30.0`.

**So sánh 2 bộ tham số thời gian (`real` vs `demo`):**

| Tham số | `real` | `demo` | Ý nghĩa sử dụng |
|---|---|---|---|
| `sample_interval_s` | `60` | `10` | Chu kỳ gửi telemetry của node |
| `irrigation.max_run_s` | `300` | `15` | Thời gian chạy tối đa 1 lần bơm |
| `irrigation.min_gap_s` | `1800` | `90` | Khoảng nghỉ tối thiểu giữa 2 lần bơm |
| `irrigation.max_total_s_per_hour` | `420` | `120` | Tổng giây bơm tối đa trong 1 giờ |
| `irrigation.soil_settle_s` | `300` | `30` | Thời gian chờ đất thấm sau khi bơm |
| `fan.min_on_s` / `max_on_s` | `300` / `1800` | `60` / `300` | Thời lượng chạy tối thiểu / tối đa quạt |
| `mist.max_on_s` / `lockout_s` | `900` / `900` | `300` / `120` | Thời lượng tối đa máy tạo ẩm / khóa sau khi quạt bật |
| `risk.vpd_low_duration_min` | `60` | `3` | Thời gian VPD < `low_crit` liên tục để cảnh báo/bật quạt |
| `risk.horizon_min` | `120` | `15` | Chân trời dự báo rủi ro A3 |
| `risk.trend_windows_min` | `[30, 60]` | `[5, 15]` | Cửa sổ tính xu hướng đặc trưng AI |
| `disease.fungal_minutes_alert` | `360` | `5` | Số phút tích luỹ điều kiện nấm để bật `DISEASE_RISK` |

- **Quy tắc chỉnh sửa template hệ thống:** Khi owner gọi `PUT /api/crop-profiles/{id}` trên một template có `farm_id = NULL`, API **không** sửa bản hệ thống mà **clone** thành bản mới thuộc `user.farm_id`, chuyển các zone thuộc farm đang trỏ vào template cũ sang bản mới, rồi tăng `cfg_version_desired`.

## 4. Cấu hình & Giao tiếp nội bộ (`config.py`, `pubsub.py`, `security.py`)

### 4.1 Biến cấu hình chính trong `Settings`
- DB & Auth: `database_url`, `jwt_secret`, `jwt_algorithm="HS256"`, `jwt_expire_min=720`.
- MQTT: `mqtt_host` (Docker: `mosquitto`), `mqtt_port=1883`, `mqtt_public_host`, `mqtt_public_port=8883`, `mqtt_worker_user`, `mqtt_worker_password`, `mqtt_admin_user`, `mqtt_admin_password`.
- Push & Email: `vapid_public_key`, `vapid_private_key`, `vapid_subject`, `smtp_host`, `smtp_port=587`, `smtp_user`, `smtp_password`, `alert_email_from`.
- Nghiệp vụ & ML: `models_dir=Path("./models")` (trong Docker là `/models`), `command_expire_s=30`, `alert_cooldown_min=10`, `escalate_after_min=5`, `risk_forecast_threshold=0.7`.

### 4.2 Kênh PostgreSQL `LISTEN/NOTIFY`
- **`CHANNEL_WORKER = "worker_events"` (`api` → `worker`):**
  - `{"type": "command_created", "cmd_id": "<uuid>", "greenhouse_id": "<uuid>"}`
  - `{"type": "cfg_updated", "greenhouse_id": "<uuid>"}`
  - (M5 đề xuất): `{"type": "model_activated", "zone_id": "<uuid>", "task": "..."}` để worker hot-reload mô hình mới từ `ml.train`.
- **`CHANNEL_WS = "ws_events"` (`worker` → `api`):**
  - Payload nhỏ gọn JSON có `farm_id`, `type`, `data`. Dùng `pg_notify(session, ...)` **bên trong transaction** để đảm bảo sự kiện chỉ phát ra khi commit DB thành công.

### 4.3 Bảo mật cốt lõi (`security.py`)
- Mật khẩu băm bằng **Argon2id** (`argon2.PasswordHasher`).
- JWT ký HS256 chứa claims: `sub` (`user_id`), `farm_id`, `role`, `iat`, `exp`.

## 5. Kiểm tra & Xác nhận

- Unit tests tại `platform/tests/test_core_and_api_unit.py`:
  - `test_password_hash_and_jwt_roundtrip`
  - `test_system_crop_templates_valid`
  - `test_mac_normalization_and_command_validation`
  - `test_api_process_does_not_import_heavy_ml_libraries`
