# Feature: Web Console React 18 (9 Trang & Biểu đồ Realtime) (`web/`)

> Nguồn đặc tả: `docs/greenhub-spec.md` mục 0, 6.2–6.7, 8.3, 8.4, 9, 10, 15; `docs/DECISIONS.md`.

## 1. Mục tiêu & Phạm vi

Xây dựng giao diện quản lý và vận hành **GreenHub Web Console** bằng React 18 + TypeScript: theo dõi vi khí hậu đa vùng trực tiếp qua WebSocket + REST, điều khiển thiết bị chấp hành kèm Auto/Manual và chiến lược `fixed`/`adaptive`, quản lý provisioning/ghép node/hiệu chuẩn ẩm đất, chỉnh sửa crop profile, xử lý & phản hồi cảnh báo, và theo dõi mô hình AI cùng thí nghiệm KPI.

- **Ngoài phạm vi:** Không làm app di động native; không thêm Grafana hay trang nhật ký `farm_activities`.

## 2. Trạng thái hiện thực trong repo

- **Đã có (khung khởi tạo M2):**
  - `web/package.json`: React `18.3.1`, React Router `6.28.0`, `@tanstack/react-query` `5.62.0`, Recharts `3.10.1`, Vite `6.0.5`, TypeScript `5.7.2`.
  - `web/vite.config.ts`: dev proxy `/api` → `http://localhost:8000` và `/ws` → `ws://localhost:8000` (`ws: true`).
  - `web/src/lib/api.ts`: helper `api<T>()` gắn `Authorization: Bearer` từ `localStorage['gh_token']`, ném `ApiError(status, body)`.
  - `web/src/lib/push.ts`: helper `subscribePush()` gọi `Notification.requestPermission()` + `pushManager.subscribe()` + `POST /push/subscribe`.
  - `web/src/App.tsx`, `web/src/index.css`, `web/src/main.tsx`: khung layout điều hướng, `HealthBadge` gọi `/api/health`, các route hiện mới render `<Placeholder />`.
- **Cần hiện thực đầy đủ (M3–M5):**
  - Auth context/guard (redirect `/login` khi chưa có token hoặc nhận `401`), hiển thị vai trò user (`viewer`/`operator`/`owner`) và ẩn/vô hiệu nút vượt quyền.
  - WebSocket hook (`useWebSocket`) kết nối `wss://<host>/ws?token=<jwt>` tự reconnect + cập nhật React Query cache / state realtime + hiển thị toast cảnh báo in-app & chuông/badge số alert chưa xử lý.
  - Toàn bộ 9 trang chức năng chi tiết bên dưới (responsive cho cả màn hình điện thoại và desktop).

## 3. Kiến trúc Frontend & Realtime

### 3.1 Quản lý trạng thái & WebSocket
- Dùng `@tanstack/react-query` cho REST fetching và invalidation.
- Một WebSocket client dùng chung (tại `AppShell` sau khi đăng nhập) kết nối `/ws?token=...`:
  - Nhận `telemetry` → nối điểm mới trực tiếp vào buffer biểu đồ trang Zone đang mở mà không cần reload toàn trang.
  - Nhận `alert` → hiện Toast góc màn hình (màu theo `severity`: đỏ `critical`, vàng `warning`, xanh `info`), cập nhật badge số alert mở trên thanh điều hướng/chuông, invalidate `['alerts']` và `['greenhouses']`.
  - Nhận `command_status` → cập nhật tức thì trạng thái lệnh (`pending → sent → applied | rejected | expired | timeout`) và `reported.actuators` trên trang Điều khiển/Zone.
  - Nhận `device_status` (kèm `node_discovered`) & `config_sync` → cập nhật badge online/offline, RSSI, đồng bộ `cfg_version`, và danh sách node mới phát hiện trên trang Thiết bị.
  - Nhận `prediction` → cập nhật ngay xác suất rủi ro & `"cần tưới sau ~N phút"` trên trang Zone.

### 3.2 Quy ước hiển thị & Ngôn ngữ (MUST)
- Ngôn ngữ hiển thị 100% **tiếng Việt** tự nhiên cho người vận hành nông nghiệp.
- Bảng phân biệt rõ dữ liệu thật vs mô phỏng (gắn nhãn/badge `"Mô phỏng"` nếu `is_simulated === true`).
- Responsive mobile-first/adaptive: trên điện thoại (`< 768px`), thanh navigation chuyển dạng tab dưới đáy hoặc menu gọn, bảng dài cuộn ngang hoặc chuyển dạng card.

## 4. Đặc tả chi tiết 9 Trang (Spec mục 10)

### Trang 1: Đăng nhập (`/login`)
- Form Email + Mật khẩu → gọi `POST /api/auth/login` → lưu token bằng `setToken()` → gọi `GET /api/me` → chuyển về `/`.
- Báo lỗi tiếng Việt rõ ràng khi sai tài khoản/mật khẩu (`401`).

### Trang 2: Tổng quan Farm (`/`)
- Gọi `GET /api/greenhouses`.
- Hiển thị danh sách tất cả nhà kính thuộc farm của user (bao gồm cả nhà kính thật và nhà kính giả lập từ simulator):
  - Tên, vị trí, trạng thái **Online / Offline** (từ `online`), badge **Mô phỏng** nếu gateway `is_simulated`, số **Cảnh báo đang mở** (`open_alerts`).
  - Danh sách các Zone trong nhà kính (tên zone, cây trồng, chiến lược `fixed`/`adaptive`) + nút truy cập nhanh vào **Trang Zone (`/zones/:id`)** và **Điều khiển**.
- Nút `"Tạo nhà kính mới"` (chỉ hiện với `owner`) gọi `POST /api/greenhouses`.

### Trang 3: Chi tiết Zone (`/zones/:id`)
- Khối chọn khoảng thời gian (`15 phút`, `1 giờ`, `6 giờ`, `24 giờ`, `7 ngày`) và độ mịn tự động chọn `agg=raw|1m|1h`.
- **Biểu đồ trực tiếp (Recharts v3):**
  1. **Nhiệt độ (`°C`) & Độ ẩm (`%RH`)**.
  2. **VPD (`kPa`):** có vùng tô màu dải tối ưu **`[vpd.optimal[0], vpd.optimal[1]]`** (`ReferenceArea` màu xanh nhạt) và đường ngưỡng `vpd.low_crit` / `vpd.high_crit` (`ReferenceLine`).
  3. **Ẩm đất (`%`):** kèm ngưỡng `soil_moisture_pct.min` và `max`.
  4. **Ánh sáng (`lux`) & Thẻ DLI trong ngày (`mol/m²/ngày`):** gọi `GET /api/zones/{id}/dli`.
  - **Lớp phủ trạng thái actuator & điểm alert:** hiển thị dải/mốc thời gian bơm/quạt/tạo ẩm đã chạy và đánh dấu các mốc alert xuất hiện trên trục thời gian biểu đồ.
  - Đánh dấu/cảnh báo trực quan nếu điểm gần nhất có `quality != 'ok'` (`stuck`, `spike`, `dropout`, `out_of_range`).
- **Khung AI (`GET /api/zones/{id}/predictions` + WS `prediction`):**
  - Hiển thị **Xác suất rủi ro nấm** (`risk_forecast.score` dạng `%` + thanh mức độ + chân trời `horizon_min` phút).
  - Hiển thị **"Cần tưới sau ~N phút"** (`irrigation_eta.value`, hoặc trạng thái đang ổn định/đến hạn tưới nếu `<= 0` hay `null`).
- **Khu vực Điều khiển nhanh / Liên kết tới khối Điều khiển của nhà kính.**

### Trang 4: Điều khiển (tích hợp trên `/zones/:id` hoặc `/greenhouses/:id/control`)
- Với 4 actuator (`pump_1`, `pump_2`, `fan`, `mist`) của nhà kính:
  - Hiển thị trạng thái thực tế (`reported.actuators`: Đang BẬT / TẮT).
  - **Công tắc Auto / Manual** (kèm chọn thời hạn manual, ví dụ 15p / 30p / 60p hoặc không giới hạn) → gọi `PUT /api/greenhouses/{id}/modes`.
  - Nút **BẬT** (nhập/chọn `duration_s` bắt buộc) và **TẮT** → gọi `POST /api/greenhouses/{id}/commands` (chỉ mở cho `operator`/`owner`; bắt lỗi `409 gateway_offline` báo rõ *"Gateway đang offline, không thể gửi lệnh"*).
  - Lưu ý hiển thị cảnh báo trực quan quy tắc interlock quạt ↔ máy tạo ẩm.
- **Chọn chiến lược điều khiển theo Zone (`fixed` / `adaptive`):** gọi `PUT /api/zones/{id}` (hoặc qua nút bắt đầu thí nghiệm).
- **Bảng lịch sử lệnh gần nhất (`GET /api/greenhouses/{id}/commands` + WS `command_status`):** hiển thị tiến trình `pending → sent → applied / rejected (kèm reject_reason) / expired / timeout`.

### Trang 5: Thiết bị (`/devices`)
- **Danh sách Gateway theo nhà kính (`GET /gateways/{id}/status` + `GET /greenhouses/{id}/config-sync`):**
  - Trạng thái Online/Offline, `last_seen`, cường độ tín hiệu `RSSI` (dBm), `fw_version`, `is_simulated`.
  - Trạng thái đồng bộ cấu hình: **`cfg_version_reported` / `cfg_version_desired`** kèm badge **"Đã đồng bộ"** (xanh) hoặc **"Đang chờ"** (vàng).
  - Nút **"Cấp phát Gateway"** (`POST /api/gateways`, chỉ `owner`): mở modal hiển thị **`mqtt_username`, `mqtt_password` (CHỈ HIỂN THỊ 1 LẦN, có nút Copy!), `host`, `port`, `farm_id`, `greenhouse_id`** để nạp vào Captive Portal của ESP32.
- **Node ESP32 (`GET /nodes` + WS `node_discovered`):**
  - Mục **"Phát hiện node lạ" (`status=discovered`):** hiện MAC, RSSI, firmware, thời gian thấy lần đầu + dropdown chọn Zone + nút **"Ghép vào Zone"** (`POST /api/nodes/{mac}/pair`).
  - **Fallback nhập MAC thủ công:** form nhập trực tiếp MAC (`AA:BB:CC:DD:EE:01`) + chọn Zone → gọi `POST /api/nodes/{mac}/pair`.
  - Danh sách node đã ghép (`status=paired`), hiển thị `last_seen`, `rssi`, `battery_mv`.
- **Hiệu chuẩn ẩm đất 2 điểm (`PUT /api/zones/{id}/calibration`):**
  - Chọn Zone → nhập `soil_dry_raw` (đo trong không khí khô) và `soil_wet_raw` (đo trong đất ẩm bão hoà) → Lưu → tự động tăng `cfg_version` và hiện trạng thái chờ đồng bộ xuống node.

### Trang 6: Crop Profile (`/crop-profiles`)
- Liệt kê các profile hệ thống (`Cà chua bi real/demo`, `Dâu tây real/demo`) và bản sao riêng của farm (`GET /api/crop-profiles`).
- Cho phép gán profile cho từng Zone (`PUT /api/zones/{id}`).
- Form chỉnh sửa đầy đủ các nhóm tham số của `parameters_json` (VPD `optimal`, `low_crit`, `low_off`, `high_crit`, `leaf_offset_c`; Nhiệt độ tối ưu; Ẩm đất `min/max`; Bệnh `rh_gt`, `temp_range_c`, `fungal_minutes_alert`; Tưới `max_run_s`, `min_gap_s`, `max_total_s_per_hour`, `soil_settle_s`; Quạt `min_on_s`, `max_on_s`; Tạo ẩm `max_on_s`, `lockout_s`; Rủi ro `vpd_low_duration_min`, `horizon_min`, `trend_windows_min`; `sample_interval_s`; Failsafe `temp_critical_high_c`, `soil_moisture_critical_low_pct`).
- Lưu (`PUT /api/crop-profiles/{id}`) → tự động đồng bộ `cfg` xuống gateway (lưu ý giải thích cho user nếu đang sửa template hệ thống sẽ tự tạo bản sao riêng cho farm).

### Trang 7: Cảnh báo (`/alerts`)
- Bộ lọc theo trạng thái (`Đang mở`, `Đã xác nhận`, `Đã giải quyết`, `Tất cả`) → `GET /api/alerts`.
- Thẻ/dòng cảnh báo hiển thị: loại cảnh báo (tiếng Việt dễ hiểu), `severity` (`info`/`warning`/`critical`), zone/nhà kính, thời điểm phát sinh, nội dung chi tiết (`payload`), trạng thái (`raised` / `notified` / `acknowledged` / `resolved`), mốc `escalated_at` nếu đã leo thang.
- Thao tác (cho `operator`/`owner`):
  - Nút **"Xác nhận (Ack)"** (`POST /api/alerts/{id}/ack`).
  - Nút phản hồi **"Đúng (`true_positive`)"** / **"Sai (`false_positive`)"** (`POST /api/alerts/{id}/feedback`) để phục vụ đánh giá mô hình A3 và KPI thí nghiệm.

### Trang 8: Model & Thí nghiệm (`/models`)
- **Bảng Mô hình AI (`GET /api/models`):**
  - Liệt kê theo Zone & Task (`risk_forecast`, `irrigation_eta`, `pump_response`, `fan_response`): `version`, ngày huấn luyện (`trained_at`), `n_samples`, `source_mix` (`real` vs `sim`), trạng thái **`Đang kích hoạt (Active)`** vs không kích hoạt + `notes`.
  - So sánh **Metrics của mô hình vs Baseline** (PR-AUC/F1 cho `risk_forecast`; MAE phút cho `irrigation_eta`; số sự kiện/sai số cho `pump_response`/`fan_response`).
  - Hiển thị **Dấu hiệu lệch dữ liệu (Data Drift)**: so sánh mean/std gần đây với lúc train (cảnh báo nếu phân phối lệch đáng kể).
- **Quản lý Thí nghiệm Fixed vs Adaptive (`POST /api/experiments`, `POST /api/experiments/{id}/stop`, `GET /api/experiments/{id}/kpis`):**
  - Chọn nhà kính + chiến lược (`fixed` hoặc `adaptive`) + ghi chú → **"Bắt đầu thí nghiệm"** / **"Dừng thí nghiệm"**.
  - Bảng so sánh 5 KPI giữa các phiên chạy `fixed` và `adaptive`: số lần bật/tắt bơm & quạt mỗi giờ, `%` thời gian VPD trong dải tối ưu, overshoot ẩm đất, tổng thời gian bơm, số cảnh báo sai.

### Trang 9: Cài đặt Thông báo (`/settings/notifications`)
- Khối **Web Push:**
  - Hiển thị trạng thái quyền trình duyệt (`Notification.permission`) & đăng ký hiện tại.
  - Nút **"Bật thông báo đẩy (Web Push)"** gọi `subscribePush()` (bắt buộc kích hoạt từ sự kiện click chuột/chạm của người dùng) và nút hủy đăng ký (`DELETE /api/push/subscribe`).
  - **Hộp hướng dẫn riêng cho iOS (16.4+):** ghi rõ người dùng iPhone/iPad phải dùng Safari chọn **Share → Add to Home Screen (Thêm vào Màn hình chính)** rồi mở từ biểu tượng trên màn hình chính mới bật được Web Push.
  - Lưu ý ngắn gọn về giới hạn của Web Push (chế độ Không làm phiền có thể chặn push → hệ thống luôn có lớp dự phòng Email leo thang & Buzzer).
- Khối **Tuỳ chọn nhận thông báo (`PUT /api/me/notification-prefs`):**
  - Bật/tắt Push (`push_enabled`), bật/tắt Email leo thang (`email_enabled`), chọn mức độ tối thiểu (`min_severity`: `info` | `warning` | `critical`).

## 5. Kiểm tra & Xác nhận

- `npm run build --prefix web` (`tsc -b && vite build`) thành công 0 lỗi TypeScript.
- Kiểm tra responsive trên DevTools kích thước mobile (`390×844`) và desktop (`1280×800`).
- Chạy trọn 5 kịch bản demo A–E qua giao diện web thật trên HTTPS (`https://localhost` hoặc domain DuckDNS).
