# Feature: Alert Service & Notification 4 Lớp (`platform/worker/alerts.py`, `notify.py`)

> Nguồn đặc tả: `docs/greenhub-spec.md` mục 6.6, 6.7, 7, 9, 10, 15, 17 (#3); `docs/DECISIONS.md`.

## 1. Mục tiêu & Phạm vi

Quản lý trọn vẹn vòng đời cảnh báo chống trùng lặp (`dedupe`), tự giải quyết theo hysteresis, leo thang cảnh báo nghiêm trọng chưa được xác nhận, và gửi thông báo đa kênh gồm 4 lớp: **In-app WebSocket**, **Web Push (VAPID)**, **Email (SMTP)**, và **Buzzer tại chỗ** (do gateway tự kích hoạt).

- **Ngoài phạm vi:** TUYỆT ĐỐI KHÔNG xây Telegram bot, FCM/Firebase, SMS, hoặc push cho app di động native (spec mục 2.2 & 6.7). Không thu nhận phản hồi đúng/sai của người dùng cho cảnh báo (không có cột `alerts.feedback`/`feedback_at`, không có endpoint feedback).

## 2. Trạng thái hiện thực trong repo

- **Chưa hiện thực (`platform/worker/alerts.py` và `platform/worker/notify.py` hiện mới chỉ có docstring 1 dòng!).**
- **Hạ tầng đã sẵn sàng:**
  - Bảng `alerts` (kèm partial unique index `alerts_open_dedupe` trên `dedupe_key WHERE state <> 'resolved'`), `push_subscriptions`, `notification_prefs` đã có trong DB & `core/models.py`.
  - `pywebpush==2.5.0` và `aiosmtplib==5.1.3` đã cài sẵn trong `platform/requirements.txt`.
  - `Settings` đã có `vapid_public_key`, `vapid_private_key`, `vapid_subject`, `smtp_*`, `alert_email_from`, `alert_cooldown_min = 10`, `escalate_after_min = 5`.
  - Frontend `web/public/sw.js` và `web/src/lib/push.ts` đã viết sẵn khung nhận push.

## 3. Vòng đời Alert & Deduplication (`worker/alerts.py`, MUST)

### 3.1 Máy trạng thái `alerts.state`
`raised` → `notified` → `acknowledged` → `resolved`
(Có thể chuyển trực tiếp sang `resolved` từ bất kỳ trạng thái nào khi điều kiện thực tế hết.)

### 3.2 Quy tắc Dedupe & Cooldown
- **Định dạng `dedupe_key`:** `"{alert_type}:{zone_id}"` (nếu gắn với zone) hoặc `"{alert_type}:{greenhouse_id}"` (cho alert cấp gateway như `DEVICE_OFFLINE`, `FAILSAFE_ACTIVE`).
- **Tạo hoặc cập nhật (`raise_alert`):**
  1. Tìm alert đang mở (`state != 'resolved'`) có `dedupe_key` trùng (nhờ `alerts_open_dedupe` unique index, không bao giờ tồn tại 2 alert mở cùng key; có thể dùng `INSERT ... ON CONFLICT (dedupe_key) WHERE state <> 'resolved' DO NOTHING` hoặc SELECT + xử lý `IntegrityError`).
  2. Nếu **chưa có** alert mở → tạo mới `Alert(..., state='raised', created_at=now)` → gọi Notification Service gửi thông báo lần đầu → nếu gửi ít nhất 1 thông báo/WS thành công, cập nhật `state='notified'`, `notified_at=now`.
  3. Nếu **đã có** alert mở:
     - Cập nhật `payload` với giá trị đo mới nhất.
     - Nếu `state == 'acknowledged'` → không gửi lại spam trừ khi leo thang không áp dụng nữa (đã ack rồi thì không leo thang).
     - Nếu chưa `acknowledged` và `now - notified_at >= timedelta(minutes=Settings.alert_cooldown_min)` (mặc định **10 phút**) → gửi lại thông báo nhắc và cập nhật `notified_at = now`.

### 3.3 Tự động Resolve & Leo thang (`escalate_alerts`)
- **Auto-resolve (`resolve_alert`):**
  - Khi Rule Engine / Ingestion / Inference báo điều kiện đã hết (theo hysteresis): cập nhật `state = 'resolved'`, `resolved_at = now`. Phát WS `alert` để UI cập nhật/đóng badge ngay.
- **Leo thang `critical` (chạy trong scheduler định kỳ, ví dụ mỗi 30 s hoặc trong tick 5 s/60 s):**
  - Tìm các alert có:
    - `severity == 'critical'`
    - `state IN ('raised', 'notified')` (tức **chưa** `acknowledged` và chưa `resolved`)
    - `escalated_at IS NULL`
    - `now - created_at >= timedelta(minutes=escalate_after_min)` (mặc định `Settings.escalate_after_min = 5`; trong cấu hình demo có thể đặt `ESCALATE_AFTER_MIN=2` trong `.env`).
  - Hành động khi leo thang:
    1. Gửi lại **Web Push** tới user đủ điều kiện.
    2. Gửi **Email SMTP** tới các user của farm có `notification_prefs.email_enabled == True`.
    3. Đặt `escalated_at = now`.

### 3.4 Bảng loại Alert chuẩn (7 MUST + 2 MAY)

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

- `YIELD_FORECAST_LOW` chỉ mang tính thông tin: không kích hoạt điều khiển, không leo thang (severity `info`), và SHOULD không phát khi dự báo gắn `low_confidence = true`. Ngưỡng `0.6` SHOULD được đặt thành hằng số cấu hình của `inference.py` (không phải ngưỡng sinh học của crop profile).
- Ví dụ nội dung tiếng Việt: `"Năng suất dự kiến thấp – Luống Xà lách (Zone 1): 1.6 kg/m² (≈ 53% mức tham chiếu)."`

## 4. Dịch vụ Thông báo 4 Lớp (`worker/notify.py`, MUST)

| Lớp | Kênh | Khi nào gửi | Chi tiết cài đặt |
|---|---|---|---|
| **1. In-app** | WebSocket (`CHANNEL_WS`) | Mọi alert mới / cập nhật trạng thái / resolved | `pg_notify(session, CHANNEL_WS, {"farm_id": ..., "type": "alert", "data": ...})` → Web Console hiện toast, chuông, badge số alert chưa xử lý. |
| **2. Web Push** | VAPID + `pywebpush` | Alert mới & nhắc cooldown & leo thang | Chạy `pywebpush.webpush()` là hàm đồng bộ qua **`await asyncio.to_thread(...)`** để không block event loop `worker`! |
| **3. Email** | SMTP (`aiosmtplib`) | Chỉ khi **leo thang `critical`** (`escalated_at`) | Gửi qua `Settings.smtp_host/port/user/password` từ `Settings.alert_email_from`. Nếu `smtp_host` rỗng (dev chưa cấu hình SMTP) thì log warning và bỏ qua êm ái, không làm crash worker. |
| **4. Tại chỗ** | Buzzer GPIO23 | Failsafe / mất mạng | Thực hiện tự động bởi firmware Gateway (không cần cloud gửi lệnh). |

### 4.1 Lọc người nhận theo `notification_prefs` & Mức độ
- `SEVERITY_RANK = {"info": 1, "warning": 2, "critical": 3}`.
- Lấy toàn bộ `User` thuộc `greenhouse.farm_id` join `NotificationPref` (mặc định nếu chưa có dòng pref thì coi `push_enabled=True, email_enabled=True, min_severity="warning"`).
- User chỉ nhận Web Push khi `push_enabled == True` và `SEVERITY_RANK[alert.severity] >= SEVERITY_RANK[pref.min_severity]`.

### 4.2 Định dạng Payload Web Push & Nội dung tiếng Việt (MUST)
- JSON gửi cho `pywebpush`:
  ```json
  {
    "title": "CẢNH BÁO: Nguy cơ nấm bệnh",
    "body": "CẢNH BÁO: Nguy cơ nấm bệnh – Luống Dâu tây (Zone 2): VPD 0.14 kPa, RH 94%. Quạt đã được bật.",
    "tag": "DISEASE_RISK:<zone_id>",
    "severity": "critical",
    "url": "/zones/<zone_id>"
  }
  ```
  - Nếu alert cấp nhà kính (`zone_id is None`), `url` trỏ tới `"/"` hoặc `"/alerts"`.
- **Dọn subscription chết (MUST):**
  - Bắt `WebPushException`: nếu `e.response is not None and e.response.status_code in (404, 410)` → **xóa ngay** bản ghi `PushSubscription` đó khỏi DB!
  - Nếu gửi thành công → cập nhật `sub.last_used_at = now`.

## 5. Kiểm tra & Xác nhận

- Unit tests: dedupe 2 lần cùng `dedupe_key` chỉ tạo 1 bản ghi mở; sau khi `resolve` thì tạo được bản ghi mới; xóa `PushSubscription` khi nhận `WebPushException` 404/410; leo thang gửi email sau `escalate_after_min` khi chưa `acknowledged`; alert `info` (vd `YIELD_FORECAST_LOW`, nếu hiện thực) không bị leo thang.
- Demo Kịch bản A: nhận Web Push trên điện thoại/desktop khi đóng/ẩn tab; bấm vào thông báo mở đúng `/zones/{id}`. Nếu không ack sau `escalate_after_min` (2 phút demo), nhận thêm email cảnh báo.
