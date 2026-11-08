# Feature: Đặc tả đầy đủ Hợp đồng REST API (`/api/*`) (`platform/api/`)

> Nguồn đặc tả: `docs/greenhub-spec.md` mục 6.2–6.7, 7.1, 8.3, 8.4, 9, 10, 12; `docs/DECISIONS.md`.

## 1. Mục tiêu & Phạm vi

Tổng hợp đầy đủ hợp đồng giao tiếp HTTP REST dưới tiền tố `/api` (OpenAPI tại `/api/docs`), bao gồm cả các endpoint đã hoàn thiện ở M2 và các endpoint còn thiếu cho M3–M5 để backend và frontend (`web/`) khớp nhau tuyệt đối.

## 2. Trạng thái hiện thực theo từng nhóm Endpoint

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
| Zone | `GET /api/zones/{id}`, `PUT /api/zones/{id}` | `viewer` / `owner` | **Đã xong** | `api/routers/zones.py` |
| Dữ liệu | `GET /api/zones/{id}/readings?from&to&agg=raw\|1m\|1h` | `viewer` | **Đã xong** | `api/routers/zones.py` |
| Dữ liệu | `GET /api/zones/{id}/dli?date=` | `viewer` | **Đã xong** | `api/routers/zones.py` |
| Crop Profile | `GET /api/crop-profiles`, `GET /api/crop-profiles/{id}`, `PUT /api/crop-profiles/{id}` | `viewer` / `owner` | **Đã xong** | `api/routers/zones.py` |
| Điều khiển | `POST /api/greenhouses/{id}/commands`, `PUT /api/greenhouses/{id}/modes` | `operator` | **Đã xong** | `api/routers/commands.py` |
| Điều khiển | `GET /api/greenhouses/{id}/commands` | `viewer` | **Đã xong** | `api/routers/commands.py` |
| Cảnh báo | `GET /api/alerts?state=` | `viewer` | **Cần làm (M3)** | `api/routers/alerts.py` |
| Cảnh báo | `POST /api/alerts/{id}/ack`, `POST /api/alerts/{id}/feedback` | `operator` | **Cần làm (M3)** | `api/routers/alerts.py` |
| Push & Prefs | `GET /api/push/public-key`, `POST /api/push/subscribe`, `DELETE /api/push/subscribe`, `PUT /api/me/notification-prefs` (+ `GET /api/me/notification-prefs` gợi ý cho UI) | `viewer` | **Cần làm (M3)** | `api/routers/push.py` |
| Dữ liệu AI | `GET /api/zones/{id}/predictions` | `viewer` | **Cần làm (M5)** | `api/routers/models.py` (hoặc `zones.py`) |
| Model ML | `GET /api/models?zone_id=`, `GET /api/models/{id}` | `viewer` | **Cần làm (M5)** | `api/routers/models.py` |
| Thí nghiệm | `POST /api/experiments`, `POST /api/experiments/{id}/stop`, `GET /api/experiments/{id}/kpis` (+ `GET /api/experiments?greenhouse_id=` cho UI) | `operator` / `viewer` | **Cần làm (M5)** | `api/routers/experiments.py` |

*(Gợi ý bổ sung tiện cho Web Console: `GET /api/greenhouses/{id}/actuator-logs` để vẽ lớp phủ lịch sử hoạt động bơm/quạt/tạo ẩm trên biểu đồ trang Zone hoặc dùng chung dữ liệu `commands`/`actuator_logs`.)*

## 3. Chi tiết các Endpoint M3–M5 cần hiện thực

### 3.1 Cảnh báo (`api/routers/alerts.py`)
- **`GET /api/alerts?state=&greenhouse_id=&limit=100`** (`CurrentViewer`):
  - Lọc bắt buộc theo `Greenhouse.farm_id == user.farm_id` (join `alerts.greenhouse_id = greenhouses.id`).
  - Lọc tuỳ chọn `state ∈ {'raised','notified','acknowledged','resolved'}` hoặc `open` (tiện cho UI: `state != 'resolved'`), `greenhouse_id`. Sắp xếp `created_at DESC`.
  - Trả về đầy đủ trường `Alert`: `id, greenhouse_id, zone_id, alert_type, severity, state, dedupe_key, payload, created_at, notified_at, escalated_at, acknowledged_at, acked_by, resolved_at, feedback, feedback_at`.
- **`POST /api/alerts/{alert_id}/ack`** (`CurrentOperator`):
  - Kiểm tra alert thuộc `user.farm_id` (`404` nếu không tìm thấy).
  - Nếu `state == 'resolved'` → `409 Conflict` (hoặc giữ nguyên không đổi). Nếu đang `raised`/`notified` → chuyển `state = 'acknowledged'`, `acknowledged_at = now()`, `acked_by = user.id`.
  - Phát `pg_notify(CHANNEL_WS, ...)` sự kiện `alert` cập nhật trạng thái tới Web Console.
- **`POST /api/alerts/{alert_id}/feedback`** (`CurrentOperator`):
  - Body: `{"feedback": "true_positive" | "false_positive"}`.
  - Kiểm tra sở hữu `farm_id`, lưu `alert.feedback` và `alert.feedback_at = now()`.

### 3.2 Web Push & Tuỳ chọn thông báo (`api/routers/push.py`)
- **`GET /api/push/public-key`** (`CurrentViewer`):
  - Trả `{"public_key": Settings.vapid_public_key}`. Nếu chưa cấu hình → `503 Service Unavailable`.
- **`POST /api/push/subscribe`** (`CurrentViewer`):
  - Body khớp với `sub.toJSON()` của browser `PushSubscription` (`web/src/lib/push.ts`):
    ```json
    {"endpoint": "https://...", "keys": {"p256dh": "...", "auth": "..."}}
    ```
    (kèm `Request.headers.get("user-agent")`).
  - Upsert theo `endpoint` (nếu `endpoint` đã tồn tại, cập nhật `user_id = user.id`, `p256dh`, `auth`, `user_agent`, `last_used_at = now()`). Trả `201`/`200`.
- **`DELETE /api/push/subscribe`** (`CurrentViewer`):
  - Nhận `{"endpoint": "..."}` (qua body hoặc query param `endpoint`, hỗ trợ cả hai hoặc `Body` chuẩn để UI dễ gọi). Chỉ xóa subscription có `user_id == user.id`.
- **`GET /api/me/notification-prefs`** & **`PUT /api/me/notification-prefs`** (`CurrentViewer`):
  - Đảm bảo tồn tại dòng `NotificationPref(user_id=user.id)` (tạo mặc định nếu chưa có).
  - `PUT` body: `{"push_enabled": bool, "email_enabled": bool, "min_severity": "info" | "warning" | "critical"}`.

### 3.3 Dự báo, Mô hình ML & Thí nghiệm (`api/routers/models.py`, `experiments.py`)
- **Lưu ý cực kỳ quan trọng:** Tuyệt đối **KHÔNG** import `joblib`, `pandas`, `sklearn`, `lightgbm` trong các router này! Chỉ truy vấn metadata từ các bảng SQL (`predictions`, `ml_models`, `experiment_runs`, `readings`, `actuator_logs`, `alerts`).
- **`GET /api/zones/{zone_id}/predictions?task=&limit=50`** (`CurrentViewer`):
  - Kiểm tra `zone_id` thuộc `user.farm_id`. Trả về các dự báo mới nhất (`ts DESC`), gồm `risk_forecast` (`score`, `horizon_min`) và `irrigation_eta` (`value` phút còn lại).
- **`GET /api/models?zone_id=&task=`** (`CurrentViewer`):
  - Lọc theo các zone thuộc `user.farm_id` (hoặc `zone_id IS NULL` nếu có model chung). Trả `version, task, trained_at, train_from, train_to, n_samples, source_mix, metrics, baseline_metrics, is_active, notes`, **cộng** thêm thống kê feature drift nếu được lưu trong `metrics`/`notes` hoặc tính gọn bằng SQL trên `readings` (trung bình/std gần đây vs lúc train).
- **`GET /api/models/{model_id}`** (`CurrentViewer`): chi tiết 1 model, kiểm tra `farm_id` qua `Zone → Greenhouse`.
- **`POST /api/experiments`** (`CurrentOperator`):
  - Body: `{"greenhouse_id": "<uuid>", "strategy": "fixed" | "adaptive", "notes": "..."}`.
  - Kiểm tra `greenhouse_id` thuộc `user.farm_id`.
  - Cập nhật `zones.control_strategy = body.strategy` cho các zone của nhà kính đó (hoặc cho phép truyền danh sách `zone_ids` tuỳ chọn) và đóng các `ExperimentRun` đang mở (`ended_at IS NULL`) trước khi tạo bản ghi mới `ExperimentRun(started_at=now())`.
- **`POST /api/experiments/{exp_id}/stop`** (`CurrentOperator`):
  - Kiểm tra sở hữu `farm_id`, đặt `ended_at = now()` nếu chưa dừng.
- **`GET /api/experiments/{exp_id}/kpis`** (`CurrentViewer`):
  - Tính 5 KPI bằng **truy vấn SQL thuần** trên khoảng `[started_at, coalesce(ended_at, now())]` của nhà kính đó (xem công thức chi tiết trong `ml/FEATURE_AI_ML_AND_EXPERIMENTS.md`):
    1. Số lần bật/tắt bơm, quạt mỗi giờ (từ `actuator_logs`).
    2. `%` thời gian VPD nằm trong `vpd.optimal` của từng zone (từ `readings` có `quality='ok'`).
    3. Overshoot ẩm đất: `max(soil_moisture - soil_max)` trong cửa sổ sau mỗi lần tưới.
    4. Tổng thời gian bơm (`SUM(duration_s)` trên `actuator_logs` của `pump_1`/`pump_2`).
    5. Số cảnh báo sai (`COUNT(*) WHERE feedback = 'false_positive'`).

## 4. Mã lỗi HTTP chuẩn (MUST)

- `401 Unauthorized`: thiếu/sai/hết hạn JWT hoặc sai mật khẩu login.
- `403 Forbidden`: sai vai trò RBAC (`viewer` gọi endpoint `operator`/`owner`), hoặc ghép MAC thuộc farm khác.
- `404 Not Found`: tài nguyên không tồn tại hoặc thuộc farm khác.
- `409 Conflict`:
  - `detail="gateway_offline"` khi gọi `POST /api/greenhouses/{id}/commands` lúc gateway offline (spec mục 6.5 & 9).
  - Nhà kính đã có gateway khi gọi `POST /api/gateways`.
- `422 Unprocessable Entity`: sai schema Pydantic (thiếu `duration_s` khi `action='on'`, sai MAC, `soil_dry_raw == soil_wet_raw`, `parameters_json` không hợp lệ).
