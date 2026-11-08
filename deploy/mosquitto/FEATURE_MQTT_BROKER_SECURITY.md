# Feature: MQTT Broker Mosquitto, Bảo mật TLS & Dynamic Security ACL (`deploy/mosquitto/`)

> Nguồn đặc tả: `docs/greenhub-spec.md` mục 3.1, 5, 6.1, 6.2, 12, 13.1, 13.3; `docs/DECISIONS.md`.

## 1. Mục tiêu & Phạm vi

Vận hành MQTT Broker **Eclipse Mosquitto 2.0.20** bảo mật cao làm cầu nối hai chiều giữa Gateway ESP32 / Simulator và Backend Worker:
1. Mã hóa đường truyền từ thiết bị ngoài Internet/LAN bằng **MQTT over TLS (:8883)**.
2. Cấm hoàn toàn truy cập ẩn danh (`allow_anonymous false`), cấp credential động theo từng nhà kính qua **Dynamic Security plugin** (`$CONTROL/dynamic-security/v1`).
3. Cô lập chặt quyền publish/subscribe của mỗi gateway trong đúng tiền tố `gh/{farm_id}/{greenhouse_id}/`.
4. Lưu bền vững (`persistence`) retained messages (`status`, `cfg`) và trạng thái Dynamic Security qua các lần khởi động lại container.

- **Ngoài phạm vi:** Không dùng AWS IoT Core hay broker thương mại; không mở cổng `1883` plaintext ra Internet; không bật WebSockets trên Mosquitto (Web Console nhận realtime qua FastAPI `/ws`, không nối trực tiếp MQTT).

## 2. Trạng thái hiện thực trong repo

- **Đã hoàn thiện (M1–M2):**
  - `deploy/mosquitto/mosquitto.conf`: cấu hình hai listener `1883` (internal) và `8883` (TLS), persistence, Dynamic Security plugin, giới hạn inflight/queue/message size.
  - `deploy/mosquitto/docker-entrypoint.sh`: kiểm tra và sao chép cert/key sang `/mosquitto/certs/`, hạ quyền file đúng chuẩn `mosquitto:mosquitto`, khởi tạo `dynamic-security.json` + tạo `worker-role` & user `MQTT_WORKER_USER` ở lần chạy đầu.
  - `deploy/mosquitto/acl.fallback`: file cấu hình ACL dự phòng dạng `password_file`/`acl_file` nếu Dynamic Security gặp sự cố.
  - `platform/api/provisioning.py`: `build_gateway_dynsec_commands` và `provision_gateway_mqtt` cấp phát động user & role cho mỗi gateway từ API và `tools/seed_dev.py`.
- **Cần kiểm chứng vận hành ở M4:**
  - Chạy với chứng chỉ thật Let's Encrypt từ volume `caddy_data` qua `deploy/docker-compose.prod.yml`.
  - Xác nhận TLS handshake từ Gateway ESP32 thật (`WiFiClientSecure` + root CA / bundle) tới `<DOMAIN>:8883` và cron `restart mosquitto` hằng tháng.

## 3. Cấu hình Broker (`deploy/mosquitto/mosquitto.conf`)

| Tham số | Giá trị | Lý do kỹ thuật |
|---|---|---|
| `per_listener_settings` | `false` | Dùng chung một nguồn xác thực/ACL cho cả listener `1883` và `8883`. |
| `allow_anonymous` | `false` | Bắt buộc xác thực username/password ở mọi kết nối. |
| `persistence` | `true` | Lưu retained `cfg`, `status`, session QoS 1 và DB Dynamic Security tại `/mosquitto/data/` (volume `mosquitto_data`), `autosave_interval 60`. |
| `log_dest` | `stdout` | Xuất `error`, `warning`, `notice`, `information` + `connection_messages true` để `docker compose logs mosquitto` theo dõi kết nối thiết bị. |
| `plugin` | `/usr/lib/mosquitto_dynamic_security.so` | Quản lý user/role/ACL qua MQTT topic mà không cần reload/restart broker khi thêm gateway mới. |
| `plugin_opt_config_file` | `/mosquitto/data/dynamic-security.json` | Lưu bền vững tài khoản `api-admin`, `worker` và tất cả gateway trong volume `mosquitto_data`. |
| `listener 1883` | Nội bộ Docker | Cho `worker`, `api` (`api-admin`) và healthcheck `mosquitto_ctrl`. Ở `dev` bind thêm `127.0.0.1:1883`; ở `prod` **không** publish ra host/Security Group. |
| `listener 8883` | TLS `tlsv1.2` | Dùng `/mosquitto/certs/server.crt` và `/mosquitto/certs/server.key`; publish `8883:8883` cho ESP32 Gateway và `tools/simulator`. |
| `max_inflight_messages` | `20` | Giới hạn gói QoS 1 đang bay phù hợp RAM nhỏ của ESP32. |
| `max_queued_messages` | `1000` | Giữ lệnh/gói tin tối đa khi thiết bị tạm rớt mạng. |
| `message_size_limit` | `65536` | Trần 64 KB mỗi gói (đủ lớn cho payload `cfg` > 1 KB). |

## 4. Khởi tạo Runtime & Vòng đời Chứng chỉ (`docker-entrypoint.sh`)

1. **Kiểm tra biến môi trường bắt buộc:** `MQTT_TLS_CERTFILE`, `MQTT_TLS_KEYFILE`, `MQTT_ADMIN_USER`, `MQTT_ADMIN_PASSWORD`, `MQTT_WORKER_USER`, `MQTT_WORKER_PASSWORD`. Nếu thiếu file cert → thoát lỗi ngay và nhắc chạy script tạo cert dev.
2. **Sao chép & Phân quyền Chứng chỉ TLS (quyết định trong `docs/DECISIONS.md`):**
   - File `.key` do Caddy sinh ra trên Docker volume `caddy_data` có quyền `0600` thuộc `root:root`, nên tiến trình `mosquitto` (tự hạ quyền xuống UID `mosquitto`) không đọc trực tiếp được.
   - Entrypoint copy `$MQTT_TLS_CERTFILE` → `/mosquitto/certs/server.crt` (`chmod 644`) và `$MQTT_TLS_KEYFILE` → `/mosquitto/certs/server.key` (`chmod 600`), rồi `chown -R mosquitto:mosquitto /mosquitto/certs /mosquitto/data`.
3. **Khởi tạo Dynamic Security lần đầu (`FIRST_RUN=1` khi chưa có `/mosquitto/data/dynamic-security.json`):**
   - Chạy `mosquitto_ctrl dynsec init "$DYNSEC" "$MQTT_ADMIN_USER" "$MQTT_ADMIN_PASSWORD"` và `chown mosquitto:mosquitto "$DYNSEC"`.
   - Khởi động `mosquitto -c /mosquitto/config/mosquitto.conf` chạy nền (kèm `trap 'kill -TERM $PID' TERM INT`).
   - Đợi listener `127.0.0.1:1883` sẵn sàng qua `ctrl getDefaultACLAccess` (tối đa 30 giây).
   - Tạo role **`worker-role`** với toàn quyền trên tiền tố `gh/#`:
     - `publishClientSend 'gh/#' allow`
     - `publishClientReceive 'gh/#' allow`
     - `subscribePattern 'gh/#' allow`
   - Tạo client `MQTT_WORKER_USER` và gắn `worker-role`.
   - Sau bước này `wait "$PID"` giữ tiến trình chính.
4. **Gia hạn chứng chỉ trên Production (`docker-compose.prod.yml`):**
   - Vì entrypoint thực hiện **sao chép** file cert khi container khởi động, khi Caddy tự động gia hạn chứng chỉ Let's Encrypt (mỗi ~60 ngày), Mosquitto sẽ vẫn giữ bản copy cũ nếu không restart.
   - **Bắt buộc** cài cron hàng tháng (ví dụ ngày 1 hàng tháng lúc 04:00 UTC):
     ```bash
     0 4 1 * * cd /home/ubuntu/greenhub && docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.prod.yml restart mosquitto
     ```

## 5. Phân quyền Dynamic Security & Phương án Dự phòng (`acl.fallback`)

### 5.1 Quyền Gateway qua `$CONTROL/dynamic-security/v1` (`platform/api/provisioning.py`)

Mỗi lần `POST /api/gateways` (hoặc `tools/seed_dev.py`) chạy, `api` kết nối cổng nội bộ `1883` bằng tài khoản `MQTT_ADMIN_USER`, gửi batch lệnh tới `$CONTROL/dynamic-security/v1` và chờ kết quả trên `$CONTROL/dynamic-security/v1/response` (timeout 8 s):

1. `deleteClient` (`gw_{greenhouse_id.hex[:12]}`) & `deleteRole` (`gw-{greenhouse_id}`) — bảo đảm idempotent khi seed/re-provision.
2. `createRole` (`gw-{greenhouse_id}`) với chính xác **10 rule ACL** trên `prefix = gh/{farm_id}/{greenhouse_id}`:
   - **Đọc từ Cloud → Gateway:**
     - `cmd/#`: `subscribePattern` (allow), `publishClientReceive` (allow).
     - `cfg`: `subscribeLiteral` (allow), `subscribePattern` (allow), `publishClientReceive` (allow).
   - **Ghi từ Gateway → Cloud (`publishClientSend` allow):**
     - `{prefix}/telemetry/#`
     - `{prefix}/status`
     - `{prefix}/event`
     - `{prefix}/discovery`
     - `{prefix}/ack/#`
3. `createClient` với `username = gw_{greenhouse_id.hex[:12]}`, `password = secrets.token_urlsafe(20)`, gắn role `gw-{greenhouse_id}`.

> [!IMPORTANT]
> Trong Mosquitto Dynamic Security, mọi topic không được `allow` rõ ràng (bao gồm `gh/{other_farm}/...` hay `gh/{farm}/{other_gh}/...`, hoặc gateway tự publish ngược vào `cmd/` hay `cfg`) đều bị **deny** mặc định. Không được gán gateway client vào role có wildcard `gh/#`.

### 5.2 Fallback thủ công (`deploy/mosquitto/acl.fallback`)

Nếu gặp sự cố nghiêm trọng với `mosquitto_dynamic_security.so`, có thể chuyển nhanh sang xác thực file tĩnh bằng cách sửa khối `plugin` trong `mosquitto.conf` thành `password_file /mosquitto/config/passwd` + `acl_file /mosquitto/config/acl`, tạo mật khẩu qua `mosquitto_passwd -b`, và khai báo `user worker -> topic readwrite gh/#` kèm liệt kê tường minh `topic read`/`topic write` cho từng `gw-<id>` (do mẫu `%u` của Mosquitto ACL không tách được `farm_id` và `greenhouse_id`).

## 6. Đặc tả Giao thức Topic MQTT (`docs/greenhub-spec.md` mục 5)

Tiền tố bắt buộc: **`gh/{farm_id}/{greenhouse_id}/`** (`farm_id`, `greenhouse_id` là UUID chuỗi 36 ký tự). Tất cả topic dùng **QoS 1**; thời gian định dạng ISO 8601 UTC (`2026-10-14T08:00:00Z`).

| Topic hậu tố | Chiều | Retained | Payload & Enum chuẩn |
|---|---|---|---|
| `telemetry/{zone_index}` | Gateway → Cloud | Không | `{"ts","zone","air_t","air_rh","soil_m","soil_raw","lux","batt","rssi","flags","seq"}` (`lux` là `null` khi không có BH1750). |
| `status` | Gateway → Cloud | **Có** (+ **LWT**) | Online: `{"online":true,"fw","rssi","uptime_s","heap","queue_len","cfg_version","actuators":{"pump_1",...},"nodes":[{"mac","zone","last_seen_s"}]}`. LWT khi rớt mạng đột ngột: `{"online":false}`. |
| `event` | Gateway → Cloud | Không | `{"ts","type","zone","detail", ...}`; `type` ∈ `boot \| failsafe_start \| failsafe_stop \| actuator_changed \| sensor_invalid`. Với `actuator_changed`: kèm `actuator`, `action`, `source:"failsafe"`. |
| `discovery` | Gateway → Cloud | Không | `{"ts","mac","fw","rssi"}` (khi gateway bắt được `PKT_HELLO` hoặc telemetry từ MAC chưa có trong `cfg`). |
| `cmd/{actuator}` | Cloud → Gateway | Không | `{"cmd_id":"<uuid>","actuator":"pump_1\|pump_2\|fan\|mist","action":"on\|off","duration_s":120,"expires_at":"<utc>","source":"auto\|manual"}` (`duration_s` bắt buộc khi `action="on"`). |
| `ack/{cmd_id}` | Gateway → Cloud | Không | `{"cmd_id","status":"applied\|rejected\|expired","reason":null\|"interlock"\|"min_gap"\|"max_total"\|"max_run"\|"invalid","applied_at","side_effects":["mist_off"],"state":{...}}`. |
| `cfg` | Cloud → Gateway | **Có** | `{"cfg_version":int,"offline_failsafe_after_s":60,"nodes":[{"mac","zone"}],"zones":[{"zone","pump","sample_interval_s","soil_cal":{"dry_raw","wet_raw"},"limits":{...},"failsafe":{...}}]}`. |

- **Worker Subscriptions (`platform/worker/main.py`):**
  `gh/+/+/telemetry/+`, `gh/+/+/status`, `gh/+/+/event`, `gh/+/+/discovery`, `gh/+/+/ack/+`.

## 7. Healthcheck, Giới hạn Tài nguyên & Kiểm thử

- **Healthcheck container (`deploy/docker-compose.yml`):**
  `mosquitto_ctrl -h 127.0.0.1 -p 1883 -u "$MQTT_ADMIN_USER" -P "$MQTT_ADMIN_PASSWORD" dynsec getDefaultACLAccess >/dev/null 2>&1` (interval 15 s, memory limit **128 MB**).
- **Lệnh kiểm thử & debug:**
  ```powershell
  # 1. Unit & Integration test Dynamic Security ACL + TLS :8883
  .venv\Scripts\pytest.exe platform/tests/test_core_and_api_unit.py -k dynsec
  .venv\Scripts\pytest.exe -v -m integration platform/tests/test_m2_integration.py

  # 2. Kiểm tra TLS handshake & chuỗi chứng chỉ thực tế (dev: localhost:8883; prod: <domain>:8883)
  openssl s_client -connect localhost:8883 -CAfile deploy/certs/ca.crt

  # 3. Nghe toàn bộ topic ở dev qua cổng loopback 127.0.0.1:1883 (dùng user worker trong .env)
  mosquitto_sub -h 127.0.0.1 -p 1883 -u worker -P "<MQTT_WORKER_PASSWORD>" -t "gh/#" -v
  ```
