# Feature: Cơ sở dữ liệu PostgreSQL + TimescaleDB & Continuous Aggregates (`platform/migrations/`)

> Nguồn đặc tả: `docs/greenhub-spec.md` mục 7, 13.1, 13.3, 15; `docs/DECISIONS.md`.

## 1. Mục tiêu & Phạm vi

Quản lý lược đồ cơ sở dữ liệu PostgreSQL + TimescaleDB bằng Alembic: lưu trữ cấu trúc đa tenant (`farms`, `users`, `greenhouses`), thiết bị (`gateways`, `device_nodes`, `device_state`), chuỗi thời gian (`readings` hypertable + `readings_1m`, `readings_1h`), vận hành điều khiển (`commands`, `actuator_logs`), cảnh báo/thông báo (`alerts`, `push_subscriptions`, `notification_prefs`), và AI/thí nghiệm (`ml_models`, `predictions`, `experiment_runs`).

- **Ngoài phạm vi:** Không bật PostgreSQL Row-Level Security (RLS là MAY; cô lập tenant thực hiện bằng `WHERE farm_id = ...` ở API); không tạo bảng `farm_activities` (ngoài phạm vi spec 2.2); không dùng AWS RDS.

## 2. Trạng thái hiện thực trong repo

- **Đã hoàn thiện (M2):**
  - `platform/alembic.ini` & `platform/migrations/env.py` — cấu hình Alembic async với `asyncpg`, đọc `DATABASE_URL` từ `core.config.get_settings()`.
  - `20261105_0001_init_extensions.py` (`rev 0001`): `CREATE EXTENSION IF NOT EXISTS timescaledb;` và `pgcrypto;` (nếu cần `gen_random_uuid()`).
  - `20261105_0002_core_schema.py` (`rev 0002`): tạo toàn bộ 17 bảng nghiệp vụ, các ràng buộc `CHECK`/`UNIQUE`/`FK`, index `ix_actuator_logs_gh_created`, partial unique index `alerts_open_dedupe`, chuyển `readings` thành hypertable TimescaleDB, và seed 4 `crop_profiles` hệ thống (`farm_id = NULL`) bằng `ON CONFLICT (id) DO NOTHING`.
  - `20261105_0003_continuous_aggregates.py` (`rev 0003`): dùng `autocommit_block()` tạo `readings_1m` và `readings_1h` kèm `add_continuous_aggregate_policy` (`if_not_exists => TRUE`).
- **Tùy chọn có thể thêm sau (MAY):**
  - Compression policy cho `readings` cũ hơn 7 ngày (`timescaledb.compress`, `compress_segmentby='zone_id'`).

## 3. Chi tiết toàn bộ 17 bảng & Ràng buộc

1. **`farms`**: `id` UUID PK, `name` VARCHAR(100) NOT NULL, `created_at` TIMESTAMPTZ.
2. **`users`**: `id` UUID PK, `farm_id` FK→`farms.id`, `email` UNIQUE NOT NULL, `password_hash` TEXT NOT NULL, `role` CHECK `('owner','operator','viewer')`, `created_at`.
3. **`greenhouses`**: `id` UUID PK, `farm_id` FK→`farms.id`, `name`, `location`, `created_at`.
4. **`gateways`**: `id` UUID PK, `greenhouse_id` UNIQUE FK→`greenhouses.id` (1-1), `mqtt_username` UNIQUE NOT NULL, `is_simulated` BOOL default `false`, `provisioned_at`, `online` BOOL default `false`, `last_seen`, `fw_version`, `rssi`.
5. **`crop_profiles`**: `id` UUID PK, `farm_id` FK→`farms.id` (`NULL` = template hệ thống), `crop_name` NOT NULL, `variety`, `schema_version` INT default `1`, `parameters_json` JSONB NOT NULL.
6. **`zones`**: `id` UUID PK, `greenhouse_id` FK→`greenhouses.id`, `zone_index` INT NOT NULL, `name`, `crop_profile_id` FK→`crop_profiles.id`, `planting_date` DATE, `pump_channel` INT, `control_strategy` CHECK `('fixed','adaptive')` default `'fixed'`, `soil_dry_raw`, `soil_wet_raw`. Ràng buộc `UNIQUE (greenhouse_id, zone_index)`.
7. **`device_nodes`**: `id` UUID PK, `mac_address` VARCHAR(17) UNIQUE NOT NULL, `greenhouse_id` FK, `zone_id` FK, `status` CHECK `('discovered','paired')` default `'discovered'`, `firmware_version`, `battery_mv`, `rssi`, `first_seen`, `last_seen`.
8. **`readings`** *(TimescaleDB Hypertable trên cột `ts`)*:
   - `PRIMARY KEY (zone_id, ts)` (bắt buộc chứa cột phân vùng `ts` của TimescaleDB; giúp `ON CONFLICT (zone_id, ts) DO NOTHING` idempotent).
   - Cột: `air_temp`, `air_rh`, `vpd`, `soil_moisture`, `soil_raw`, `lux`, `rssi`, `seq`, `quality` (`'ok' | 'stuck' | 'spike' | 'dropout' | 'out_of_range'`), `source` CHECK `('real','sim')`.
9. **`commands`**: `id` UUID PK (= `cmd_id`), `greenhouse_id` FK, `actuator`, `action`, `duration_s`, `source` CHECK `('auto','manual')`, `requested_by` FK→`users.id`, `reason`, `status` CHECK `('pending','sent','applied','rejected','expired','timeout')`, `reject_reason`, `created_at`, `sent_at`, `acked_at`, `expires_at` NOT NULL.
10. **`actuator_logs`**: `id` UUID PK, `greenhouse_id` FK, `actuator`, `action`, `source` CHECK `('auto','manual','failsafe')`, `cmd_id` UUID, `duration_s`, `reason`, `created_at`. Index: `(greenhouse_id, created_at DESC)`.
11. **`device_state`**: `greenhouse_id` PK FK→`greenhouses.id`, `reported` JSONB, `desired` JSONB (chứa `modes`), `cfg_version_desired` INT, `cfg_version_reported` INT, `updated_at`.
12. **`alerts`**:
    - `id` UUID PK, `greenhouse_id` FK, `zone_id` FK (nullable cho alert cấp gateway như `DEVICE_OFFLINE`), `alert_type` VARCHAR(50), `severity` CHECK `('info','warning','critical')`, `state` CHECK `('raised','notified','acknowledged','resolved')`, `dedupe_key` VARCHAR(120), `payload` JSONB, `created_at`, `notified_at`, `escalated_at`, `acknowledged_at`, `acked_by` FK→`users.id`, `resolved_at`, `feedback` CHECK `IS NULL OR IN ('true_positive','false_positive')`, `feedback_at`.
    - **Index đặc biệt:** `CREATE UNIQUE INDEX alerts_open_dedupe ON alerts (dedupe_key) WHERE state <> 'resolved'` → đảm bảo tại một thời điểm chỉ có tối đa 1 alert đang mở cho mỗi `dedupe_key` (`"{type}:{zone_id|greenhouse_id}"`).
13. **`push_subscriptions`**: `id` UUID PK, `user_id` FK, `endpoint` UNIQUE TEXT, `p256dh`, `auth`, `user_agent`, `created_at`, `last_used_at`.
14. **`notification_prefs`**: `user_id` PK FK→`users.id`, `push_enabled` (`true`), `email_enabled` (`true`), `min_severity` (`'warning'`).
15. **`ml_models`**: `id` UUID PK, `zone_id` FK (nullable nếu dùng chung), `task` VARCHAR(30), `version` INT, `artifact_path` TEXT, `trained_at`, `train_from`, `train_to`, `n_samples`, `source_mix` JSONB (`{"real":n,"sim":m}`), `metrics` JSONB, `baseline_metrics` JSONB, `is_active` BOOL default `false`, `notes`. Ràng buộc `UNIQUE (zone_id, task, version)`.
16. **`predictions`**: `PRIMARY KEY (zone_id, task, ts)`, `model_id` FK→`ml_models.id`, `horizon_min`, `score` REAL, `value` REAL, `details` JSONB.
17. **`experiment_runs`**: `id` UUID PK, `greenhouse_id` FK, `strategy` CHECK `('fixed','adaptive')`, `started_at`, `ended_at`, `notes`.

## 4. Continuous Aggregates & Quy trình vận hành

- **`readings_1m`**: `time_bucket('1 minute', ts)`, lọc `WHERE quality = 'ok'`, gom trung bình `air_temp`, `air_rh`, `vpd`, `soil_moisture`, `lux` và `count(*) AS n`. Refresh policy: `start_offset => '2 hours'`, `end_offset => '1 minute'`, `schedule_interval => '1 minute'`.
- **`readings_1h`**: `time_bucket('1 hour', ts)`, lọc `WHERE quality = 'ok'`. Refresh policy: `start_offset => '3 days'`, `end_offset => '1 hour'`, `schedule_interval => '15 minutes'`.
- **Chú ý cho query `/readings?agg=1m|1h`:** Do continuous aggregate có `end_offset` 1 phút / 1 giờ và `schedule_interval`, dữ liệu phút/giờ mới nhất có thể trễ nhẹ; đây là hành vi chuẩn của TimescaleDB policy.
- **Chạy migration sạch:**
  - Trong Docker (`platform/docker-entrypoint.sh`): container `api` chạy `alembic upgrade head` trước khi start `uvicorn`, và `worker` phụ thuộc `api` healthy nên không bao giờ xảy ra race condition chạy migration song song (`docs/DECISIONS.md`).
  - Cục bộ ngoài Docker (nếu cần): từ `platform/` với `DATABASE_URL` trỏ `127.0.0.1:15432`, chạy `alembic upgrade head`.
