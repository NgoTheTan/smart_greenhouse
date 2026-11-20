# Feature: Alert Service & Notification 2 Lớp (`platform/worker/alerts.py`, `notify.py`)

> Nguồn đặc tả: `docs/greenhub-spec.md` mục 6.6, 6.7, 7, 9, 10, 15, 17; `docs/DECISIONS.md`.

## 1. Mục tiêu & Phạm vi

Quản lý trọn vẹn vòng đời cảnh báo chống trùng lặp (`dedupe`), nhắc lại theo cooldown, tự giải quyết theo hysteresis, và phát thông báo theo **2 lớp**: **In-app WebSocket** và **Buzzer tại chỗ** (do gateway tự kích hoạt khi mất kết nối / failsafe).

- **Ngoài phạm vi:** Không dùng Web Push (VAPID / Service Worker), Email leo thang (SMTP), Telegram bot, FCM/Firebase, SMS, hoặc push cho app di động native. Không thu nhận phản hồi đúng/sai của người dùng cho cảnh báo (không có cột `alerts.feedback`/`feedback_at`, không có endpoint feedback).

## 2. Trạng thái hiện thực trong repo

- **Đã hiện thực đầy đủ (`platform/worker/alerts.py` và `platform/worker/notify.py`):**
  - Bảng `alerts` (kèm partial unique index `alerts_open_dedupe` trên `dedupe_key WHERE state <> 'resolved'`).
  - `Settings` giữ `alert_cooldown_min = 10` và `yield_low_threshold = 0.6`.
  - Frontend `web/src/lib/ws.tsx`, `web/src/App.tsx` (`ToastContainer`, `AlertBell`) và `web/src/pages/AlertsPage.tsx` hiển thị và xác nhận cảnh báo theo thời gian thực.

## 3. Vòng đời Alert & Deduplication (`worker/alerts.py`, MUST)

### 3.1 Máy trạng thái `alerts.state`
`raised` → `notified` → `acknowledged` → `resolved`
(Có thể chuyển trực tiếp sang `resolved` từ bất kỳ trạng thái nào khi điều kiện thực tế hết.)

### 3.2 Quy tắc Dedupe & Cooldown
- **Định dạng `dedupe_key`:** `"{alert_type}:{zone_id}"` (nếu gắn với zone) hoặc `"{alert_type}:{greenhouse_id}"` (cho alert cấp gateway như `DEVICE_OFFLINE`, `FAILSAFE_ACTIVE`).
- **Tạo hoặc cập nhật (`raise_alert`):**
  1. Tìm alert đang mở (`state != 'resolved'`) có `dedupe_key` trùng (nhờ `alerts_open_dedupe` unique index, không bao giờ tồn tại 2 alert mở cùng key).
  2. Nếu **chưa có** alert mở → tạo mới `Alert(..., state='raised', created_at=now)` → gọi `send_alert_notifications()` phát sự kiện In-app WS → cập nhật `state='notified'`, `notified_at=now`.
  3. Nếu **đã có** alert mở:
     - Cập nhật `payload` với giá trị đo mới nhất và `severity` nếu thay đổi.
     - Nếu `state == 'acknowledged'` → không gửi lại thông báo nhắc.
     - Nếu chưa `acknowledged` và `now - notified_at >= timedelta(minutes=Settings.alert_cooldown_min)` (mặc định **10 phút**) → gửi lại thông báo nhắc qua WebSocket và cập nhật `notified_at = now`.

### 3.3 Tự động Resolve (`resolve_alert`)
- Khi Rule Engine / Ingestion / Inference báo điều kiện đã hết (theo hysteresis): cập nhật `state = 'resolved'`, `resolved_at = now`. Phát WS `alert` để UI cập nhật/đóng badge ngay.

### 3.4 Bảng loại Alert chuẩn (6 MUST + 2 MAY)

| `alert_type` | Phạm vi `dedupe_key` | `severity` mặc định | Nguồn phát sinh | Điều kiện Resolve |
|---|---|---|---|---|
| `DISEASE_RISK` | `DISEASE_RISK:{zone_id}` | `critical` | `rules.py` | `vpd >= low_off` & `fungal_minutes` hết |
| `HEAT_STRESS` | `HEAT_STRESS:{zone_id}` | `critical` | `rules.py` (`air_t >= temp_crit`) | `air_t <= temp_crit - 2` |
| `SOIL_DRY` | `SOIL_DRY:{zone_id}` | `warning` | `rules.py` (`soil < soil_crit` kéo dài) | `soil >= soil_min` |
| `SENSOR_FAULT` | `SENSOR_FAULT:{zone_id}` | `warning` | `rules.py` / `ingest.py` (`quality != ok`) | Nhận liên tiếp mẫu `quality == 'ok'` |
| `DEVICE_OFFLINE` | `DEVICE_OFFLINE:{gh_id}` | `critical` | `ingest.py` (`status.online=false` / LWT) / watchdog | Nhận `status.online=true` hoặc telemetry mới |
| `FAILSAFE_ACTIVE` | `FAILSAFE_ACTIVE:{gh_id}` | `critical` | `ingest.py` (`event: failsafe_start`) | Nhận `event: failsafe_stop` |
| `MAINTENANCE` *(MAY)* | `MAINTENANCE:{zone_id}` | `info` | kiểm tra chất lượng dữ liệu (luật) nâng cao (RSSI thấp, mất gói, drift cảm biến) | Chỉ số ổn định lại |
| `YIELD_FORECAST_LOW` *(MAY)* | `YIELD_FORECAST_LOW:{zone_id}` | `info` | `inference.py` (`yield_forecast` của vụ `active` có `relative_yield < 0.6`) | Dự báo kế tiếp có `relative_yield >= 0.6`, hoặc vụ chuyển `harvested`/`abandoned` |

- `YIELD_FORECAST_LOW` chỉ mang tính thông tin: không kích hoạt điều khiển, và SHOULD không phát khi dự báo gắn `low_confidence = true`. Ngưỡng `0.6` được đặt thành cấu hình `Settings.yield_low_threshold`.
- Ví dụ nội dung tiếng Việt: `"Nhà kính Demo - Luống Xà lách: Năng suất dự kiến thấp (1.60 kg/m², ≈ 53% mức tham chiếu)."`

## 4. Dịch vụ Thông báo 2 Lớp (`worker/notify.py`, MUST)

| Lớp | Kênh | Khi nào gửi | Chi tiết cài đặt |
|---|---|---|---|
| **1. In-app** | WebSocket (`CHANNEL_WS`) | Mọi alert mới / nhắc cooldown / ack / resolved | `pg_notify(session, CHANNEL_WS, {"farm_id": ..., "type": "alert", "data": {..., "title", "body", "url"}})` → Web Console hiện Toast, chuông, badge số alert chưa xử lý và cập nhật `/alerts`. |
| **2. Tại chỗ** | Buzzer GPIO23 | Failsafe / mất mạng MQTT quá `offline_failsafe_after_s` | Thực hiện tự động bởi firmware Gateway (kêu ngắt quãng 200 ms mỗi 3000 ms, không cần cloud gửi lệnh). |

### 4.1 Định dạng Payload WebSocket & Nội dung tiếng Việt (MUST)
- `data` phát qua `pg_notify(CHANNEL_WS)` gồm đầy đủ metadata alert kèm `title`, `body` tiếng Việt định dạng bởi `get_alert_title()` / `format_alert_body()` và `url`:
  - `/zones/{zone_id}` nếu alert gắn với zone, hoặc `/greenhouses/{greenhouse_id}` cho alert cấp nhà kính.

## 5. Kiểm tra & Xác nhận

- Unit tests (`platform/tests/test_alerts_and_notify.py`): dedupe 2 lần cùng `dedupe_key` chỉ tạo 1 bản ghi mở; cooldown 10 phút nhắc lại khi chưa `acknowledged`; sau khi `acknowledged` không gửi nhắc lại dù quá cooldown; sau khi `resolve` thì tạo được bản ghi mới; `send_alert_notifications` phát đúng payload `ws_events` (có `title`, `body`, `url`, không có `escalated_at`).
- Demo Kịch bản A: khi điều kiện nấm bệnh xảy ra, nhận Toast & badge cảnh báo thời gian thực trên Web Console và bấm mở đúng `/zones/{id}` (hoặc xem tại `/alerts` và xác nhận Ack).
