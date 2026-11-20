# Feature: Xác thực JWT, Một quyền người dùng (`owner`) & Cô lập đa Tenant (`platform/api/`)

> Nguồn đặc tả: `docs/greenhub-spec.md` mục 3.2, 6.1, 7, 9, 12, 15 (Kịch bản D); `docs/DECISIONS.md`.

## 1. Mục tiêu & Phạm vi

Bảo vệ toàn bộ hệ thống API và WebSocket bằng JWT Bearer token với **một vai trò người dùng duy nhất (`owner`)** để quản lý toàn bộ nhà kính thuộc trang trại của mình, và đảm bảo cô lập tuyệt đối dữ liệu giữa các `farms` ở tầng ứng dụng (user thuộc Farm A không thể xem hay tác động tới nhà kính, zone, vụ trồng, node, cảnh báo, lệnh, dự báo của Farm B).

- **Ngoài phạm vi:** Không phân cấp nhiều vai trò (`viewer`/`operator`); không dùng PostgreSQL Row-Level Security (RLS là MAY); không tích hợp OAuth2 bên thứ 3 hay Firebase Auth.

## 2. Trạng thái hiện thực trong repo

- **Đã hoàn thiện:**
  - `platform/core/security.py`: Argon2id (`hash_password`, `verify_password`) và PyJWT HS256 (`create_access_token`, `decode_access_token`).
  - `platform/api/deps.py`: `get_current_user`, dependency shortcuts `CurrentUser`, `DbSession`.
  - `platform/api/routers/auth.py`: `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/me`.
  - `platform/api/routers/greenhouses.py`: `get_owned_greenhouse`, `GET /api/greenhouses`, `POST /api/greenhouses`, `GET /api/greenhouses/{gh_id}`.
  - `platform/api/main.py`: `GET /api/health` (kiểm tra kết nối DB cho Docker/Caddy healthcheck).
- **Quy tắc cho mọi router nghiệp vụ:**
  - Toàn bộ router nghiệp vụ (`alerts`, `commands`, `cycles`, `devices`, `greenhouses`, `models`, `push`, `recommendations`, `zones`) **MUST** sử dụng `CurrentUser` và kiểm tra sở hữu `farm_id` qua `Greenhouse`, `Zone → Greenhouse`, hoặc `CropCycle → Zone → Greenhouse`.

## 3. Cơ chế Xác thực & Cô lập Tenant (MUST)

### 3.1 JWT & Password Hashing
- **Băm mật khẩu:** Argon2id (`argon2.PasswordHasher()`). Không lưu mật khẩu plaintext; khi seed dev dùng `hash_password(...)`.
- **Đăng ký (`POST /api/auth/register`):**
  - Input: `{"email": "...", "password": "...", "farm_name": "..."}`.
  - Tạo `Farm` mới + `User` mới gắn `role = "owner"` + `NotificationPref` mặc định → trả `{"access_token": "<jwt>", "token_type": "bearer"}`.
- **Đăng nhập (`POST /api/auth/login`):**
  - Input: `{"email": "...", "password": "..."}` (so sánh email chuẩn hóa lowercase: `body.email.lower()`).
  - Sai email hoặc mật khẩu → `401 Unauthorized` (`"Email hoặc mật khẩu không đúng"`).
  - Thành công → trả `{"access_token": "<jwt>", "token_type": "bearer"}`.
- **Claims trong JWT:**
  - `sub`: `str(user.id)` (UUID)
  - `farm_id`: `str(user.farm_id)` (UUID)
  - `role`: `"owner"`
  - `iat`, `exp`: mặc định hết hạn sau `Settings.jwt_expire_min` (`720` phút = 12 giờ), thuật toán `HS256`, bí mật `Settings.jwt_secret`.
- **Xác thực trên từng request (`get_current_user`):**
  - Bắt buộc header `Authorization: Bearer <token>`.
  - Thiếu/sai token/hết hạn/user không tồn tại trong DB → `401 Unauthorized`.

### 3.2 Quyền hạn của vai trò duy nhất (`owner`)

Mọi người dùng đăng nhập thành công (`CurrentUser`, `role = "owner"`) đều có toàn quyền trên **chính trang trại (`farm_id`) của mình**:

- Xem thông tin bản thân (`GET /me`), tuỳ chọn Push/Notification (`GET/PUT /me/notification-prefs`, `POST/DELETE /push/subscribe`).
- Xem & tạo nhà kính (`GET/POST /greenhouses`), đồng bộ cấu hình (`GET /greenhouses/{id}/config-sync`).
- Quản lý thiết bị: cấp phát gateway (`POST /gateways`), xem trạng thái gateway (`GET /gateways/{id}/status`), xem & ghép node (`GET /nodes`, `POST /nodes/{mac}/pair`), hiệu chuẩn ẩm đất (`PUT /zones/{id}/calibration`).
- Giám sát & cấu hình zone/cây trồng: xem readings, DLI, cập nhật zone (`PUT /zones/{id}`), xem/sửa crop profile (`GET/PUT /crop-profiles`).
- Vận hành & cảnh báo: gửi lệnh điều khiển (`POST /commands`), đổi Auto/Manual (`PUT /modes`), xem & xác nhận cảnh báo (`GET /alerts`, `POST /alerts/{id}/ack`).
- Quản lý vụ trồng & AI: tạo/thu hoạch/huỷ vụ (`POST /zones/{id}/cycles`, `POST /cycles/{id}/harvest`, `POST /cycles/{id}/abandon`), xem dự báo/gợi ý & làm mới gợi ý (`POST /greenhouses/{id}/recommendations/refresh`), xem metadata mô hình (`GET /models*`).

### 3.3 Cô lập đa Tenant (`farm_id`)
- Mọi truy vấn đọc/ghi theo ID (`gh_id`, `zone_id`, `cycle_id`, `gateway_id`, `alert_id`, `crop_profile_id`) **MUST** kiểm tra điều kiện `farm_id == user.farm_id`.
- **Lưu ý đặc biệt với `crop_profiles`:** `farm_id IS NULL` là template hệ thống (mọi farm đều đọc được, nhưng khi sửa sẽ clone thành bản ghi mới thuộc `user.farm_id`); `farm_id = <other_farm>` tuyệt đối không đọc/sửa được.
- **Lưu ý đặc biệt với `device_nodes` khi ghép MAC (`pair_node`):** Nếu MAC đã tồn tại và thuộc một `greenhouse_id` của **farm khác**, trả `403 Forbidden` (`"MAC này đã thuộc về một farm khác"`).
- **Quy tắc cô lập tenant với `yield_samples` và mô hình toàn cục (MUST):**
  - Bảng `yield_samples` lưu tập mẫu gộp từ nhiều nhà kính (`real`, `sim`, `synthetic`, `public`) dùng cho huấn luyện offline **một mô hình toàn cục** (quyết định kiến trúc có chủ đích trong `docs/DECISIONS.md`).
  - **Tuyệt đối không** mở bất kỳ REST endpoint nào đọc, liệt kê hoặc xuất `yield_samples` ra ngoài.
  - Các endpoint `GET /api/models`, `GET /api/models/active`, `GET /api/models/{id}` **chỉ trả số liệu tổng hợp** của mô hình toàn cục (`n_samples`, `n_greenhouses`, `source_mix`, `crops`, `metrics`, `baseline_metrics`, `notes`), không bao giờ tiết lộ dữ liệu từng nhà kính hay từng vụ của farm khác.
  - Thống kê `feature_drift` 7 ngày gần nhất trả kèm ở `GET /api/models/active` và `GET /api/models/{id}` chỉ tổng hợp từ các bản ghi `predictions` thuộc nhà kính của chính `user.farm_id` so với `train_stats` tổng hợp của mô hình.
- **WebSocket:** Kết nối `WS /ws?token=` giải mã `farm_id` từ JWT và chỉ đẩy các sự kiện `ws_events` có `event["farm_id"] == str(user.farm_id)`.

## 4. Hành vi mặc định khi tạo Nhà kính (`POST /api/greenhouses`)

- Tạo `Greenhouse(farm_id=user.farm_id, name=..., location=...)`.
- Nếu `body.zones` không được truyền, tự động tạo 2 zone demo mặc định:
  - Zone 1: `"Zone 1 – Cà chua bi"`, `crop_profile_id = TEMPLATE_TOMATO_DEMO_ID`, `pump_channel = 1`, `soil_dry_raw = 2900`, `soil_wet_raw = 1300`.
  - Zone 2: `"Zone 2 – Dâu tây"`, `crop_profile_id = TEMPLATE_STRAWBERRY_DEMO_ID`, `pump_channel = 2`, `soil_dry_raw = 2900`, `soil_wet_raw = 1300`.
- Khởi tạo ngay bản ghi `DeviceState` với `cfg_version_desired = 1`, `cfg_version_reported = 0`.
- Trả về `GreenhouseResponse` kèm `online`, `open_alerts`, `zones`.

## 5. Kiểm tra & Xác nhận

- Unit tests: `test_password_hash_and_jwt_roundtrip`, `test_auth_and_gateway_offline_409` (kiểm tra 401 khi thiếu/sai token hoặc user không tồn tại, token hợp lệ trả về quyền `owner`, `409 gateway_offline`, không lộ `yield_samples`).
- Kiểm thử Kịch bản D (spec mục 15): tạo 2 farm riêng biệt (hoặc user farm A và simulator gắn với farm A vs user farm B) → user farm B gọi `GET /api/greenhouses` không thấy nhà kính của farm A, gọi trực tiếp `GET /api/greenhouses/{id_farm_A}` nhận `404`.
