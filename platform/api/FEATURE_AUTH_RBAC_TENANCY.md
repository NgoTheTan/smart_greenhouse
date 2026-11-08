# Feature: Xác thực JWT, Phân quyền RBAC & Cô lập đa Tenant (`platform/api/`)

> Nguồn đặc tả: `docs/greenhub-spec.md` mục 3.2, 6.1, 7, 9, 12, 15 (Kịch bản D); `docs/DECISIONS.md`.

## 1. Mục tiêu & Phạm vi

Bảo vệ toàn bộ hệ thống API và WebSocket bằng JWT Bearer token, phân cấp quyền theo 3 vai trò (`viewer`, `operator`, `owner`), và đảm bảo cô lập tuyệt đối dữ liệu giữa các `farms` ở tầng ứng dụng (user thuộc Farm A không thể xem hay tác động tới nhà kính, node, cảnh báo, lệnh của Farm B).

- **Ngoài phạm vi:** Không dùng PostgreSQL Row-Level Security (RLS là MAY); không tích hợp OAuth2 bên thứ 3 hay Firebase Auth.

## 2. Trạng thái hiện thực trong repo

- **Đã hoàn thiện (M2):**
  - `platform/core/security.py`: Argon2id (`hash_password`, `verify_password`) và PyJWT HS256 (`create_access_token`, `decode_access_token`).
  - `platform/api/deps.py`: `get_current_user`, `require_min_role`, dependency shortcuts `CurrentViewer`, `CurrentOperator`, `CurrentOwner`, `DbSession`.
  - `platform/api/routers/auth.py`: `POST /api/auth/login`, `GET /api/me`.
  - `platform/api/routers/greenhouses.py`: `get_owned_greenhouse`, `GET /api/greenhouses`, `POST /api/greenhouses`, `GET /api/greenhouses/{gh_id}`.
  - `platform/api/main.py`: `GET /api/health` (kiểm tra kết nối DB cho Docker/Caddy healthcheck).
- **Cần lưu ý / mở rộng cho M3–M5:**
  - Các router mới (`alerts`, `push`, `models`, `experiments`) **MUST** sử dụng `CurrentViewer` / `CurrentOperator` / `CurrentOwner` và kiểm tra sở hữu `farm_id` qua join `Greenhouse` hoặc `Zone → Greenhouse`.
  - Nếu cần trang/API tạo user nhân viên (`operator`/`viewer`) cho `owner` (spec mục 9 ghi vai trò `owner` quản lý user), có thể bổ sung `POST /api/users` / `GET /api/users` gắn chặt `farm_id = user.farm_id` và `CurrentOwner`.

## 3. Cơ chế Xác thực & Phân quyền (MUST)

### 3.1 JWT & Password Hashing
- **Băm mật khẩu:** Argon2id (`argon2.PasswordHasher()`). Không lưu mật khẩu plaintext; khi seed dev dùng `hash_password(...)`.
- **Đăng nhập (`POST /api/auth/login`):**
  - Input: `{"email": "...", "password": "..."}` (so sánh email chuẩn hóa lowercase: `body.email.lower()`).
  - Sai email hoặc mật khẩu → `401 Unauthorized` (`"Email hoặc mật khẩu không đúng"`).
  - Thành công → trả `{"access_token": "<jwt>", "token_type": "bearer"}`.
- **Claims trong JWT:**
  - `sub`: `str(user.id)` (UUID)
  - `farm_id`: `str(user.farm_id)` (UUID)
  - `role`: `"viewer" | "operator" | "owner"`
  - `iat`, `exp`: mặc định hết hạn sau `Settings.jwt_expire_min` (`720` phút = 12 giờ), thuật toán `HS256`, bí mật `Settings.jwt_secret`.
- **Xác thực trên từng request (`get_current_user`):**
  - Bắt buộc header `Authorization: Bearer <token>`.
  - Thiếu/sai token/hết hạn/user không tồn tại trong DB → `401 Unauthorized`.

### 3.2 Ma trận phân quyền RBAC (`ROLE_RANK = {"viewer": 1, "operator": 2, "owner": 3}`)

Hàm `require_min_role(min_role)` cho phép vai trò cấp cao hơn kế thừa toàn bộ quyền cấp dưới (`owner >= operator >= viewer`). Vi phạm quyền → `403 Forbidden`.

| Nhóm chức năng | `viewer` | `operator` | `owner` |
|---|:---:|:---:|:---:|
| Xem thông tin bản thân (`GET /me`), tuỳ chọn Push/Notification của mình | ✓ | ✓ | ✓ |
| Xem danh sách nhà kính, zone, readings, DLI, predictions, models, experiments, alerts, commands, gateway status, config-sync | ✓ | ✓ | ✓ |
| Gửi lệnh điều khiển tay (`POST /commands`), đổi Auto/Manual (`PUT /modes`) | ✗ (403) | ✓ | ✓ |
| Xác nhận cảnh báo (`POST /alerts/{id}/ack`), đánh giá đúng/sai (`POST /alerts/{id}/feedback`) | ✗ (403) | ✓ | ✓ |
| Bắt đầu / dừng thí nghiệm (`POST /experiments`, `POST /experiments/{id}/stop`) | ✗ (403) | ✓ | ✓ |
| Tạo nhà kính (`POST /greenhouses`), cấp phát gateway (`POST /gateways`), xem & ghép node (`GET /nodes`, `POST /nodes/{mac}/pair`), hiệu chuẩn đất (`PUT /zones/{id}/calibration`) | ✗ (403) | ✗ (403) | ✓ |
| Sửa zone (`PUT /zones/{id}`: tên, `crop_profile_id`, `control_strategy`), sửa crop profile (`PUT /crop-profiles/{id}`) | ✗ (403) | ✗ (403) | ✓ |

### 3.3 Cô lập đa Tenant (`farm_id`)
- Mọi truy vấn đọc/ghi theo ID (`gh_id`, `zone_id`, `gateway_id`, `alert_id`, `experiment_id`, `crop_profile_id`) **MUST** kiểm tra điều kiện `farm_id == user.farm_id`.
- **Lưu ý đặc biệt với `crop_profiles`:** `farm_id IS NULL` là template hệ thống (mọi farm đều đọc được, nhưng khi sửa sẽ clone thành bản ghi mới thuộc `user.farm_id`); `farm_id = <other_farm>` tuyệt đối không đọc/sửa được.
- **Lưu ý đặc biệt với `device_nodes` khi ghép MAC (`pair_node`):** Nếu MAC đã tồn tại và thuộc một `greenhouse_id` của **farm khác**, trả `403 Forbidden` (`"MAC này đã thuộc về một farm khác"`).
- **WebSocket:** Kết nối `WS /ws?token=` giải mã `farm_id` từ JWT và chỉ đẩy các sự kiện `ws_events` có `event["farm_id"] == str(user.farm_id)`.

## 4. Hành vi mặc định khi tạo Nhà kính (`POST /api/greenhouses`)

- Tạo `Greenhouse(farm_id=user.farm_id, name=..., location=...)`.
- Nếu `body.zones` không được truyền, tự động tạo 2 zone demo mặc định:
  - Zone 1: `"Zone 1 – Cà chua bi"`, `crop_profile_id = TEMPLATE_TOMATO_DEMO_ID`, `pump_channel = 1`, `soil_dry_raw = 2900`, `soil_wet_raw = 1300`.
  - Zone 2: `"Zone 2 – Dâu tây"`, `crop_profile_id = TEMPLATE_STRAWBERRY_DEMO_ID`, `pump_channel = 2`, `soil_dry_raw = 2900`, `soil_wet_raw = 1300`.
- Khởi tạo ngay bản ghi `DeviceState` với `cfg_version_desired = 1`, `cfg_version_reported = 0`.
- Trả về `GreenhouseResponse` kèm `online`, `open_alerts`, `zones`.

## 5. Kiểm tra & Xác nhận

- Unit tests: `test_password_hash_and_jwt_roundtrip`, `test_rbac_and_gateway_offline_409` (kiểm tra 401 khi thiếu token, 403 khi `viewer` gọi quyền `operator`).
- Kiểm thử Kịch bản D (spec mục 15): tạo 2 farm riêng biệt (hoặc user farm A và simulator gắn với farm A vs user farm B) → user farm B gọi `GET /api/greenhouses` không thấy nhà kính của farm A, gọi trực tiếp `GET /api/greenhouses/{id_farm_A}` nhận `404`.
