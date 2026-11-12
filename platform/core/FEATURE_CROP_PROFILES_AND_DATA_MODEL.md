# Feature: Mô hình dữ liệu miền, Crop Profiles, Cấu hình & Core PubSub (`platform/core/`)

> Nguồn đặc tả: `docs/greenhub-spec.md` mục 0, 1, 3.2, 6.1, 7, 7.1, 8.2, 9, 12, 13.4; `docs/DECISIONS.md`.

## 1. Mục tiêu & Phạm vi

Định nghĩa mô hình dữ liệu chuyên biệt cho nhà kính thông minh (`Farm → User → Greenhouse → Gateway / Zone → CropProfile → CropCycle / DeviceNode`), dữ liệu huấn luyện gộp nhiều nhà kính (`yield_samples`), mô hình toàn cục (`ml_models`) và dự báo/gợi ý (`predictions`), bộ tham số sinh học có cấu hình (`parameters_json` `schema_version = 2` với 2 thang thời gian `real` và `demo`), cấu hình tập trung qua `.env`, giao tiếp nội bộ `api ↔ worker` qua PostgreSQL `LISTEN/NOTIFY` (không Redis), và tiện ích bảo mật mật khẩu/JWT.

## 2. Trạng thái hiện thực trong repo

- **Khởi tạo nền tảng (M2):**
  - `platform/core/config.py`: `Settings` (`pydantic-settings`), đọc `.env` từ gốc repo hoặc CWD, cache qua `get_settings()`.
  - `platform/core/db.py`: `engine` SQLAlchemy async (`asyncpg`), `SessionLocal`, `Base`, `get_session()`.
  - `platform/core/models.py`: ORM models SQLAlchemy 2.0 (nền tảng M2, cần nâng cấp lên 18 bảng nghiệp vụ ở M3–M5).
  - `platform/core/schemas.py`: toàn bộ MQTT payload schemas (`TelemetryPayload`, `GatewayStatusPayload`, `GatewayEventPayload`, `DiscoveryPayload`, `CommandMqttPayload`, `AckPayload`, `CfgPayload`) và REST schemas cơ bản + `normalize_mac`.
  - `platform/core/crop_templates.py`: Pydantic validator `CropParameters` và `SYSTEM_CROP_TEMPLATES` với UUID cố định (nâng cấp từ 4 template `schema_version = 1` lên 10 template `schema_version = 2`).
  - `platform/core/security.py`: Argon2id (`hash_password`, `verify_password`) và JWT HS256 (`create_access_token`, `decode_access_token`).
  - `platform/core/pubsub.py`: `pg_notify` (gọi trong transaction SQLAlchemy) và `listen_loop` (kết nối `asyncpg` riêng kèm ping 15 s & exponential backoff) cho `CHANNEL_WS = "ws_events"` và `CHANNEL_WORKER = "worker_events"`.
  - `platform/core/log.py`: cấu hình logging thống nhất theo `Settings.log_level`.
- **Cần cập nhật / bổ sung khi làm M3–M5:**
  - `platform/core/crop_templates.py`: nâng cấp `CropParameters` lên `schema_version = 2` (bổ sung `light.dli_optimal`, `cycle.days`, `yield.reference_kg_m2`, `ai.*`; nhóm `risk` chỉ còn `vpd_low_duration_min`) và đủ **10 template hệ thống** (5 cây × 2 bộ `real`/`demo`).
  - `platform/core/models.py` (kèm Alembic migration): cập nhật từ khung M2 lên đầy đủ 18 bảng nghiệp vụ ở mục 3.1 (thêm `crop_profiles.crop_code`, `zones.area_m2`, bảng `crop_cycles`, `yield_samples`; dọn các cột/bảng của cơ chế cũ ở `zones`/`alerts`; cập nhật `ml_models` toàn cục và `predictions`).
  - `platform/core/climate_features.py`: trích 16 đặc trưng khí hậu (`feature_version = 1`) bằng Python thuần (xem [FEATURE_MICROCLIMATE_AND_QUALITY.md](./FEATURE_MICROCLIMATE_AND_QUALITY.md)).
  - `platform/core/schemas.py`: bổ sung/cập nhật Pydantic schemas cho M3–M5:
    - Cảnh báo: `AlertResponse`.
    - Web Push & Tuỳ chọn thông báo: `PushPublicKeyResponse`, `PushSubscribeRequest` (`endpoint`, `keys: {p256dh, auth}`, `user_agent`), `NotificationPrefUpdateRequest`, `NotificationPrefResponse`.
    - Zone: `ZoneUpdateRequest` (`name`, `crop_profile_id`, `area_m2`), `ZoneResponse` (thêm `area_m2`).
    - Vụ trồng & AI năng suất / gợi ý: `CropCycleCreateRequest`, `CropCycleHarvestRequest`, `CropCycleResponse`, `PredictionResponse`, `CropRecommendationResponse`, `RefreshRecommendationResponse`, `MlModelResponse`.
  - `platform/core/config.py`: dọn biến cấu hình không còn dùng, bổ sung `tz: str = "Asia/Ho_Chi_Minh"`.

## 3. Phân cấp mô hình miền, Schema CSDL & Bảng `crop_profiles`

### 3.1 Phân cấp sở hữu (Multi-tenant), Cập nhật ORM & Cô lập dữ liệu
- **Phân cấp tenant:**
  - `farms` (gốc tenant) → `users` (`farm_id`, `role ∈ {'owner','operator','viewer'}`).
  - `farms` → `greenhouses` (`1 greenhouse = 1 gateway` qua `UNIQUE(greenhouse_id)` trên `gateways` và `1 device_state` qua `PRIMARY KEY(greenhouse_id)`).
  - `greenhouses` → `zones` (`UNIQUE(greenhouse_id, zone_index)`, `zone_index = 1..N`, `pump_channel`, `area_m2`, `soil_dry_raw`, `soil_wet_raw`).
  - `zones` → `crop_cycles` (vụ trồng theo zone; tối đa 1 vụ `status = 'active'` trên mỗi zone).
  - `device_nodes`: `mac_address` chuẩn `AA:BB:CC:DD:EE:01`, `status ∈ {'discovered','paired'}`.
- **18 bảng nghiệp vụ trong `platform/core/models.py` (cộng `Base`):**
  - Nhóm cốt lõi & thiết bị giữ nguyên cấu trúc: `farms`, `users`, `greenhouses`, `gateways`, `device_nodes`, `readings` (TimescaleDB hypertable), `commands`, `actuator_logs`, `device_state`, `push_subscriptions`, `notification_prefs`.
  - Các bảng được cập nhật / thêm / bỏ so với khung M2 ban đầu:
    - **`crop_profiles`** (`CropProfile`): `crop_code VARCHAR(40) NOT NULL` (`tomato_cherry | strawberry | lettuce | cucumber | bell_pepper`), `schema_version INT NOT NULL DEFAULT 2`.
    - **`zones`** (`Zone`): `id`, `greenhouse_id`, `zone_index`, `name`, `crop_profile_id`, `area_m2 REAL` (diện tích canh tác, m²), `planting_date`, `pump_channel`, `soil_dry_raw`, `soil_wet_raw` (chỉ còn một chiến lược điều khiển hysteresis cố định nên không có cột chọn chiến lược).
    - **`alerts`** (`Alert`): giữ các cột vòng đời cảnh báo (`id`, `greenhouse_id`, `zone_id`, `alert_type`, `severity`, `state`, `dedupe_key`, `payload`, `created_at`, `notified_at`, `escalated_at`, `acknowledged_at`, `acked_by`, `resolved_at`).
    - **Thêm `crop_cycles`** (`CropCycle` – dữ liệu tenant):
      - `id` UUID PK, `zone_id` FK→`zones.id` NOT NULL, `crop_profile_id` FK→`crop_profiles.id` NOT NULL, `started_at` TIMESTAMPTZ NOT NULL, `harvested_at` TIMESTAMPTZ, `area_m2` REAL NOT NULL (`CHECK (area_m2 > 0)`), `yield_kg` REAL (`CHECK (yield_kg >= 0)`), `status` VARCHAR(10) NOT NULL DEFAULT `'active'` (`CHECK (status IN ('active','harvested','abandoned'))`), `notes` TEXT, `created_by` FK→`users.id`, `created_at` TIMESTAMPTZ NOT NULL.
      - Partial unique index `crop_cycles_one_active` trên `(zone_id) WHERE status = 'active'`.
    - **Thêm `yield_samples`** (`YieldSample` – tập huấn luyện gộp nhiều nhà kính):
      - `id` UUID PK, `source` VARCHAR(10) NOT NULL (`CHECK (source IN ('real','sim','synthetic','public'))`), `greenhouse_key` VARCHAR(100) NOT NULL (UUID nhà kính platform hoặc mã ngoài như `'syn-0042'`), `farm_id` FK→`farms.id` (`NULL` với dữ liệu ngoài platform), `crop_cycle_id` UUID UNIQUE FK→`crop_cycles.id` (nullable), `crop_code` VARCHAR(40) NOT NULL, `started_at` TIMESTAMPTZ, `ended_at` TIMESTAMPTZ, `cycle_days` REAL, `feature_version` INT NOT NULL, `features` JSONB NOT NULL, `coverage` REAL, `yield_kg_m2` REAL NOT NULL (`CHECK (yield_kg_m2 >= 0)`), `meta` JSONB (ví dụ `region`, `oracle_relative_yields`), `created_at` TIMESTAMPTZ NOT NULL.
      - Index trên `(crop_code)` và `(greenhouse_key)`.
    - **Cập nhật `ml_models`** (`MlModel` – mô hình toàn cục):
      - **Bỏ** `zone_id`, `train_from`, `train_to` và unique constraint cũ theo zone.
      - Các cột: `id` UUID PK, `task` VARCHAR(30) NOT NULL DEFAULT `'yield'`, `version` INT NOT NULL, `feature_version` INT NOT NULL, `artifact_path` TEXT NOT NULL, `trained_at` TIMESTAMPTZ NOT NULL, `n_samples` INT, `n_greenhouses` INT, `source_mix` JSONB (`{"synthetic":n,"sim":m,"real":k,"public":p}`), `crops` JSONB (`[{"crop_code":"lettuce","n":412,"reference_kg_m2":3.0}]`), `metrics` JSONB (trên tập test nhà kính chưa thấy + theo cây + theo `source` + `top1`/`ndcg3`), `baseline_metrics` JSONB (`{"B0":{...},"B1":{...}}`), `is_active` BOOLEAN NOT NULL DEFAULT `false`, `notes` TEXT.
      - Ràng buộc `UNIQUE (task, version)`.
    - **Cập nhật `predictions`** (`Prediction`):
      - Khóa chính `id` UUID PK; thêm `greenhouse_id` UUID NOT NULL FK→`greenhouses.id`, `crop_cycle_id` UUID FK→`crop_cycles.id` (chỉ dùng cho `yield_forecast`), đặt `zone_id` FK→`zones.id` là nullable (chỉ dùng cho `yield_forecast`).
      - `task` VARCHAR(30) NOT NULL `CHECK (task IN ('yield_forecast','crop_recommendation'))`, `ts` TIMESTAMPTZ NOT NULL, `model_id` FK→`ml_models.id`, `value` REAL (`kg/m²` dự kiến với `yield_forecast`), `score` REAL (`relative_yield` với `yield_forecast` / điểm top-1 với `crop_recommendation`), `details` JSONB.
      - Ràng buộc `CHECK (task <> 'yield_forecast' OR zone_id IS NOT NULL)` và index `(greenhouse_id, task, ts DESC)`.
- **Cô lập tenant & Ràng buộc bộ nhớ (MUST):**
  - Mọi endpoint API lọc dữ liệu nghiệp vụ theo `farm_id` của người dùng ở tầng ứng dụng.
  - `yield_samples` chứa dữ liệu gộp từ nhiều nhà kính và **không bao giờ** được trả qua bất kỳ API nào; `GET /models` chỉ trả số liệu tổng hợp (`n_samples`, `n_greenhouses`, `source_mix`, `crops`, `metrics`, `baseline_metrics`). Huấn luyện tập trung trên dữ liệu gộp nhiều nhà kính để tạo một mô hình toàn cục là quyết định kiến trúc có chủ đích (chi tiết pipeline tại [ml/FEATURE_AI_YIELD_AND_RECOMMENDATION.md](../../ml/FEATURE_AI_YIELD_AND_RECOMMENDATION.md)).
  - **Không import `pandas`, `scikit-learn`, `lightgbm`** trong `platform/core/` hay `platform/api/` (giữ tiến trình `api` trong ngân sách ≤ 384 MB RAM trên VPS 2 GB).

### 3.2 Cấu trúc `crop_profiles.parameters_json` (`schema_version = 2`)

Được validate chặt qua `core.crop_templates.CropParameters` (lưu ý dùng `Field(alias="yield")` cho thuộc tính Python và `model_dump(by_alias=True)` để key JSON đầu ra luôn là `"yield"`):

```json
{
  "schema_version": 2,
  "vpd": {"optimal": [0.8, 1.2], "low_crit": 0.4, "low_off": 0.6, "high_crit": 1.6, "leaf_offset_c": 1.0},
  "temp_c": {"optimal": [20.0, 28.0]},
  "light": {"dli_optimal": [20.0, 30.0]},
  "soil_moisture_pct": {"min": 60.0, "max": 75.0},
  "disease": {"rh_gt": 85.0, "temp_range_c": [15.0, 25.0], "fungal_minutes_alert": 360},
  "irrigation": {"max_run_s": 300, "min_gap_s": 1800, "max_total_s_per_hour": 420, "soil_settle_s": 300},
  "fan": {"min_on_s": 300, "max_on_s": 1800},
  "mist": {"max_on_s": 900, "lockout_s": 900},
  "risk": {"vpd_low_duration_min": 60},
  "cycle": {"days": 120},
  "yield": {"reference_kg_m2": 10.0},
  "ai": {"recommend_window_h": 336, "min_cycle_hours": 72.0, "inference_interval_s": 3600, "min_coverage": 0.7},
  "sample_interval_s": 60,
  "failsafe": {"temp_critical_high_c": 35.0, "soil_moisture_critical_low_pct": 30.0}
}
```

- **Đặc điểm `schema_version = 2`:**
  - Bổ sung: `light.dli_optimal` (`[min, max]`, mol/m²/ngày), `cycle.days` (`int > 0`), `yield.reference_kg_m2` (`float > 0`), `ai.recommend_window_h` (`int > 0`), `ai.min_cycle_hours` (`float > 0`), `ai.inference_interval_s` (`int > 0`), `ai.min_coverage` (`float ∈ (0, 1]`).
  - Nhóm `risk` chỉ gồm `vpd_low_duration_min` (phục vụ rule engine bật quạt khi VPD thấp kéo dài).

### 3.3 Mười template hệ thống (`farm_id = NULL`, MUST)

5 loại cây trồng × 2 bộ (`real` và `demo`) = **10 template hệ thống** với UUID cố định:

| UUID cố định | `crop_code` | `crop_name` | `variety` | `vpd.optimal` | `temp_c.optimal` | `light.dli_optimal` | `soil_moisture_pct` | `cycle.days` | `yield.reference_kg_m2` | `failsafe.temp_critical_high_c` | `disease.rh_gt` |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `00000000-0000-4000-8000-000000000001` | `tomato_cherry` | Cà chua bi | `real` | `[0.8, 1.2]` | `[20, 28]` | `[20, 30]` | `60–75` | `120` | `10.0` | `35.0` | `85.0` |
| `00000000-0000-4000-8000-000000000002` | `tomato_cherry` | Cà chua bi | `demo` | `[0.8, 1.2]` | `[20, 28]` | `[20, 30]` | `60–75` | `120` | `10.0` | `35.0` | `85.0` |
| `00000000-0000-4000-8000-000000000003` | `strawberry` | Dâu tây | `real` | `[0.6, 0.9]` | `[18, 24]` | `[15, 22]` | `50–65` | `150` | `4.0` | `30.0` | `90.0` |
| `00000000-0000-4000-8000-000000000004` | `strawberry` | Dâu tây | `demo` | `[0.6, 0.9]` | `[18, 24]` | `[15, 22]` | `50–65` | `150` | `4.0` | `30.0` | `90.0` |
| `00000000-0000-4000-8000-000000000005` | `lettuce` | Xà lách | `real` | `[0.6, 1.0]` | `[15, 22]` | `[12, 17]` | `60–80` | `40` | `3.0` | `30.0` | `85.0` |
| `00000000-0000-4000-8000-000000000006` | `lettuce` | Xà lách | `demo` | `[0.6, 1.0]` | `[15, 22]` | `[12, 17]` | `60–80` | `40` | `3.0` | `30.0` | `85.0` |
| `00000000-0000-4000-8000-000000000007` | `cucumber` | Dưa leo | `real` | `[0.8, 1.2]` | `[22, 30]` | `[20, 30]` | `65–80` | `75` | `15.0` | `38.0` | `85.0` |
| `00000000-0000-4000-8000-000000000008` | `cucumber` | Dưa leo | `demo` | `[0.8, 1.2]` | `[22, 30]` | `[20, 30]` | `65–80` | `75` | `15.0` | `38.0` | `85.0` |
| `00000000-0000-4000-8000-000000000009` | `bell_pepper` | Ớt chuông | `real` | `[0.8, 1.2]` | `[21, 28]` | `[20, 30]` | `60–75` | `150` | `8.0` | `35.0` | `85.0` |
| `00000000-0000-4000-8000-000000000010` | `bell_pepper` | Ớt chuông | `demo` | `[0.8, 1.2]` | `[21, 28]` | `[20, 30]` | `60–75` | `150` | `8.0` | `35.0` | `85.0` |

*Lưu ý:* Cả 10 template dùng chung `vpd.low_crit = 0.4`, `low_off = 0.6`, `high_crit = 1.6`, `leaf_offset_c = 1.0`, `disease.temp_range_c = [15.0, 25.0]`, `failsafe.soil_moisture_critical_low_pct = 30.0`, `ai.min_coverage = 0.7`.

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
| `disease.fungal_minutes_alert` | `360` | `5` | Số phút tích luỹ điều kiện nấm để bật `DISEASE_RISK` |
| `ai.recommend_window_h` | `336` | `1` | Cửa sổ giờ lấy khí hậu để gợi ý cây trồng |
| `ai.min_cycle_hours` | `72` | `0.5` | Thời gian tối thiểu của vụ `active` trước khi dự báo năng suất |
| `ai.inference_interval_s` | `3600` | `60` | Chu kỳ suy luận định kỳ trong worker |
| `ai.min_coverage` | `0.7` | `0.7` | Tỉ lệ bucket hợp lệ tối thiểu để suy luận / tạo mẫu |

*(Ở bộ `demo`, các tham số `cycle.days`, `yield.reference_kg_m2`, `light.dli_optimal` giữ nguyên như bộ `real`. Khi suy luận `crop_recommendation` cấp nhà kính, dùng `ai.recommend_window_h` nhỏ nhất trong các zone của nhà kính đó.)*

- **Quy tắc chỉnh sửa template hệ thống:** Khi owner gọi `PUT /api/crop-profiles/{id}` trên một template có `farm_id = NULL`, API **không** sửa bản hệ thống mà **clone** thành bản mới thuộc `user.farm_id` (giữ nguyên `crop_code`), chuyển các zone thuộc farm đang trỏ vào template cũ sang bản mới, rồi tăng `cfg_version_desired`.

## 4. Cấu hình & Giao tiếp nội bộ (`config.py`, `pubsub.py`, `security.py`)

### 4.1 Biến cấu hình chính trong `Settings`
- DB & Auth: `database_url`, `jwt_secret`, `jwt_algorithm="HS256"`, `jwt_expire_min=720`.
- MQTT: `mqtt_host` (Docker: `mosquitto`), `mqtt_port=1883`, `mqtt_public_host`, `mqtt_public_port=8883`, `mqtt_worker_user`, `mqtt_worker_password`, `mqtt_admin_user`, `mqtt_admin_password`.
- Push & Email: `vapid_public_key`, `vapid_private_key`, `vapid_subject`, `smtp_host`, `smtp_port=587`, `smtp_user`, `smtp_password`, `alert_email_from`.
- Nghiệp vụ & ML: `models_dir=Path("./models")` (trong Docker là `/models`), `tz="Asia/Ho_Chi_Minh"`, `command_expire_s=30`, `alert_cooldown_min=10`, `escalate_after_min=5`.

### 4.2 Kênh PostgreSQL `LISTEN/NOTIFY`
- **`CHANNEL_WORKER = "worker_events"` (`api` / `ml.train` → `worker`):**
  - `{"type": "command_created", "cmd_id": "<uuid>", "greenhouse_id": "<uuid>"}`
  - `{"type": "cfg_updated", "greenhouse_id": "<uuid>"}`
  - `{"type": "cycle_harvested", "cycle_id": "<uuid>"}` (tạo `yield_samples` khi thu hoạch vụ trồng)
  - `{"type": "recommend", "greenhouse_id": "<uuid>"}` (làm mới gợi ý cây trồng theo yêu cầu)
  - `{"type": "model_activated", "task": "yield", "model_id": "<uuid>"}` (do `ml/train.py` gửi khi kích hoạt mô hình toàn cục mới để worker hot-reload)
- **`CHANNEL_WS = "ws_events"` (`worker` → `api`):**
  - Payload nhỏ gọn JSON có `farm_id`, `type` (`telemetry`, `alert`, `command_status`, `device_status`, `prediction`, `crop_cycle`, `config_sync`), `data`. Dùng `pg_notify(session, ...)` **bên trong transaction** để đảm bảo sự kiện chỉ phát ra khi commit DB thành công.

### 4.3 Bảo mật cốt lõi (`security.py`)
- Mật khẩu băm bằng **Argon2id** (`argon2.PasswordHasher`).
- JWT ký HS256 chứa claims: `sub` (`user_id`), `farm_id`, `role`, `iat`, `exp`.

## 5. Kiểm tra & Xác nhận

- Unit tests tại `platform/tests/test_core_and_api_unit.py`:
  - `test_password_hash_and_jwt_roundtrip`
  - `test_system_crop_templates_valid` (kiểm tra đủ 10 template `schema_version = 2`, đủ 5 `crop_code` × `real`/`demo`)
  - `test_mac_normalization_and_command_validation`
  - `test_api_process_does_not_import_heavy_ml_libraries` (xác nhận `core` và `api` không import `pandas`/`scikit-learn`/`lightgbm`)
