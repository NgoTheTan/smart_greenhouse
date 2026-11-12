# Feature: Web Console React 18 (10 Trang & Biểu đồ Realtime) (`web/`)

> Nguồn đặc tả: `docs/greenhub-spec.md` mục 0, 6.2–6.7, 8, 9, 10, 15; `docs/DECISIONS.md`. Tài liệu AI liên quan: [ml/FEATURE_AI_YIELD_AND_RECOMMENDATION.md](../ml/FEATURE_AI_YIELD_AND_RECOMMENDATION.md).

## 1. Mục tiêu & Phạm vi

Xây dựng giao diện quản lý và vận hành **GreenHub Web Console** bằng React 18 + TypeScript: theo dõi vi khí hậu đa vùng trực tiếp qua WebSocket + REST, điều khiển thiết bị chấp hành kèm Auto/Manual, quản lý provisioning/ghép node/hiệu chuẩn ẩm đất, chỉnh sửa crop profile, quản lý **vụ trồng** (bắt đầu/thu hoạch), xử lý cảnh báo, xem **dự báo năng suất** theo zone, **gợi ý cây trồng** theo nhà kính và theo dõi **mô hình AI năng suất toàn cục**.

- **Ngoài phạm vi:** Không làm app di động native; không thêm Grafana hay trang nhật ký `farm_activities`; không có giao diện chọn chiến lược điều khiển (rule engine chỉ có một chiến lược hysteresis cố định); không có nút phản hồi đúng/sai cho cảnh báo; không có trang/thao tác huấn luyện mô hình (huấn luyện chạy offline bằng `python -m ml.train`).

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
  - Toàn bộ 10 trang chức năng chi tiết bên dưới (responsive cho cả màn hình điện thoại và desktop). Trang **Gợi ý cây trồng**, **Mô hình AI** và khung AI ở trang Zone thuộc M5; nút Bắt đầu vụ/Thu hoạch SHOULD có từ M4 (để bắt đầu vụ xà lách thật).

## 3. Kiến trúc Frontend & Realtime

### 3.1 Quản lý trạng thái & WebSocket
- Dùng `@tanstack/react-query` cho REST fetching và invalidation.
- Một WebSocket client dùng chung (tại `AppShell` sau khi đăng nhập) kết nối `/ws?token=...`:
  - Nhận `telemetry` → nối điểm mới trực tiếp vào buffer biểu đồ trang Zone đang mở mà không cần reload toàn trang.
  - Nhận `alert` → hiện Toast góc màn hình (màu theo `severity`: đỏ `critical`, vàng `warning`, xanh `info`), cập nhật badge số alert mở trên thanh điều hướng/chuông, invalidate `['alerts']` và `['greenhouses']`.
  - Nhận `command_status` → cập nhật tức thì trạng thái lệnh (`pending → sent → applied | rejected | expired | timeout`) và `reported.actuators` trên trang Điều khiển/Zone.
  - Nhận `device_status` (kèm `node_discovered`) & `config_sync` → cập nhật badge online/offline, RSSI, đồng bộ `cfg_version`, và danh sách node mới phát hiện trên trang Thiết bị.
  - Nhận `prediction` → rẽ nhánh theo `data.task`:
    - `yield_forecast` → cập nhật khung AI trang Zone tương ứng (`zone_id`) và invalidate `['predictions', zoneId]`.
    - `crop_recommendation` → cập nhật trang Gợi ý cây trồng của nhà kính (`greenhouse_id`), invalidate `['recommendations', greenhouseId]`, tắt trạng thái "Đang làm mới…" nếu đang chờ.
  - Nhận `crop_cycle` (khi vụ bắt đầu/thu hoạch/huỷ) → invalidate `['cycles', zoneId]`, `['zones', zoneId]` và `['greenhouses']` (cây trồng của zone có thể đổi theo vụ).

### 3.2 Quy ước hiển thị & Ngôn ngữ (MUST)
- Ngôn ngữ hiển thị 100% **tiếng Việt** tự nhiên cho người vận hành nông nghiệp; tên cây hiển thị bằng tên tiếng Việt của crop profile (không hiển thị thô `crop_code` trừ ở bảng kỹ thuật trang Mô hình AI).
- Bảng phân biệt rõ dữ liệu thật vs mô phỏng (gắn nhãn/badge `"Mô phỏng"` nếu `is_simulated === true`).
- Mọi kết quả AI (dự báo năng suất, gợi ý cây trồng) MUST ghi rõ là **ước tính**, hiển thị khoảng tin cậy `p10–p90` và badge **"Độ tin cậy thấp"** khi `low_confidence === true` (kèm tooltip lý do: dữ liệu thiếu `coverage` thấp, cửa sổ < 24 giờ – chế độ demo, hoặc khí hậu nằm ngoài dải dữ liệu huấn luyện).
- Khi không có mô hình active (API trả rỗng/`404` tương ứng), hiển thị trạng thái trống **"Chưa có mô hình"** thay vì lỗi.
- Định dạng số: năng suất `kg/m²` 1 chữ số thập phân; năng suất tương đối hiển thị dạng `%` (`relative_yield × 100`, làm tròn số nguyên).
- Responsive mobile-first/adaptive: trên điện thoại (`< 768px`), thanh navigation chuyển dạng tab dưới đáy hoặc menu gọn, bảng dài cuộn ngang hoặc chuyển dạng card.

## 4. Đặc tả chi tiết 10 Trang (Spec mục 10)

### Trang 1: Đăng nhập (`/login`)
- Form Email + Mật khẩu → gọi `POST /api/auth/login` → lưu token bằng `setToken()` → gọi `GET /api/me` → chuyển về `/`.
- Báo lỗi tiếng Việt rõ ràng khi sai tài khoản/mật khẩu (`401`).

### Trang 2: Tổng quan Farm (`/`)
- Gọi `GET /api/greenhouses`.
- Hiển thị danh sách tất cả nhà kính thuộc farm của user (bao gồm cả nhà kính thật và nhà kính giả lập từ simulator):
  - Tên, vị trí, trạng thái **Online / Offline** (từ `online`), badge **Mô phỏng** nếu gateway `is_simulated`, số **Cảnh báo đang mở** (`open_alerts`).
  - Danh sách các Zone trong nhà kính (tên zone, cây trồng, trạng thái vụ: "Đang trồng – ngày thứ N" hoặc "Chưa có vụ") + nút truy cập nhanh vào **Trang Zone (`/zones/:id`)** và **Điều khiển**.
  - Liên kết **"Gợi ý cây trồng"** tới `/greenhouses/:id/recommendations`; SHOULD hiển thị tóm tắt cây top-1 nếu đã có gợi ý.
- Nút `"Tạo nhà kính mới"` (chỉ hiện với `owner`) gọi `POST /api/greenhouses`.

### Trang 3: Chi tiết Zone (`/zones/:id`)
- Khối chọn khoảng thời gian (`15 phút`, `1 giờ`, `6 giờ`, `24 giờ`, `7 ngày`) và độ mịn tự động chọn `agg=raw|1m|1h`.
- **Biểu đồ trực tiếp (Recharts v3):**
  1. **Nhiệt độ (`°C`) & Độ ẩm (`%RH`)**.
  2. **VPD (`kPa`):** có vùng tô màu dải tối ưu **`[vpd.optimal[0], vpd.optimal[1]]`** (`ReferenceArea` màu xanh nhạt) và đường ngưỡng `vpd.low_crit` / `vpd.high_crit` (`ReferenceLine`).
  3. **Ẩm đất (`%`):** kèm ngưỡng `soil_moisture_pct.min` và `max`.
  4. **Ánh sáng (`lux`) & Thẻ DLI trong ngày (`mol/m²/ngày`):** gọi `GET /api/zones/{id}/dli`; SHOULD so với dải `light.dli_optimal` của crop profile.
  - **Lớp phủ trạng thái actuator & điểm alert:** hiển thị dải/mốc thời gian bơm/quạt/tạo ẩm đã chạy và đánh dấu các mốc alert xuất hiện trên trục thời gian biểu đồ.
  - Đánh dấu/cảnh báo trực quan nếu điểm gần nhất có `quality != 'ok'` (`stuck`, `spike`, `dropout`, `out_of_range`) – kết quả của kiểm tra chất lượng dữ liệu (luật).
- **Khung AI – Vụ trồng & Năng suất dự kiến (`GET /api/zones/{id}/cycles`, `GET /api/zones/{id}/predictions?task=yield_forecast&from&to` + WS `prediction`, `crop_cycle`):**
  - **Vụ hiện tại** (vụ `status='active'`, tối đa 1 vụ/zone): tên cây (crop profile), ngày bắt đầu, diện tích `area_m2`, tiến độ **"Ngày thứ N / `cycle.days`"** (N = số ngày từ `started_at`, thanh tiến độ; vượt `cycle.days` thì hiện "Đã quá thời gian vụ dự kiến").
  - **Năng suất dự kiến:** lấy bản `yield_forecast` mới nhất → hiển thị `value` (kg/m²) + khoảng `details.interval` (p10–p90), ví dụ *"Năng suất dự kiến 6.2 kg/m² (5.1–7.3)"*, kèm năng suất tương đối (`score` dạng `%` so với năng suất tham chiếu `yield.reference_kg_m2`), sản lượng ước tính cả vụ (`value × area_m2` kg), thời điểm cập nhật và phiên bản mô hình.
  - Cờ độ tin cậy: badge **"Độ tin cậy thấp"** khi `details.low_confidence`; chưa đủ `ai.min_cycle_hours` từ khi bắt đầu vụ → hiện *"Chưa đủ dữ liệu để dự báo"*; không có mô hình active → *"Chưa có mô hình"*.
  - MAY: biểu đồ nhỏ đường năng suất dự kiến theo thời gian trong vụ (từ lịch sử `predictions`).
  - **Nút "Bắt đầu vụ"** (`operator`/`owner`, chỉ hiện khi zone chưa có vụ active): modal chọn crop profile (mặc định profile hiện tại của zone), `started_at` (mặc định hiện tại), `area_m2` (mặc định `zones.area_m2`, MUST > 0) → `POST /api/zones/{id}/cycles`. Ghi chú cho user: bắt đầu vụ sẽ gán crop profile của vụ cho zone và đồng bộ `cfg` xuống gateway. Bắt lỗi `409` (zone đã có vụ active) bằng thông báo tiếng Việt.
  - **Nút "Thu hoạch"** (`operator`/`owner`, khi có vụ active): modal nhập `harvested_at` (mặc định hiện tại) và tổng khối lượng `yield_kg` (kg, ≥ 0; hiển thị ngay quy đổi `kg/m²` = `yield_kg / area_m2`) → `POST /api/cycles/{id}/harvest`. Sau khi thành công hiển thị ghi chú: dữ liệu vụ sẽ được dùng làm mẫu huấn luyện (nếu đủ dữ liệu khí hậu).
  - **Nút "Huỷ vụ"** (phụ, có xác nhận) → `POST /api/cycles/{id}/abandon`.
  - **Lịch sử vụ:** bảng các vụ trước (cây, bắt đầu, thu hoạch, `yield_kg`, kg/m², trạng thái `harvested`/`abandoned`, `notes` – ví dụ lý do không tạo được mẫu do thiếu dữ liệu).
- **Thông tin zone:** cho phép sửa tên, crop profile và diện tích canh tác `area_m2` qua `PUT /api/zones/{id}` (theo quyền của REST API).
- **Khu vực Điều khiển nhanh / Liên kết tới khối Điều khiển của nhà kính.**

### Trang 4: Điều khiển (tích hợp trên `/zones/:id` hoặc `/greenhouses/:id/control`)
- Với 4 actuator (`pump_1`, `pump_2`, `fan`, `mist`) của nhà kính:
  - Hiển thị trạng thái thực tế (`reported.actuators`: Đang BẬT / TẮT).
  - **Công tắc Auto / Manual** (kèm chọn thời hạn manual, ví dụ 15p / 30p / 60p hoặc không giới hạn) → gọi `PUT /api/greenhouses/{id}/modes`.
  - Nút **BẬT** (nhập/chọn `duration_s` bắt buộc) và **TẮT** → gọi `POST /api/greenhouses/{id}/commands` (chỉ mở cho `operator`/`owner`; bắt lỗi `409 gateway_offline` báo rõ *"Gateway đang offline, không thể gửi lệnh"*).
  - Lưu ý hiển thị cảnh báo trực quan quy tắc interlock quạt ↔ máy tạo ẩm.
- Chế độ Auto dùng duy nhất luật hysteresis cố định theo crop profile (không có lựa chọn chiến lược); SHOULD hiển thị tóm tắt ngưỡng đang áp dụng (ẩm đất `min/max`, VPD `low_crit/high_crit`).
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
- Liệt kê 10 profile hệ thống (5 cây × 2 bản `real`/`demo`: `Cà chua bi`, `Dâu tây`, `Xà lách`, `Dưa leo`, `Ớt chuông`) và bản sao riêng của farm (`GET /api/crop-profiles`); hiển thị `crop_code` (chỉ đọc) và nhãn `real`/`demo`.
- Cho phép gán profile cho từng Zone (`PUT /api/zones/{id}`); khi zone đang có vụ active, ghi chú rằng crop profile được đặt theo vụ.
- Form chỉnh sửa đầy đủ các nhóm tham số của `parameters_json` (`schema_version = 2`): VPD `optimal`, `low_crit`, `low_off`, `high_crit`, `leaf_offset_c`; Nhiệt độ tối ưu `temp_c.optimal`; Ánh sáng `light.dli_optimal`; Ẩm đất `min/max`; Bệnh `rh_gt`, `temp_range_c`, `fungal_minutes_alert`; Tưới `max_run_s`, `min_gap_s`, `max_total_s_per_hour`, `soil_settle_s`; Quạt `min_on_s`, `max_on_s`; Tạo ẩm `max_on_s`, `lockout_s`; Rủi ro `vpd_low_duration_min`; Vụ trồng `cycle.days`; Năng suất tham chiếu `yield.reference_kg_m2`; AI `ai.recommend_window_h`, `ai.min_cycle_hours`, `ai.inference_interval_s`, `ai.min_coverage`; `sample_interval_s`; Failsafe `temp_critical_high_c`, `soil_moisture_critical_low_pct`.
- Ghi chú dưới nhóm **Năng suất tham chiếu**: giá trị này dùng để quy đổi năng suất tương đối của mô hình AI ra kg/m² (mô hình toàn cục dùng giá trị tham chiếu lưu trong mô hình lúc huấn luyện).
- Lưu (`PUT /api/crop-profiles/{id}`) → tự động đồng bộ `cfg` xuống gateway (lưu ý giải thích cho user nếu đang sửa template hệ thống sẽ tự tạo bản sao riêng cho farm).

### Trang 7: Cảnh báo (`/alerts`)
- Bộ lọc theo trạng thái (`Đang mở`, `Đã xác nhận`, `Đã giải quyết`, `Tất cả`) → `GET /api/alerts`.
- Thẻ/dòng cảnh báo hiển thị: loại cảnh báo (tiếng Việt dễ hiểu, ví dụ `DISEASE_RISK` → "Nguy cơ nấm bệnh", `HEAT_STRESS` → "Sốc nhiệt", `SOIL_DRY` → "Đất khô", `SENSOR_FAULT` → "Lỗi cảm biến", MAY `YIELD_FORECAST_LOW` → "Năng suất dự kiến thấp"), `severity` (`info`/`warning`/`critical`), zone/nhà kính, thời điểm phát sinh, nội dung chi tiết (`payload`), trạng thái (`raised` / `notified` / `acknowledged` / `resolved`), mốc `escalated_at` nếu đã leo thang.
- Thao tác (cho `operator`/`owner`):
  - Nút **"Xác nhận (Ack)"** (`POST /api/alerts/{id}/ack`).

### Trang 8: Gợi ý cây trồng (`/greenhouses/:id/recommendations`)
- Bộ chọn nhà kính (dropdown các nhà kính của farm, có badge **Mô phỏng**) → `GET /api/greenhouses/{id}/recommendations` (bản `crop_recommendation` mới nhất) + WS `prediction` (`data.task = 'crop_recommendation'`).
- **Tóm tắt khí hậu cửa sổ gần nhất** (từ `details.features`, `details.window_h`, `details.coverage`): nhiệt độ TB (`t_mean`), TB ngày/đêm (`t_day_mean`/`t_night_mean`), RH TB (`rh_mean`), VPD TB (`vpd_mean`), DLI TB (`dli_mean`, hiển thị "Không có dữ liệu ánh sáng" nếu `null`), tỉ lệ thời gian nóng > 30 °C (`frac_t_gt_30`); ghi rõ độ dài cửa sổ (ví dụ "14 ngày gần nhất" hoặc "1 giờ gần nhất – chế độ demo"), độ phủ dữ liệu `coverage` (%) và thời điểm tính.
- **3 thẻ top cây** (`details.ranking[0..2]`): hạng, tên cây (`crop_name`), năng suất tương đối (`relative_yield` dạng `%`), năng suất dự kiến `expected_kg_m2` + khoảng `interval` (p10–p90), tối đa 3 lý do tiếng Việt (`reasons`, ví dụ *"Nhiệt độ TB 31.2 °C cao hơn khoảng tối ưu 18–24 °C"*).
- **Bảng tất cả ứng viên** (toàn bộ `details.ranking`): hạng, cây, năng suất tương đối, kg/m², khoảng tin cậy, lý do; sắp xếp mặc định theo hạng.
- **Nút "Làm mới"** (`operator`/`owner`) → `POST /api/greenhouses/{id}/recommendations/refresh` (`202`) → hiển thị trạng thái "Đang tính lại…" cho tới khi nhận WS `prediction` mới của nhà kính (SHOULD timeout ~60 s rồi refetch REST).
- **Ghi chú độ tin cậy (MUST):** gợi ý giả định tưới đủ (ẩm đất đặt ở trung điểm khoảng tối ưu của từng cây) và chỉ dựa trên khí hậu; khi `low_confidence` hiển thị badge + lý do. Gợi ý **không** gửi lệnh điều khiển nào tới thiết bị.
- Trạng thái trống: chưa có mô hình active → "Chưa có mô hình"; nhà kính chưa đủ dữ liệu → "Chưa đủ dữ liệu khí hậu để gợi ý".

### Trang 9: Mô hình AI (`/models`)
- **Mô hình đang kích hoạt (`GET /api/models/active`):** phiên bản `version`, ngày huấn luyện (`trained_at`), `feature_version`, số mẫu `n_samples`, số nhà kính `n_greenhouses`, cơ cấu nguồn dữ liệu `source_mix` (`synthetic` / `sim` / `real` / `public` – biểu đồ cột hoặc thanh tỉ lệ), danh sách cây `crops` (`crop_code`, số mẫu `n`, `reference_kg_m2`).
- **Chất lượng trên nhà kính chưa từng thấy (tập test, `metrics` vs `baseline_metrics`):** bảng MAE (kg/m²), RMSE, R², MAPE của mô hình so với **B0** (median theo cây) và **B1** (Ridge); tô nổi chỉ số tốt nhất.
- **MAE theo từng cây** và **tách theo `source`** (đặc biệt hiển thị riêng, trung thực kết quả trên mẫu `real` dù số lượng ít, ghi rõ số mẫu).
- **Chất lượng gợi ý:** Top-1 accuracy và NDCG@3 so với xếp hạng oracle (ghi chú: chỉ tính trên dữ liệu `synthetic`).
- **Dấu hiệu lệch dữ liệu (Data Drift):** so sánh mean/std các đặc trưng khí hậu của các dự đoán 7 ngày gần nhất với tập huấn luyện; cảnh báo trực quan (vàng) cho đặc trưng lệch đáng kể.
- MAY: biểu đồ độ quan trọng đặc trưng (feature importance) nếu API trả về.
- **Lịch sử phiên bản (`GET /api/models`, chi tiết `GET /api/models/{id}`):** bảng `version`, `trained_at`, `n_samples`, MAE test, trạng thái **"Đang kích hoạt"** vs không kích hoạt + `notes` (ví dụ lý do không kích hoạt vì không thắng B0/B1/bản đang active).
- Trang chỉ đọc (vai trò `viewer` trở lên); hiển thị số liệu tổng hợp, không bao giờ hiển thị mẫu huấn luyện riêng lẻ.

### Trang 10: Cài đặt Thông báo (`/settings/notifications`)
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
- Chạy trọn 5 kịch bản demo A–E qua giao diện web thật trên HTTPS (`https://localhost` hoặc domain trên VPS). Kịch bản **E. AI** trên web: trang Mô hình AI hiển thị metrics trên nhà kính chưa thấy so với B0/B1; zone có vụ đang trồng hiển thị năng suất dự kiến; trang Gợi ý hiển thị top-3 cho nhà kính thật và các nhà kính giả lập ở vùng khí hậu khác nhau cho gợi ý khác nhau hợp lý; thay đổi khí hậu nhà kính thật rồi bấm **Làm mới** → khí hậu tóm tắt và xếp hạng cập nhật.
