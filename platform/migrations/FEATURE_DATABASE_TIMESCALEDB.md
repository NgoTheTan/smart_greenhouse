# Feature: Cơ sở dữ liệu PostgreSQL + TimescaleDB & Continuous Aggregates (`platform/migrations/`)

> Nguồn đặc tả: `docs/greenhub-spec.md` mục 7, 13.1, 13.3, 15; `docs/DECISIONS.md`.

## 1. Mục tiêu & Phạm vi

Quản lý lược đồ cơ sở dữ liệu PostgreSQL + TimescaleDB bằng Alembic: lưu trữ cấu trúc đa tenant (`farms`, `users`, `greenhouses`), thiết bị (`gateways`, `device_nodes`, `device_state`), chuỗi thời gian (`readings` hypertable + `readings_1m`, `readings_1h`), vận hành điều khiển (`commands`, `actuator_logs`), cảnh báo/thông báo (`alerts`, `push_subscriptions`, `notification_prefs`), và vòng đời vụ trồng / AI năng suất (`crop_cycles`, `yield_samples`, `ml_models`, `predictions`).

- **Ngoài phạm vi:** Không bật PostgreSQL Row-Level Security (RLS là MAY; cô lập tenant thực hiện bằng `WHERE farm_id = ...` ở tầng API và tuyệt đối không mở endpoint đọc `yield_samples`); không tạo bảng `farm_activities` (ngoài phạm vi spec 2.2); không dùng dịch vụ CSDL cloud managed (chạy container trên VPS).

## 2. Lịch sử Migration & Đặc tả Migration chuyển đổi

### 2.1 Các migration đã áp dụng ở M2 (giữ nguyên bất biến)
- `platform/alembic.ini` & `platform/migrations/env.py` — cấu hình Alembic async với `asyncpg`, đọc `DATABASE_URL` từ `core.config.get_settings()`.
- `20261105_0001_init_extensions.py` (`rev 0001`): `CREATE EXTENSION IF NOT EXISTS timescaledb;` và `pgcrypto;`.
- `20261105_0002_core_schema.py` (`rev 0002`): tạo bộ bảng nghiệp vụ lõi ban đầu, chuyển `readings` thành hypertable TimescaleDB, tạo `ix_actuator_logs_gh_created`, partial unique index `alerts_open_dedupe`, và seed 4 `crop_profiles` hệ thống ban đầu (`v1`).
- `20261105_0003_continuous_aggregates.py` (`rev 0003`): dùng `autocommit_block()` tạo `readings_1m` và `readings_1h` kèm `add_continuous_aggregate_policy` (`if_not_exists => TRUE`).

### 2.2 Migration mới cần tạo: `20261112_0004_yield_ai_and_cycles.py` (`rev 0004`, `down_revision = "0003"`)
*(Lưu ý: vì `rev 0003` đã được dùng cho `continuous_aggregates`, migration chuyển đổi sang schema đích mới phải mang revision `0004`.)*

Các bước trong `upgrade()` để chuyển đổi sạch từ schema M2 sang schema đích (mục 3):
1. **`crop_profiles`:**
   - Thêm cột `crop_code VARCHAR(40)`, backfill dữ liệu cũ (`Cà chua bi` → `'tomato_cherry'`, `Dâu tây` → `'strawberry'`), rồi đặt `NOT NULL`.
   - Đổi mặc định `schema_version` thành `2`.
   - Cập nhật 4 template hệ thống cũ (`farm_id IS NULL`) sang `parameters_json` `schema_version = 2` (bổ sung `light.dli_optimal`, `cycle.days`, `yield.reference_kg_m2`, `ai.*`) và chèn thêm 6 template mới cho `lettuce` (Xà lách), `cucumber` (Dưa leo), `bell_pepper` (Ớt chuông) × `real`/`demo` → đủ **10 template hệ thống**.
2. **`zones`:**
   - Xoá ràng buộc `ck_zones_control_strategy` (nếu có) và xoá cột `control_strategy`.
   - Thêm cột `area_m2 REAL`.
3. **`alerts`:**
   - Xoá ràng buộc `ck_alerts_feedback` (nếu có) và xoá 2 cột `feedback`, `feedback_at`.
4. **Xoá bảng cũ không còn dùng:**
   - `DROP TABLE IF EXISTS experiment_runs`.
5. **Tạo bảng `crop_cycles`:**
   - Tạo bảng `crop_cycles` theo DDL mục 3 và partial unique index `CREATE UNIQUE INDEX crop_cycles_one_active ON crop_cycles (zone_id) WHERE status = 'active'`.
6. **Tạo bảng `yield_samples`:**
   - Tạo bảng `yield_samples` theo DDL mục 3 và 2 index trên `(crop_code)` và `(greenhouse_key)`.
7. **Cập nhật bảng `ml_models` (sang mô hình toàn cục):**
   - Xoá `uq_ml_models_zone_task_ver` và các cột cũ (`zone_id`, `train_from`, `train_to`).
   - Thêm `feature_version INT NOT NULL DEFAULT 1`, `n_greenhouses INT`, `crops JSONB`; đặt `DEFAULT 'yield'` cho `task`; thêm `UNIQUE (task, version)` (`uq_ml_models_task_version`).
8. **Cập nhật bảng `predictions`:**
   - Chuyển sang cấu trúc mới (drop & recreate bảng `predictions` nếu chưa có dữ liệu cần giữ, hoặc migrate tương đương): khóa chính `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`, cột `ts`, `task CHECK (task IN ('yield_forecast','crop_recommendation'))`, `greenhouse_id NOT NULL`, `zone_id` (nullable), `crop_cycle_id` (nullable), `model_id`, `value`, `score`, `details`, `CHECK (task <> 'yield_forecast' OR zone_id IS NOT NULL)`, và index `(greenhouse_id, task, ts DESC)`.

### 2.3 Tuỳ chọn có thể thêm sau (MAY)
- Compression policy cho `readings` cũ hơn 7 ngày (`timescaledb.compress`, `compress_segmentby='zone_id'`).

## 3. Chi tiết Schema đích (18 bảng & Ràng buộc)

1. **`farms`**: `id` UUID PK, `name` VARCHAR(100) NOT NULL, `created_at` TIMESTAMPTZ.
2. **`users`**: `id` UUID PK, `farm_id` FK→`farms.id`, `email` UNIQUE NOT NULL, `password_hash` TEXT NOT NULL, `role` CHECK `('owner','operator','viewer')`, `created_at`.
3. **`greenhouses`**: `id` UUID PK, `farm_id` FK→`farms.id`, `name`, `location`, `created_at`.
4. **`gateways`**: `id` UUID PK, `greenhouse_id` UNIQUE FK→`greenhouses.id` (1-1), `mqtt_username` UNIQUE NOT NULL, `is_simulated` BOOL default `false`, `provisioned_at`, `online` BOOL default `false`, `last_seen`, `fw_version`, `rssi`.
5. **`crop_profiles`**: `id` UUID PK, `farm_id` FK→`farms.id` (`NULL` = template hệ thống), `crop_code` VARCHAR(40) NOT NULL (`tomato_cherry | strawberry | lettuce | cucumber | bell_pepper`), `crop_name` NOT NULL, `variety`, `schema_version` INT default `2`, `parameters_json` JSONB NOT NULL.
6. **`zones`**: `id` UUID PK, `greenhouse_id` FK→`greenhouses.id`, `zone_index` INT NOT NULL, `name`, `crop_profile_id` FK→`crop_profiles.id`, `area_m2` REAL, `planting_date` DATE, `pump_channel` INT, `soil_dry_raw`, `soil_wet_raw`. Ràng buộc `UNIQUE (greenhouse_id, zone_index)`.
7. **`device_nodes`**: `id` UUID PK, `mac_address` VARCHAR(17) UNIQUE NOT NULL, `greenhouse_id` FK, `zone_id` FK, `status` CHECK `('discovered','paired')` default `'discovered'`, `firmware_version`, `battery_mv`, `rssi`, `first_seen`, `last_seen`.
8. **`readings`** *(TimescaleDB Hypertable trên cột `ts`)*:
   - `PRIMARY KEY (zone_id, ts)` (bắt buộc chứa cột phân vùng `ts` của TimescaleDB; giúp `ON CONFLICT (zone_id, ts) DO NOTHING` idempotent).
   - Cột: `air_temp`, `air_rh`, `vpd`, `soil_moisture`, `soil_raw`, `lux`, `rssi`, `seq`, `quality` (`'ok' | 'stuck' | 'spike' | 'dropout' | 'out_of_range'`), `source` CHECK `('real','sim')`.
9. **`commands`**: `id` UUID PK (= `cmd_id`), `greenhouse_id` FK, `actuator`, `action`, `duration_s`, `source` CHECK `('auto','manual')`, `requested_by` FK→`users.id`, `reason`, `status` CHECK `('pending','sent','applied','rejected','expired','timeout')`, `reject_reason`, `created_at`, `sent_at`, `acked_at`, `expires_at` NOT NULL.
10. **`actuator_logs`**: `id` UUID PK, `greenhouse_id` FK, `actuator`, `action`, `source` CHECK `('auto','manual','failsafe')`, `cmd_id` UUID, `duration_s`, `reason`, `created_at`. Index: `(greenhouse_id, created_at DESC)`.
11. **`device_state`**: `greenhouse_id` PK FK→`greenhouses.id`, `reported` JSONB, `desired` JSONB (chứa `modes`), `cfg_version_desired` INT, `cfg_version_reported` INT, `updated_at`.
12. **`alerts`**:
    - `id` UUID PK, `greenhouse_id` FK, `zone_id` FK (nullable cho alert cấp gateway như `DEVICE_OFFLINE`), `alert_type` VARCHAR(50), `severity` CHECK `('info','warning','critical')`, `state` CHECK `('raised','notified','acknowledged','resolved')`, `dedupe_key` VARCHAR(120), `payload` JSONB, `created_at`, `notified_at`, `escalated_at`, `acknowledged_at`, `acked_by` FK→`users.id`, `resolved_at`.
    - **Index đặc biệt:** `CREATE UNIQUE INDEX alerts_open_dedupe ON alerts (dedupe_key) WHERE state <> 'resolved'` → đảm bảo tại một thời điểm chỉ có tối đa 1 alert đang mở cho mỗi `dedupe_key` (`"{type}:{zone_id|greenhouse_id}"`).
13. **`push_subscriptions`**: `id` UUID PK, `user_id` FK, `endpoint` UNIQUE TEXT, `p256dh`, `auth`, `user_agent`, `created_at`, `last_used_at`.
14. **`notification_prefs`**: `user_id` PK FK→`users.id`, `push_enabled` (`true`), `email_enabled` (`true`), `min_severity` (`'warning'`).
15. **`crop_cycles`** *(vụ trồng – dữ liệu theo tenant)*:
    - `id` UUID PK, `zone_id` FK→`zones.id` NOT NULL, `crop_profile_id` FK→`crop_profiles.id` NOT NULL, `started_at` TIMESTAMPTZ NOT NULL, `harvested_at` TIMESTAMPTZ, `area_m2` REAL NOT NULL `CHECK (area_m2 > 0)`, `yield_kg` REAL `CHECK (yield_kg >= 0)`, `status` VARCHAR(10) NOT NULL DEFAULT `'active'` `CHECK (status IN ('active','harvested','abandoned'))`, `notes` TEXT, `created_by` FK→`users.id`, `created_at` TIMESTAMPTZ NOT NULL.
    - **Index đặc biệt:** `CREATE UNIQUE INDEX crop_cycles_one_active ON crop_cycles (zone_id) WHERE status = 'active'` → mỗi zone tại một thời điểm chỉ có tối đa 1 vụ đang trồng.
16. **`yield_samples`** *(tập mẫu huấn luyện gộp từ nhiều nhà kính)*:
    - `id` UUID PK, `source` VARCHAR(10) NOT NULL `CHECK (source IN ('real','sim','synthetic','public'))`, `greenhouse_key` VARCHAR(100) NOT NULL (UUID nhà kính platform hoặc mã ngoài như `'syn-0042'`), `farm_id` FK→`farms.id` (nullable với dữ liệu ngoài platform), `crop_cycle_id` UNIQUE FK→`crop_cycles.id`, `crop_code` VARCHAR(40) NOT NULL, `started_at` TIMESTAMPTZ, `ended_at` TIMESTAMPTZ, `cycle_days` REAL, `feature_version` INT NOT NULL, `features` JSONB NOT NULL, `coverage` REAL, `yield_kg_m2` REAL NOT NULL `CHECK (yield_kg_m2 >= 0)`, `meta` JSONB, `created_at` TIMESTAMPTZ NOT NULL.
    - Index: `(crop_code)`, `(greenhouse_key)`.
    - **Bảo mật cô lập tenant:** `yield_samples` **không bao giờ** được trả qua API.
17. **`ml_models`** *(mô hình toàn cục)*:
    - `id` UUID PK, `task` VARCHAR(30) NOT NULL DEFAULT `'yield'`, `version` INT NOT NULL, `feature_version` INT NOT NULL, `artifact_path` TEXT NOT NULL, `trained_at` TIMESTAMPTZ NOT NULL, `n_samples` INT, `n_greenhouses` INT, `source_mix` JSONB (`{"synthetic":n,"sim":m,"real":k,"public":p}`), `crops` JSONB (`[{"crop_code":"lettuce","n":412,"reference_kg_m2":3.0}]`), `metrics` JSONB (trên test nhà kính chưa thấy + theo cây + theo `source` + `top1`/`ndcg3` + `train_stats`), `baseline_metrics` JSONB (`{"B0":{...},"B1":{...}}`), `is_active` BOOL NOT NULL DEFAULT `false`, `notes` TEXT.
    - Ràng buộc: `UNIQUE (task, version)`.
18. **`predictions`**:
    - `id` UUID PK, `ts` TIMESTAMPTZ NOT NULL, `task` VARCHAR(30) NOT NULL `CHECK (task IN ('yield_forecast','crop_recommendation'))`, `greenhouse_id` FK→`greenhouses.id` NOT NULL, `zone_id` FK→`zones.id` (chỉ `yield_forecast`), `crop_cycle_id` FK→`crop_cycles.id` (chỉ `yield_forecast`), `model_id` FK→`ml_models.id`, `value` REAL (`kg/m²` dự kiến với `yield_forecast`), `score` REAL (`relative_yield` với `yield_forecast` / điểm top-1 với `crop_recommendation`), `details` JSONB.
    - Ràng buộc: `CHECK (task <> 'yield_forecast' OR zone_id IS NOT NULL)`.
    - Index: `(greenhouse_id, task, ts DESC)`.

## 4. Continuous Aggregates & Quy trình vận hành

- **`readings_1m`**: `time_bucket('1 minute', ts)`, lọc `WHERE quality = 'ok'`, gom trung bình `air_temp`, `air_rh`, `vpd`, `soil_moisture`, `lux` và `count(*) AS n`. Refresh policy: `start_offset => '2 hours'`, `end_offset => '1 minute'`, `schedule_interval => '1 minute'`.
- **`readings_1h`**: `time_bucket('1 hour', ts)`, lọc `WHERE quality = 'ok'`. Refresh policy: `start_offset => '3 days'`, `end_offset => '1 hour'`, `schedule_interval => '15 minutes'`.
- **Chú ý cho query `/readings?agg=1m|1h` và `climate_features`:** Do continuous aggregate có `end_offset` 1 phút / 1 giờ và `schedule_interval`, dữ liệu mới nhất trong phút/giờ hiện tại có thể chưa materialize; với cửa sổ < 6 h dùng `readings_1m`, cửa sổ ≥ 6 h dùng `readings_1h`.
- **Chạy migration sạch:**
  - Trong Docker (`platform/docker-entrypoint.sh`): container `api` chạy `alembic upgrade head` trước khi start `uvicorn`, và `worker` phụ thuộc `api` healthy nên không bao giờ xảy ra race condition chạy migration song song (`docs/DECISIONS.md`).
  - Cục bộ ngoài Docker (nếu cần): từ `platform/` với `DATABASE_URL` trỏ `127.0.0.1:15432`, chạy `alembic upgrade head`.
- **Sao lưu trên VPS:** cron chạy `pg_dump` hằng ngày (kèm thư mục `/models`), giữ 7 bản gần nhất.
