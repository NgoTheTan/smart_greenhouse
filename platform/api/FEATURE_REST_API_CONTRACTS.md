# Feature: Đặc tả đầy đủ Hợp đồng REST API (`/api/*`) (`platform/api/`)

> Nguồn đặc tả: `docs/greenhub-spec.md` mục 6.2–6.7, 7.1, 8.2–8.3, 9, 10, 12; `docs/DECISIONS.md`.

## 1. Mục tiêu & Phạm vi

Tổng hợp đầy đủ hợp đồng giao tiếp HTTP REST dưới tiền tố `/api` (OpenAPI tại `/api/docs`), bao gồm các endpoint nền tảng (M2) và các endpoint vận hành/AI (M3–M5) để backend (`platform/api/`) và frontend (`web/`) khớp nhau tuyệt đối.

- **Quy tắc bất biến:**
  - Mọi endpoint (trừ `/api/health`, `/api/auth/login`) yêu cầu JWT Bearer token và kiểm tra RBAC (`viewer` / `operator` / `owner`).
  - Cô lập tenant ở tầng ứng dụng theo `user.farm_id`. Bảng `yield_samples` chứa dữ liệu gộp đa nhà kính cho huấn luyện toàn cục nên **tuyệt đối không** có endpoint đọc trực tiếp `yield_samples`.
  - Tiến trình `api` **KHÔNG** import `joblib`, `pandas`, `scikit-learn`, `lightgbm` (bảo vệ ngân sách RAM ≤ 384 MB trên VPS 2 GB). Mọi truy vấn ở `/models`, `/predictions`, `/recommendations` chỉ dùng SQL thuần/SQLAlchemy trên `ml_models` và `predictions`.

## 2. Bảng tổng hợp Endpoint

| Nhóm | Endpoint | Vai trò tối thiểu | Trạng thái | File router |
|---|---|---|---|---|
| System | `GET /api/health` | Công khai | **Đã xong** | `api/main.py` |
| Auth | `POST /api/auth/login` | Công khai | **Đã xong** | `api/routers/auth.py` |
| Auth | `GET /api/me` | `viewer` | **Đã xong** | `api/routers/auth.py` |
| Farm/GH | `GET /api/greenhouses`, `GET /api/greenhouses/{id}` | `viewer` | **Đã xong** | `api/routers/greenhouses.py` |
| Farm/GH | `POST /api/greenhouses` | `owner` | **Đã xong** | `api/routers/greenhouses.py` |
| Config Sync | `GET /api/greenhouses/{id}/config-sync` | `viewer` | **Đã xong** | `api/routers/greenhouses.py` |
| Thiết bị | `POST /api/gateways` | `owner` | **Đã xong** | `api/routers/devices.py` |
| Thiết bị | `GET /api/gateways/{id}/status` | `viewer` | **Đã xong** | `api/routers/devices.py` |
| Thiết bị | `GET /api/nodes?status=` | `owner` | **Đã xong** | `api/routers/devices.py` |
| Thiết bị | `POST /api/nodes/{mac}/pair` | `owner` | **Đã xong** | `api/routers/devices.py` |
| Thiết bị | `PUT /api/zones/{id}/calibration` | `owner` | **Đã xong** | `api/routers/devices.py` |
| Zone | `GET /api/zones/{id}`, `PUT /api/zones/{id}` | `viewer` / `owner` | **Cần cập nhật (`name`, `crop_profile_id`, `area_m2`)** | `api/routers/zones.py` |
| Dữ liệu | `GET /api/zones/{id}/readings?from&to&agg=raw\|1m\|1h` | `viewer` | **Đã xong** | `api/routers/zones.py` |
| Dữ liệu | `GET /api/zones/{id}/dli?date=` | `viewer` | **Đã xong** | `api/routers/zones.py` |
| Crop Profile | `GET /api/crop-profiles`, `GET /api/crop-profiles/{id}`, `PUT /api/crop-profiles/{id}` | `viewer` / `owner` | **Cần cập nhật (`schema_version=2`, `crop_code`)** | `api/routers/zones.py` |
| Vụ trồng | `GET /api/zones/{id}/cycles` | `viewer` | **Cần làm (M4–M5)** | `api/routers/cycles.py` |
| Vụ trồng | `POST /api/zones/{id}/cycles`, `POST /api/cycles/{id}/harvest`, `POST /api/cycles/{id}/abandon` | `operator` | **Cần làm (M4–M5)** | `api/routers/cycles.py` |
| Điều khiển | `POST /api/greenhouses/{id}/commands`, `PUT /api/greenhouses/{id}/modes` | `operator` | **Đã xong** | `api/routers/commands.py` |
| Điều khiển | `GET /api/greenhouses/{id}/commands` | `viewer` | **Đã xong** | `api/routers/commands.py` |
| Cảnh báo | `GET /api/alerts?state=` | `viewer` | **Cần cập nhật (chỉ giữ trường vòng đời cảnh báo)** | `api/routers/alerts.py` |
| Cảnh báo | `POST /api/alerts/{id}/ack` | `operator` | **Đã xong / giữ nguyên** | `api/routers/alerts.py` |
| Push & Prefs | `GET /api/push/public-key`, `POST /api/push/subscribe`, `DELETE /api/push/subscribe`, `GET/PUT /api/me/notification-prefs` | `viewer` | **Đã xong** | `api/routers/push.py` |
| Dự báo AI | `GET /api/zones/{id}/predictions?task=yield_forecast&from&to` | `viewer` | **Cần cập nhật (M5)** | `api/routers/models.py` |
| Gợi ý AI | `GET /api/greenhouses/{id}/recommendations` | `viewer` | **Cần làm (M5)** | `api/routers/recommendations.py` |
| Gợi ý AI | `POST /api/greenhouses/{id}/recommendations/refresh` | `operator` | **Cần làm (M5)** | `api/routers/recommendations.py` |
| Mô hình ML | `GET /api/models`, `GET /api/models/active`, `GET /api/models/{id}` | `viewer` | **Cần cập nhật (M5)** | `api/routers/models.py` |

*(Gợi ý bổ sung tiện cho Web Console: `GET /api/greenhouses/{id}/actuator-logs` để vẽ lớp phủ lịch sử hoạt động bơm/quạt/tạo ẩm trên biểu đồ trang Zone.)*

## 3. Chi tiết Hợp đồng Endpoint (M3–M5 & Cập nhật)

### 3.1 Zone & Crop Profiles (`api/routers/zones.py`)

#### `PUT /api/zones/{zone_id}` (`CurrentOwner`)
- Kiểm tra `zone_id` thuộc `user.farm_id` (`404` nếu không tìm thấy).
- **Request JSON:** nhận `name`, `crop_profile_id`, `area_m2`:
  ```json
  {
    "name": "Zone 1 – Xà lách baby leaf",
    "crop_profile_id": "00000000-0000-4000-8000-000000000006",
    "area_m2": 1.2
  }
  ```
- **Ràng buộc:**
  - `area_m2`: nếu truyền thì `> 0` (`422` nếu `<= 0`).
  - `crop_profile_id`: phải tồn tại và có `farm_id IS NULL` hoặc `farm_id == user.farm_id` (`404` nếu không tìm thấy).
  - Nếu `crop_profile_id` thay đổi: gọi `bump_cfg_version(session, gh.id)` và `pg_notify(session, CHANNEL_WORKER, {"type": "cfg_updated", "greenhouse_id": str(gh.id)})` trước khi commit.
- **Response `200 OK`:**
  ```json
  {
    "id": "11111111-1111-4111-8111-111111111111",
    "greenhouse_id": "22222222-2222-4222-8222-222222222222",
    "zone_index": 1,
    "name": "Zone 1 – Xà lách baby leaf",
    "crop_profile_id": "00000000-0000-4000-8000-000000000006",
    "area_m2": 1.2,
    "planting_date": "2026-11-12",
    "pump_channel": 1,
    "soil_dry_raw": 2900,
    "soil_wet_raw": 1300
  }
  ```

#### `GET /api/crop-profiles` (`CurrentViewer`)
- Trả về toàn bộ template hệ thống (`farm_id IS NULL`, gồm 10 bản cho 5 cây × `real`/`demo`) cộng với các profile riêng của farm (`farm_id == user.farm_id`).
- **Response `200 OK`:** danh sách `CropProfileResponse` (kèm `crop_code`, `schema_version = 2`).

#### `GET /api/crop-profiles/{profile_id}` (`CurrentViewer`)
- Kiểm tra `farm_id IS NULL` hoặc `farm_id == user.farm_id` (`404` nếu thuộc farm khác hoặc không tồn tại).

#### `PUT /api/crop-profiles/{profile_id}` (`CurrentOwner`)
- Validate `parameters_json` theo `CropParameters` (`schema_version = 2`: bắt buộc có `light.dli_optimal`, `cycle.days`, `yield.reference_kg_m2`, `ai.{recommend_window_h, min_cycle_hours, inference_interval_s, min_coverage}`; sai schema → `422 Unprocessable Entity`).
- **Quy tắc clone template hệ thống:** nếu bản ghi gốc có `farm_id IS NULL`, không sửa bản hệ thống mà tạo bản sao mới gắn `farm_id = user.farm_id` (giữ `crop_code` hoặc cập nhật nếu truyền hợp lệ trong danh sách 5 `crop_code`), chuyển các `zones` của farm đang trỏ vào template cũ sang bản mới, rồi tăng `cfg_version_desired` và phát `pg_notify` `cfg_updated`.
- **Request JSON mẫu:**
  ```json
  {
    "crop_code": "lettuce",
    "crop_name": "Xà lách",
    "variety": "demo",
    "parameters_json": {
      "schema_version": 2,
      "vpd": {"optimal": [0.6, 1.0], "low_crit": 0.4, "low_off": 0.6, "high_crit": 1.6, "leaf_offset_c": 1.0},
      "temp_c": {"optimal": [15.0, 22.0]},
      "light": {"dli_optimal": [12.0, 17.0]},
      "soil_moisture_pct": {"min": 60.0, "max": 80.0},
      "disease": {"rh_gt": 85.0, "temp_range_c": [15.0, 25.0], "fungal_minutes_alert": 5},
      "irrigation": {"max_run_s": 15, "min_gap_s": 90, "max_total_s_per_hour": 120, "soil_settle_s": 30},
      "fan": {"min_on_s": 60, "max_on_s": 300},
      "mist": {"max_on_s": 300, "lockout_s": 120},
      "risk": {"vpd_low_duration_min": 3},
      "cycle": {"days": 40},
      "yield": {"reference_kg_m2": 3.0},
      "ai": {"recommend_window_h": 1, "min_cycle_hours": 0.5, "inference_interval_s": 60, "min_coverage": 0.7},
      "sample_interval_s": 10,
      "failsafe": {"temp_critical_high_c": 30.0, "soil_moisture_critical_low_pct": 30.0}
    }
  }
  ```
- **Response `200 OK`:**
  ```json
  {
    "id": "33333333-3333-4333-8333-333333333333",
    "farm_id": "44444444-4444-4444-8444-444444444444",
    "crop_code": "lettuce",
    "crop_name": "Xà lách",
    "variety": "demo",
    "schema_version": 2,
    "parameters_json": { "...": "..." }
  }
  ```

---

### 3.2 Vụ trồng (`api/routers/cycles.py`)

#### `GET /api/zones/{zone_id}/cycles` (`CurrentViewer`)
- Kiểm tra `zone_id` thuộc `user.farm_id` (`404` nếu không tìm thấy).
- Query tuỳ chọn: `status ∈ {'active', 'harvested', 'abandoned'}`, `limit` (mặc định `50`, `1..200`). Sắp xếp `started_at DESC`.
- **Response `200 OK`:**
  ```json
  [
    {
      "id": "55555555-5555-4555-8555-555555555555",
      "zone_id": "11111111-1111-4111-8111-111111111111",
      "crop_profile_id": "00000000-0000-4000-8000-000000000006",
      "crop_code": "lettuce",
      "crop_name": "Xà lách",
      "started_at": "2026-11-01T00:00:00Z",
      "harvested_at": "2026-11-28T09:00:00Z",
      "area_m2": 0.5,
      "yield_kg": 1.65,
      "yield_kg_m2": 3.3,
      "status": "harvested",
      "notes": null,
      "created_by": "66666666-6666-4666-8666-666666666666",
      "created_at": "2026-11-01T00:00:05Z"
    }
  ]
  ```

#### `POST /api/zones/{zone_id}/cycles` (`CurrentOperator`)
- Kiểm tra `zone_id` thuộc `user.farm_id` (`404` nếu không tìm thấy).
- Kiểm tra `zone_id` chưa có vụ trồng nào đang `status = 'active'` (ràng buộc `crop_cycles_one_active`). Nếu đã có → trả `409 Conflict` (`{"detail": "zone_already_has_active_cycle"}`).
- **Request JSON:**
  ```json
  {
    "crop_profile_id": "00000000-0000-4000-8000-000000000006",
    "started_at": "2026-11-12T08:00:00Z",
    "area_m2": 0.5,
    "notes": "Vụ xà lách baby leaf đợt 1"
  }
  ```
  - `started_at` tuỳ chọn (mặc định `now()` UTC).
  - `area_m2` tuỳ chọn: nếu không truyền thì lấy `zones.area_m2`. Nếu cả body lẫn `zones.area_m2` đều `null` hoặc `area_m2 <= 0` → `422 Unprocessable Entity`.
- **Hành vi khi tạo:**
  1. Kiểm tra `crop_profile_id` hợp lệ (`farm_id IS NULL` hoặc `farm_id == user.farm_id`, else `404`).
  2. Tạo bản ghi `crop_cycles(status='active', created_by=user.id)`.
  3. Tự động cập nhật `zones.crop_profile_id = body.crop_profile_id` (và `zones.planting_date = started_at.date()`), tăng `cfg_version_desired` (`bump_cfg_version`) và gửi `pg_notify(CHANNEL_WORKER, {"type": "cfg_updated", "greenhouse_id": str(gh.id)})` trước commit.
  4. Phát `pg_notify(CHANNEL_WS, {"farm_id": str(user.farm_id), "type": "crop_cycle", "data": {...}})` sự kiện `event="started"`.
- **Response `201 Created`:** trả `CropCycleResponse` như mẫu trên (`harvested_at: null`, `yield_kg: null`, `yield_kg_m2: null`, `status: "active"`).
- **Mã lỗi:** `401`, `403` (viewer), `404` (zone hoặc crop_profile không thuộc farm), `409` (zone đã có vụ active), `422` (thiếu/sai `area_m2`).

#### `POST /api/cycles/{cycle_id}/harvest` (`CurrentOperator`)
- Kiểm tra `cycle_id` thuộc `user.farm_id` qua `CropCycle → Zone → Greenhouse` (`404` nếu không tìm thấy).
- Nếu `cycle.status != 'active'` → `409 Conflict` (`{"detail": "cycle_not_active"}`).
- **Request JSON:**
  ```json
  {
    "harvested_at": "2026-12-05T07:30:00Z",
    "yield_kg": 1.72,
    "notes": "Thu hoạch toàn bộ khay Zone 1"
  }
  ```
  - `harvested_at` tuỳ chọn (mặc định `now()` UTC); nếu `harvested_at < cycle.started_at` hoặc `yield_kg < 0` → `422 Unprocessable Entity`.
- **Hành vi:**
  - Cập nhật `status = 'harvested'`, `harvested_at`, `yield_kg`, `notes` (nếu có).
  - Phát `pg_notify(CHANNEL_WORKER, {"type": "cycle_harvested", "cycle_id": str(cycle.id)})` (worker tính đặc trưng khí hậu trên `[started_at, harvested_at]` và ghi `yield_samples`, hoặc ghi lý do bỏ qua vào `crop_cycles.notes` nếu `coverage < ai.min_coverage`).
  - Phát `pg_notify(CHANNEL_WS, {"farm_id": str(user.farm_id), "type": "crop_cycle", "data": {...}})` sự kiện `event="harvested"`.
- **Response `200 OK`:** trả `CropCycleResponse` đã cập nhật.
- **Mã lỗi:** `401`, `403`, `404`, `409` (vụ không ở trạng thái `active`), `422` (`yield_kg < 0` hoặc `harvested_at < started_at`).

#### `POST /api/cycles/{cycle_id}/abandon` (`CurrentOperator`)
- Kiểm tra `cycle_id` thuộc `user.farm_id` (`404` nếu không tìm thấy).
- Nếu `cycle.status != 'active'` → `409 Conflict` (`{"detail": "cycle_not_active"}`).
- **Request JSON (tuỳ chọn body rỗng `{}`):**
  ```json
  {
    "notes": "Huỷ vụ do thay đổi kế hoạch canh tác"
  }
  ```
- **Hành vi:** cập nhật `status = 'abandoned'`, `notes` (nếu có); không tạo `yield_samples`. Phát `pg_notify(CHANNEL_WS, ...)` sự kiện `event="abandoned"`.
- **Response `200 OK`:** trả `CropCycleResponse` với `status: "abandoned"`.

---

### 3.3 Cảnh báo (`api/routers/alerts.py`)

- **`GET /api/alerts?state=&greenhouse_id=&limit=100`** (`CurrentViewer`):
  - Lọc bắt buộc theo `Greenhouse.farm_id == user.farm_id`.
  - Lọc tuỳ chọn `state ∈ {'raised','notified','acknowledged','resolved'}` hoặc `open` (`state != 'resolved'`), `greenhouse_id`. Sắp xếp `created_at DESC`.
  - Trả về các trường `AlertResponse`: `id, greenhouse_id, zone_id, alert_type, severity, state, dedupe_key, payload, created_at, notified_at, escalated_at, acknowledged_at, acked_by, resolved_at`.
- **`POST /api/alerts/{alert_id}/ack`** (`CurrentOperator`):
  - Kiểm tra alert thuộc `user.farm_id` (`404` nếu không tìm thấy).
  - Nếu `state == 'resolved'` → `409 Conflict`. Nếu `raised`/`notified` → chuyển `state = 'acknowledged'`, `acknowledged_at = now()`, `acked_by = user.id`.
  - Phát `pg_notify(CHANNEL_WS, ...)` sự kiện `alert`.

---

### 3.4 Web Push & Tuỳ chọn thông báo (`api/routers/push.py`)

- **`GET /api/push/public-key`** (`CurrentViewer`): trả `{"public_key": Settings.vapid_public_key}` (`503` nếu chưa cấu hình).
- **`POST /api/push/subscribe`** (`CurrentViewer`): nhận `{"endpoint": "https://...", "keys": {"p256dh": "...", "auth": "..."}}` (kèm `User-Agent`), upsert theo `endpoint`, trả `201`/`200`.
- **`DELETE /api/push/subscribe`** (`CurrentViewer`): nhận `{"endpoint": "..."}` (body hoặc query param), xóa subscription thuộc `user.id`.
- **`GET /api/me/notification-prefs`** & **`PUT /api/me/notification-prefs`** (`CurrentViewer`):
  - `PUT` body: `{"push_enabled": bool, "email_enabled": bool, "min_severity": "info" | "warning" | "critical"}`.

---

### 3.5 Dự báo năng suất (`api/routers/models.py`)

- **`GET /api/zones/{zone_id}/predictions?task=yield_forecast&from=&to=&limit=100`** (`CurrentViewer`):
  - Kiểm tra `zone_id` thuộc `user.farm_id` (`404` nếu không tìm thấy).
  - Query:
    - `task`: mặc định `"yield_forecast"` (chỉ hỗ trợ `"yield_forecast"` ở endpoint cấp zone; truyền giá trị khác → `422`).
    - `from`, `to`: lọc `ts >= from`, `ts <= to` (ISO 8601 UTC, tuỳ chọn).
    - `limit`: `1..500`, mặc định `100`. Sắp xếp `ts DESC`.
  - **Response `200 OK`:**
    ```json
    [
      {
        "id": "77777777-7777-4777-8777-777777777777",
        "ts": "2026-11-12T08:00:00Z",
        "task": "yield_forecast",
        "greenhouse_id": "22222222-2222-4222-8222-222222222222",
        "zone_id": "11111111-1111-4111-8111-111111111111",
        "crop_cycle_id": "55555555-5555-4555-8555-555555555555",
        "model_id": "88888888-8888-4888-8888-888888888888",
        "value": 2.76,
        "score": 0.92,
        "details": {
          "crop_code": "lettuce",
          "reference_kg_m2": 3.0,
          "interval": [2.25, 3.27],
          "window_hours": 168.0,
          "coverage": 0.96,
          "low_confidence": false,
          "ood_features": [],
          "features": {
            "t_mean": 20.8,
            "rh_mean": 76.2,
            "vpd_mean": 0.68,
            "dli_mean": 14.5,
            "soil_mean": 68.4
          }
        }
      }
    ]
    ```
  - **Mã lỗi:** `401`, `404` (zone không thuộc farm), `422` (`task` không hợp lệ hoặc `from > to`).

---

### 3.6 Gợi ý cây trồng (`api/routers/recommendations.py`)

#### `GET /api/greenhouses/{greenhouse_id}/recommendations` (`CurrentViewer`)
- Kiểm tra `greenhouse_id` thuộc `user.farm_id` (`404` nếu không tìm thấy).
- Truy vấn bản ghi mới nhất (`ts DESC LIMIT 1`) trong `predictions` có `greenhouse_id == id` và `task == 'crop_recommendation'`.
- Nếu nhà kính chưa từng có bản ghi gợi ý (hoặc chưa có mô hình active) → trả `200 OK` với `null` (UI hiển thị trạng thái chờ/"Chưa có mô hình").
- **Response `200 OK` (khi có dữ liệu):**
  ```json
  {
    "id": "99999999-9999-4999-8999-999999999999",
    "ts": "2026-11-12T08:00:00Z",
    "task": "crop_recommendation",
    "greenhouse_id": "22222222-2222-4222-8222-222222222222",
    "model_id": "88888888-8888-4888-8888-888888888888",
    "score": 0.94,
    "details": {
      "window_h": 336,
      "coverage": 0.98,
      "low_confidence": false,
      "ood_features": [],
      "climate_summary": {
        "t_mean": 19.8,
        "t_day_mean": 22.1,
        "t_night_mean": 17.5,
        "rh_mean": 74.5,
        "vpd_mean": 0.72,
        "dli_mean": 15.8
      },
      "features": {
        "t_mean": 19.8,
        "t_day_mean": 22.1,
        "t_night_mean": 17.5,
        "t_p95": 24.9,
        "t_p05": 15.2,
        "rh_mean": 74.5,
        "vpd_mean": 0.72,
        "vpd_std": 0.18,
        "frac_vpd_low": 0.04,
        "frac_vpd_high": 0.0,
        "frac_t_gt_30": 0.0,
        "frac_t_lt_12": 0.0,
        "gdd_per_day": 9.8,
        "dli_mean": 15.8,
        "soil_mean": null,
        "soil_std": null
      },
      "ranking": [
        {
          "crop_code": "strawberry",
          "crop_name": "Dâu tây",
          "relative_yield": 0.94,
          "expected_kg_m2": 3.76,
          "interval": [3.16, 4.36],
          "reasons": [
            "Nhiệt độ TB 19.8 °C nằm trong khoảng tối ưu 18–24 °C",
            "VPD TB 0.72 kPa nằm trong khoảng tối ưu 0.6–0.9 kPa",
            "DLI TB 15.8 mol/m²/ngày nằm trong khoảng tối ưu 15–22"
          ]
        },
        {
          "crop_code": "lettuce",
          "crop_name": "Xà lách",
          "relative_yield": 0.91,
          "expected_kg_m2": 2.73,
          "interval": [2.28, 3.18],
          "reasons": [
            "Nhiệt độ TB 19.8 °C nằm trong khoảng tối ưu 15–22 °C",
            "VPD TB 0.72 kPa nằm trong khoảng tối ưu 0.6–1.0 kPa",
            "DLI TB 15.8 mol/m²/ngày nằm trong khoảng tối ưu 12–17"
          ]
        },
        {
          "crop_code": "tomato_cherry",
          "crop_name": "Cà chua bi",
          "relative_yield": 0.76,
          "expected_kg_m2": 7.6,
          "interval": [6.1, 9.1],
          "reasons": [
            "Nhiệt độ TB 19.8 °C thấp hơn khoảng tối ưu 20–28 °C",
            "DLI TB 15.8 mol/m²/ngày thấp hơn khoảng tối ưu 20–30"
          ]
        }
      ],
      "all_candidates": [
        {"crop_code": "strawberry", "crop_name": "Dâu tây", "relative_yield": 0.94, "expected_kg_m2": 3.76, "interval": [3.16, 4.36]},
        {"crop_code": "lettuce", "crop_name": "Xà lách", "relative_yield": 0.91, "expected_kg_m2": 2.73, "interval": [2.28, 3.18]},
        {"crop_code": "tomato_cherry", "crop_name": "Cà chua bi", "relative_yield": 0.76, "expected_kg_m2": 7.6, "interval": [6.1, 9.1]},
        {"crop_code": "bell_pepper", "crop_name": "Ớt chuông", "relative_yield": 0.71, "expected_kg_m2": 5.68, "interval": [4.48, 6.88]},
        {"crop_code": "cucumber", "crop_name": "Dưa leo", "relative_yield": 0.64, "expected_kg_m2": 9.6, "interval": [7.35, 11.85]}
      ]
    }
  }
  ```

#### `POST /api/greenhouses/{greenhouse_id}/recommendations/refresh` (`CurrentOperator`)
- Kiểm tra `greenhouse_id` thuộc `user.farm_id` (`404` nếu không tìm thấy).
- Không nhận body bắt buộc (`{}` hoặc rỗng).
- Gửi `pg_notify(CHANNEL_WORKER, {"type": "recommend", "greenhouse_id": str(gh.id)})` (lưu ý dùng `COMMIT` trước khi client nhận `202` để worker đọc được trạng thái mới nhất). Worker tính lại gợi ý và phát kết quả qua WebSocket `prediction` (`task="crop_recommendation"`).
- **Response `202 Accepted`:**
  ```json
  {
    "status": "accepted",
    "greenhouse_id": "22222222-2222-4222-8222-222222222222"
  }
  ```
- **Mã lỗi:** `401`, `403` (viewer), `404` (greenhouse không thuộc farm).

---

### 3.7 Mô hình AI (`api/routers/models.py`)

- **Mô hình toàn cục & Cô lập tenant:**
  - Toàn hệ thống chỉ có mô hình toàn cục `task = 'yield'`, huấn luyện offline từ `yield_samples` gộp đa nhà kính.
  - Đã **bỏ** query `?zone_id=`. Các endpoint `/models*` chỉ trả metadata và số liệu tổng hợp, **tuyệt đối không** trả bất kỳ bản ghi `yield_samples` nào.
  - Kích hoạt mô hình được thực hiện bởi CLI `ml/train.py` theo Activation Gate; không mở endpoint kích hoạt thủ công qua API.

#### `GET /api/models` (`CurrentViewer`)
- Trả danh sách các phiên bản `ml_models` (`ORDER BY version DESC`).
- **Response `200 OK`:**
  ```json
  [
    {
      "id": "88888888-8888-4888-8888-888888888888",
      "task": "yield",
      "version": 2,
      "feature_version": 1,
      "trained_at": "2026-11-12T03:00:00Z",
      "n_samples": 1024,
      "n_greenhouses": 204,
      "source_mix": {"synthetic": 1000, "sim": 22, "real": 2, "public": 0},
      "crops": [
        {"crop_code": "lettuce", "n": 208, "reference_kg_m2": 3.0},
        {"crop_code": "strawberry", "n": 204, "reference_kg_m2": 4.0},
        {"crop_code": "tomato_cherry", "n": 206, "reference_kg_m2": 10.0},
        {"crop_code": "cucumber", "n": 202, "reference_kg_m2": 15.0},
        {"crop_code": "bell_pepper", "n": 204, "reference_kg_m2": 8.0}
      ],
      "metrics": {
        "test": {"mae_kg_m2": 0.48, "rmse_kg_m2": 0.63, "r2": 0.87, "mape": 0.095, "top1_acc": 0.86, "ndcg3": 0.94},
        "by_crop": {"lettuce": {"mae_kg_m2": 0.21}, "strawberry": {"mae_kg_m2": 0.31}},
        "by_source": {"synthetic": {"mae_kg_m2": 0.47}, "sim": {"mae_kg_m2": 0.58}, "real": {"n": 2, "mae_kg_m2": 0.35}},
        "feature_importance": [{"feature": "t_mean", "gain": 0.34}, {"feature": "dli_mean", "gain": 0.28}]
      },
      "baseline_metrics": {
        "B0": {"mae_kg_m2": 1.32, "rmse_kg_m2": 1.65, "r2": -0.02},
        "B1": {"mae_kg_m2": 0.81, "rmse_kg_m2": 1.04, "r2": 0.62}
      },
      "is_active": true,
      "notes": "Activated: test MAE 0.48 < B0 1.32, B1 0.81, prev v1 0.54"
    }
  ]
  ```

#### `GET /api/models/active` (`CurrentViewer`)
- Trả mô hình có `is_active = true` (hoặc `null` nếu chưa có mô hình nào được kích hoạt), **kèm** trường `feature_drift` trong 7 ngày gần nhất.
- **Cách tính `feature_drift` (thuần SQL/Python, không import ML, cô lập tenant):**
  - Lấy `train_stats` (mean, std của từng đặc trưng trên tập train toàn cục) lưu sẵn trong `ml_models.metrics.train_stats` khi `ml/train.py` huấn luyện.
  - Truy vấn các bản ghi `predictions` trong 7 ngày gần nhất (`ts >= now() - interval '7 days'`) thuộc **các nhà kính của `user.farm_id`** (`predictions.greenhouse_id IN (SELECT id FROM greenhouses WHERE farm_id = :farm_id)`), trích các giá trị số trong `details->'features'`.
  - Tính `recent_mean`, `recent_std`, `z_score = abs(recent_mean - train_mean) / max(train_std, 1e-6)` và `drifted = z_score >= 2.0` (khi có đủ mẫu, ví dụ `n_recent >= 5`).
- **Response `200 OK`:**
  ```json
  {
    "id": "88888888-8888-4888-8888-888888888888",
    "task": "yield",
    "version": 2,
    "feature_version": 1,
    "trained_at": "2026-11-12T03:00:00Z",
    "n_samples": 1024,
    "n_greenhouses": 204,
    "source_mix": {"synthetic": 1000, "sim": 22, "real": 2, "public": 0},
    "crops": [ "...": "..." ],
    "metrics": { "...": "..." },
    "baseline_metrics": { "...": "..." },
    "is_active": true,
    "notes": "Activated: test MAE 0.48 < B0 1.32, B1 0.81, prev v1 0.54",
    "feature_drift": {
      "window_days": 7,
      "n_predictions": 42,
      "features": {
        "t_mean": {"train_mean": 23.4, "train_std": 4.1, "recent_mean": 24.1, "recent_std": 1.8, "z_score": 0.17, "drifted": false},
        "vpd_mean": {"train_mean": 0.92, "train_std": 0.35, "recent_mean": 0.88, "recent_std": 0.21, "z_score": 0.11, "drifted": false},
        "dli_mean": {"train_mean": 17.5, "train_std": 5.2, "recent_mean": 16.9, "recent_std": 3.1, "z_score": 0.12, "drifted": false}
      }
    }
  }
  ```

#### `GET /api/models/{model_id}` (`CurrentViewer`)
- Trả chi tiết 1 mô hình theo `model_id` (`404` nếu không tồn tại), cùng schema như `GET /api/models/active` (bao gồm `feature_drift` 7 ngày tính trên `predictions` thuộc `user.farm_id`).

## 4. Mã lỗi HTTP chuẩn (MUST)

- `401 Unauthorized`: thiếu/sai/hết hạn JWT hoặc sai mật khẩu login.
- `403 Forbidden`: sai vai trò RBAC (`viewer` gọi endpoint `operator`/`owner`, hoặc `operator` gọi endpoint `owner`), hoặc ghép MAC thuộc farm khác.
- `404 Not Found`: tài nguyên không tồn tại hoặc thuộc farm khác (`greenhouse_id`, `zone_id`, `cycle_id`, `alert_id`, `crop_profile_id`, `model_id`).
- `409 Conflict`:
  - `detail="gateway_offline"` khi gọi `POST /api/greenhouses/{id}/commands` lúc gateway offline (spec mục 6.5 & 9).
  - Nhà kính đã có gateway khi gọi `POST /api/gateways`.
  - Zone đã có vụ trồng `active` khi gọi `POST /api/zones/{id}/cycles` (`zone_already_has_active_cycle`).
  - Vụ trồng không ở trạng thái `active` khi gọi `POST /api/cycles/{id}/harvest` hoặc `POST /api/cycles/{id}/abandon`.
  - Alert đã `resolved` khi gọi `POST /api/alerts/{id}/ack`.
- `422 Unprocessable Entity`: sai schema Pydantic (thiếu `duration_s` khi `action='on'`, sai MAC, `soil_dry_raw == soil_wet_raw`, `parameters_json` không hợp lệ `schema_version = 2`, `area_m2 <= 0` hoặc thiếu `area_m2` khi tạo vụ, `yield_kg < 0`, `harvested_at < started_at`, `task` không hợp lệ).
- `503 Service Unavailable`: `GET /api/push/public-key` khi server chưa cấu hình khóa VAPID.
