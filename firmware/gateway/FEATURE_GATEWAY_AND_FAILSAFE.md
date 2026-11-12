# Feature: Firmware Gateway ESP32, Cầu nối MQTT TLS, An toàn biên & Failsafe (`firmware/gateway/`)

> Nguồn đặc tả: `docs/greenhub-spec.md` mục 4.1, 4.3, 4.4, 4.5, 5, 12, 13.3, 15, 16 (M1), Phụ lục A; `docs/DECISIONS.md`.

## 1. Mục tiêu & Phạm vi

Gateway ESP32 là nút trung tâm của mỗi nhà kính (`1 gateway = 1 nhà kính`):
1. Nhận cấu hình mạng & MQTT qua Captive Portal (`WiFiManager`) lần đầu và lưu vào NVS.
2. Thu gói tin nhị phân ESP-NOW từ các Sensor Node (và xử lý `HELLO` tìm kênh / `discovery` node lạ).
3. Đồng bộ thời gian NTP, kết nối **MQTT over TLS (:8883)** tới Mosquitto (có LWT, reconnect exponential backoff, hàng đợi RAM khi mất mạng).
4. Thực thi lệnh điều khiển `cmd/{actuator}` trên 4 kênh relay kèm toàn bộ quy tắc an toàn biên (auto-off, clamping, interlock quạt–ẩm, `min_gap`/`max_total` bơm, idempotency, kiểm tra `expires_at`) và gửi `ack/{cmd_id}`.
5. Nhận `cfg` retained, lưu NVS khi `cfg_version` đổi, đẩy `CfgPkt` xuống từng node tương ứng.
6. Tự động kích hoạt **Failsafe cục bộ** và còi báo (`buzzer`) khi mất MQTT kéo dài vượt `offline_failsafe_after_s`.

- **Ngoài phạm vi:** Không xử lý nhiều nhà kính trên 1 gateway; không lưu telemetry ra SD card/flash; không dùng port 1883 plaintext; không đấu tải AC 220V (demo chỉ dùng tải 5V DC).

## 2. Trạng thái hiện thực trong repo

- **Đã có:**
  - `firmware/gateway/platformio.ini`: cấu hình `board_build.partitions = min_spiffs.csv`, thư viện `gh_common`, `PubSubClient@^2.8`, `ArduinoJson@^7.2.1`, `WiFiManager@^2.0.17`, build flags `-DMQTT_MAX_PACKET_SIZE=2048`, `-DMQTT_QUEUE_SIZE=150`, định nghĩa đầy đủ 6 chân GPIO.
  - `firmware/gateway/src/main.cpp`: mới có hàm `initRelaysOff()` ghi `HIGH` trước `pinMode(OUTPUT)` cho 4 relay, tắt buzzer, `WiFi.mode(WIFI_STA)` và `TODO(M1)`.
  - Tham chiếu chuẩn hành vi an toàn biên bằng Python nằm ở `tools/simulator/gateway_client.py` (`GatewaySafetyEngine`) và bộ test `platform/tests/test_gateway_sim_safety.py`. Firmware C++ trên Gateway **MUST** thực thi đúng logic tương đương.
- **Cần hiện thực đầy đủ (M1):**
  - Captive Portal (`WiFiManager`) với custom parameters (`mqtt_host`, `mqtt_port`, `mqtt_user`, `mqtt_password`, `farm_id`, `greenhouse_id`) + lưu NVS + nút/cơ chế reset cấu hình nếu cần.
  - Kết nối Wi-Fi STA (2.4 GHz), NTP (`configTime(0, 0, "pool.ntp.org", "time.google.com")`), `WiFiClientSecure` kiểm tra chứng chỉ TLS (nhúng `ca.crt` cho dev LAN hoặc root CA / `esp_crt_bundle` cho Let's Encrypt trên VPS Linux).
  - MQTT TLS client (`PubSubClient` với `setBufferSize(2048)`, LWT topic `gh/{farm_id}/{gh_id}/status` payload `{"online":false}` QoS 1 retained, subscribe `cmd/#` và `cfg`, reconnect exponential backoff).
  - ESP-NOW handler: nhận `PKT_HELLO` -> trả `PKT_HELLO_ACK{channel}` (và publish `discovery` nếu MAC lạ); nhận `PKT_TELEMETRY` -> kiểm tra MAC đã ghép trong `cfg` -> lọc dải vật lý & khử trùng `seq` -> gửi `PKT_CFG` nếu node cần -> đẩy telemetry vào MQTT/RAM queue.
  - RAM Ring Buffer kích thước `MQTT_QUEUE_SIZE` (150 bản tin, nằm trong khoảng 100–200) lưu telemetry + event khi mất MQTT, xả dần khi kết nối lại.
  - Command & Safety Engine + Local Failsafe + Heartbeat 30 s + Buzzer alert.

## 3. Sơ đồ phần cứng & Chân GPIO (MUST)

| Chức năng | Chân ESP32 | Macro `build_flags` | Mức kích & Mạch tải |
|---|---|---|---|
| Relay IN1 – Bơm Zone 1 (`pump_1`) | `GPIO25` | `PIN_RELAY_PUMP1` | Kích mức **THẤP** (`LOW` = đóng relay, `HIGH` = ngắt). +5V -> COM, NO -> +bơm, -bơm -> GND. Diode `1N4007` song song cuộn bơm (cathode về +). |
| Relay IN2 – Bơm Zone 2 (`pump_2`) | `GPIO26` | `PIN_RELAY_PUMP2` | Kích mức **THẤP**. Diode `1N4007` song song tải. |
| Relay IN3 – Quạt (`fan`) | `GPIO27` | `PIN_RELAY_FAN` | Kích mức **THẤP**. Diode `1N4007` song song tải. |
| Relay IN4 – Máy tạo ẩm (`mist`) | `GPIO33` | `PIN_RELAY_MIST` | Kích mức **THẤP**. Nguồn 5V 3A có tụ `1000 µF` lọc rail 5V. |
| Buzzer báo động tại chỗ | `GPIO23` | `PIN_BUZZER` | Tắt (`LOW`) lúc boot. Kêu ngắt quãng/cảnh báo khi failsafe kích hoạt hoặc mất kết nối cloud kéo dài. |
| LED trạng thái | `GPIO2` | `PIN_LED` | Hiển thị trạng thái Wi-Fi / MQTT / failsafe. |

- **Cấm dùng GPIO `0, 2, 12, 15` cho relay** (chân strapping khi boot gây nháy bơm).
- Khi khởi tạo: gọi `digitalWrite(pin, HIGH)` **trước** `pinMode(pin, OUTPUT)` để mọi relay tắt tuyệt đối ngay khi cấp nguồn.
- Máy tạo ẩm USB 5V: phải dùng loại tự chạy ngay khi cấp điện (không cần bấm nút cơ).

## 4. Provisioning cục bộ & Kết nối Cloud (MUST)

### 4.1 Captive Portal (`WiFiManager`) & NVS (`"gh_gw"`)

1. Lần đầu khởi động (chưa có `ssid`/`mqtt_host`/`mqtt_user` hợp lệ trong NVS), Gateway mở AP (ví dụ `GreenHub-GW-XXXX`) bằng `WiFiManager`.
2. Người dùng cấu hình:
   - Wi-Fi SSID & mật khẩu (chỉ hỗ trợ **2.4 GHz**, không hỗ trợ Wi-Fi có captive portal công cộng hoặc WPA2-Enterprise).
   - `mqtt_host` (tên miền riêng hoặc DuckDNS trên VPS prod, hoặc IP LAN laptop ở dev — theo spec mục 13.3 prod dùng **tên miền**, không dùng IP).
   - `mqtt_port` (mặc định `8883`).
   - `mqtt_user`, `mqtt_password` (lấy từ phản hồi 1 lần của `POST /api/gateways`).
   - `farm_id`, `greenhouse_id` (UUID dạng chuỗi 36 ký tự).
3. Lưu toàn bộ vào NVS. Nếu muốn re-provision, hỗ trợ giữ nút BOOT (`GPIO0`) hoặc timeout captive portal hợp lý khi reset cấu hình.

### 4.2 Chuỗi kết nối Wi-Fi → NTP → MQTT TLS

1. Kết nối Wi-Fi STA. Lấy kênh Wi-Fi hiện tại `WiFi.channel()` để trả lời `PKT_HELLO_ACK`.
2. Khởi tạo ESP-NOW (`esp_now_init`) trên đúng kênh Wi-Fi của router đang kết nối.
3. Đồng bộ NTP qua `configTime(0, 0, "pool.ntp.org", "time.google.com")`. Đợi đồng bộ hợp lệ (`time(nullptr) > 1700000000`) trước khi gán `ts` ISO 8601 UTC (`YYYY-MM-DDTHH:MM:SSZ`) cho telemetry/event/ack.
4. Cấu hình `WiFiClientSecure`:
   - Dev LAN: dùng `setCACert(GH_CA_CERT_PEM)` nhúng từ `deploy/certs/ca.crt`.
   - Prod (VPS Let's Encrypt): dùng Root CA ISRG Root X1 hoặc `esp_crt_bundle_attach` (Arduino-ESP32), kiểm chứng trước bằng `openssl s_client -connect <domain>:8883`.
   - Tuyệt đối không bỏ xác thực chứng chỉ (`setInsecure()`) trong bản chạy thật/prod.
5. Cấu hình MQTT:
   - `PubSubClient::setBufferSize(2048)` (bắt buộc ≥ 1024 vì payload `cfg` có nhiều trường JSON).
   - Connect kèm **LWT**: topic `gh/{farm_id}/{gh_id}/status`, QoS `1`, `retain = true`, payload `{"online":false}`.
   - Khi vừa kết nối thành công:
     - Subscribe `gh/{farm_id}/{gh_id}/cmd/#` (QoS 1).
     - Subscribe `gh/{farm_id}/{gh_id}/cfg` (QoS 1).
     - Publish ngay `status` (QoS 1, `retain = true`).
     - Nếu trước đó đang ở trạng thái failsafe, kết thúc failsafe và đưa bản tin `failsafe_stop` vào queue xả lên cloud.
     - Reset bộ đếm backoff về 1 s.
   - Khi mất kết nối MQTT: reconnect bằng **exponential backoff** (ví dụ `1s -> 2s -> 4s -> ... -> max 60s`) trong `loop()` **không block** vòng đọc nút/hẹn giờ tự tắt relay/failsafe!

## 5. Luồng dữ liệu ESP-NOW ↔ MQTT & Ring Buffer RAM

### 5.1 Nhận `PKT_HELLO` từ Node

- Parse `HelloPkt` (`len == sizeof(HelloPkt)`).
- Gửi ngay `HelloAckPkt{PKT_HELLO_ACK, (uint8_t)WiFi.channel()}` unicast về `mac_src` (đăng ký peer tạm nếu chưa có).
- Kiểm tra `mac_src` có nằm trong danh sách `cfg.nodes[]` đã ghép chưa:
  - Nếu **chưa ghép** (MAC lạ): tạo bản tin `discovery` và publish/enqueue tới `gh/{farm_id}/{gh_id}/discovery`:
    ```json
    {"ts":"2026-10-14T08:00:00Z","mac":"AA:BB:CC:DD:EE:03","fw":"1.0","rssi":-62}
    ```
    (Có thể throttle ~10–30 s/MAC nếu node gửi liên tục, nhưng đảm bảo xuất hiện ngay lần đầu).
  - Nếu **đã ghép**: gửi ngay `CfgPkt` xuống node để node đồng bộ `zone`, `sample_interval_s`, `soil_cal`, `cfg_version`.

### 5.2 Nhận `PKT_TELEMETRY` từ Node

1. Kiểm tra `len == sizeof(TelemetryPkt)`.
2. Tìm `mac_src` trong danh sách `cfg.nodes[]`:
   - Nếu **MAC lạ**: không publish lên `telemetry/#`, thay vào đó publish `discovery` lên `gh/{farm_id}/{gh_id}/discovery`.
   - Nếu **đã ghép**: lấy `zone_index` chuẩn từ `cfg.nodes[]` (ưu tiên cấu hình ở gateway nếu gói node còn `zone == 0`).
3. **Khử trùng `seq`:** Lưu `last_seq` theo từng MAC node; nếu trùng `seq` liên tiếp (node gửi lại hoặc packet lặp) thì bỏ qua.
4. **Kiểm tra dải vật lý & sức khỏe cảm biến cục bộ (cho Failsafe):**
   - `air_t = pkt.air_t_x100 / 100.0f`, `air_rh = pkt.air_rh_x100 / 100.0f`.
   - Ghi nhận trạng thái cập nhật gần nhất của từng zone (`last_seen_ms`, `air_t`, `air_rh`, `soil_pct`, `soil_raw`, `flags`, phát hiện giá trị kẹt/đứt dây để failsafe không hành động sai).
   - Cập nhật `last_seen_s` cho mảng `nodes` trong bản tin `status`.
5. **Đẩy cấu hình `CfgPkt` xuống Node:**
   - Ngay sau khi nhận `TelemetryPkt` (trong cửa sổ 200 ms node đang lắng nghe), gateway gửi `CfgPkt` tương ứng với zone của node (đặc biệt khi `cfg_version` trên node hoặc trạng thái đồng bộ cần cập nhật).
6. **Chuyển đổi JSON & Publish/Queue `telemetry/{zone_index}` (QoS 1, không retain):**
   ```json
   {
     "ts": "2026-10-14T08:00:00Z",
     "zone": 2,
     "air_t": 20.4,
     "air_rh": 93.8,
     "soil_m": 58.2,
     "soil_raw": 1873,
     "lux": 18400,
     "batt": 0,
     "rssi": -58,
     "flags": 0,
     "seq": 1234
   }
   ```
   - Nếu `pkt.lux == GH_LUX_NONE (0xFFFFFFFFu)` thì xuất `"lux": null` trong JSON.
   - `rssi` lấy từ callback `esp_now_recv_info->rx_ctrl->rssi` (ESP-IDF/Arduino-ESP32) nếu có.

### 5.3 Hàng đợi RAM Ring Buffer (`MQTT_QUEUE_SIZE = 150`)

- Khi MQTT chưa kết nối, mọi bản tin `telemetry` và `event` được đưa vào ring buffer trên RAM (100–200 mục; ghi đè mục cũ nhất khi đầy).
- **TUYỆT ĐỐI KHÔNG** ghi telemetry vào NVS/SPIFFS/LittleFS để tránh hỏng flash ESP32.
- Khi MQTT kết nối lại, xả tuần tự từng phần tử trong ring buffer (giới hạn vài bản tin mỗi vòng `loop()` để không làm nghẽn xử lý relay/watchdog).

## 6. Xử lý `cfg` retained & Đồng bộ NVS

- Khi nhận `gh/{farm_id}/{gh_id}/cfg`:
  - Parse JSON theo schema `CfgPayload` (`cfg_version`, `offline_failsafe_after_s`, `nodes[]`, `zones[]`).
  - So sánh `cfg_version` mới với bản đang lưu trong RAM/NVS:
    - **Chỉ ghi vào NVS khi `cfg_version` thay đổi** (tránh mòn flash).
    - Cập nhật bảng ánh xạ `nodes[{mac, zone}]`, thông số từng zone (`pump`, `sample_interval_s`, `soil_cal.{dry_raw, wet_raw}`, `limits.*`, `failsafe.*`) và `offline_failsafe_after_s`.
  - Publish ngay `status` cập nhật `cfg_version` mới để backend đánh dấu `cfg_version_reported` ("đã đồng bộ").

## 7. Xử lý Lệnh & Quy tắc An toàn tại Gateway (MUST)

Khi nhận JSON trên topic `gh/{farm_id}/{gh_id}/cmd/{actuator}`:
```json
{"cmd_id":"6f1c...uuid","actuator":"fan","action":"on","duration_s":120,
 "expires_at":"2026-10-14T08:00:30Z","source":"auto"}
```

Thực hiện tuần tự các kiểm tra sau (tham chiếu chuẩn: `tools/simulator/gateway_client.py`):
1. **Idempotency (`_seen_cmd_ids`):** Lưu vòng đệm ~50 `cmd_id` gần nhất. Nếu `cmd_id` rỗng hoặc đã xử lý trước đó -> **bỏ qua** (không thực thi lại, không gửi ACK trùng).
2. **Kiểm tra hết hạn (`expires_at`):** Nếu NTP hợp lệ và `now_utc >= expires_at` -> không thực thi, gửi ACK:
   - `status = "expired"`, `reason = null`, `applied_at = null`.
3. **Kiểm tra hợp lệ đầu vào:**
   - `actuator ∈ {"pump_1", "pump_2", "fan", "mist"}`, `action ∈ {"on", "off"}`.
   - Nếu `action == "on"` mà thiếu `duration_s` hoặc `duration_s <= 0` -> ACK `status = "rejected"`, `reason = "invalid"`.
4. **Xử lý `action == "off"`:**
   - Tắt relay (`digitalWrite(pin, HIGH)`), xóa hẹn giờ tự tắt; nếu là bơm đang chạy thì ghi nhận `last_pump_end_ms[actuator] = millis()`.
   - ACK `status = "applied"`, `side_effects = []`.
5. **Xử lý `action == "on"` — Interlock Quạt & Máy tạo ẩm:**
   - Nếu `actuator == "mist"` và `fan` đang `"on"` -> **từ chối**, ACK `status = "rejected"`, `reason = "interlock"`.
   - Nếu `actuator == "fan"` và `mist` đang `"on"` -> **tắt `mist` trước** (`digitalWrite(PIN_RELAY_MIST, HIGH)`), xóa deadline của `mist`, thêm `"mist_off"` vào `side_effects`.
6. **Chặn trên `duration_s` & Giới hạn Bơm (`pump_1`, `pump_2`):**
   - Lấy giới hạn từ `cfg.zones[]` khớp với tên bơm (`pump_1` / `pump_2`):
     - `eff_duration = min(req_duration, irrigation_max_run_s)`.
     - **Khoảng nghỉ tối thiểu (`min_gap_s`):** Nếu bơm đang tắt và `now_s - last_pump_end < irrigation_min_gap_s` -> **từ chối**, ACK `status = "rejected"`, `reason = "min_gap"`.
     - **Tổng thời gian trong 1 giờ (`max_total_s_per_hour`):** Duy trì lịch sử các lần bơm trong cửa sổ trượt 3600 s; nếu `used_last_hour + eff_duration > irrigation_max_total_s_per_hour` -> **từ chối**, ACK `status = "rejected"`, `reason = "max_total"`.
   - Với `fan`: `eff_duration = min(req_duration, fan_max_on_s)`.
   - Với `mist`: `eff_duration = min(req_duration, mist_max_on_s)`.
   - *(Lưu ý chuẩn `reason` ACK)*: theo spec mục 5, `reason ∈ null | interlock | min_gap | max_total | max_run | invalid`. (Khi `req_duration > max_run`, chuẩn `GatewaySafetyEngine` thực hiện clamp xuống `max_run` và `applied` — đảm bảo luôn tắt sau `eff_duration`).
7. **Kích relay & Hẹn giờ tự tắt (MUST):**
   - Bật relay (`digitalWrite(pin, LOW)`), đặt `off_deadline_ms[actuator] = millis() + eff_duration * 1000UL`.
   - Trong mỗi vòng `loop()`, **tự động tắt ngay** mọi actuator khi `millis() >= off_deadline_ms` (dùng phép trừ tràn `millis()` an toàn `(long)(now - deadline) >= 0`), kể cả khi đang mất kết nối MQTT!
8. **Publish `ack/{cmd_id}` (QoS 1, không retain):**
   ```json
   {
     "cmd_id": "6f1c...uuid",
     "status": "applied",
     "reason": null,
     "applied_at": "2026-10-14T08:00:02Z",
     "side_effects": ["mist_off"],
     "state": {"pump_1": "off", "pump_2": "off", "fan": "on", "mist": "off"}
   }
   ```

## 8. Heartbeat `status` (30 s) & Failsafe cục bộ (MUST)

### 8.1 Heartbeat `status` (retained)
Publish định kỳ mỗi `30 s` (và ngay khi đổi trạng thái actuator hoặc `cfg_version`):
```json
{
  "online": true,
  "fw": "1.0.0",
  "rssi": -60,
  "uptime_s": 86400,
  "heap": 182000,
  "queue_len": 0,
  "cfg_version": 3,
  "actuators": {"pump_1": "off", "pump_2": "off", "fan": "on", "mist": "off"},
  "nodes": [
    {"mac": "AA:BB:CC:DD:EE:01", "zone": 1, "last_seen_s": 8},
    {"mac": "AA:BB:CC:DD:EE:02", "zone": 2, "last_seen_s": 9}
  ]
}
```

### 8.2 Failsafe cục bộ & Buzzer
- **Điều kiện kích hoạt:**
  1. Mất kết nối MQTT liên tục `> offline_failsafe_after_s` (mặc định **60 s**); **VÀ**
  2. Dữ liệu cảm biến của zone đó **hợp lệ**:
     - Nằm trong dải vật lý (`air_t ∈ [-10, 60]`, `air_rh ∈ [0, 100]`, `soil_pct ∈ [0, 100]`, `soil_raw ∈ [50, 4090]`, `flags` không báo lỗi cảm biến tương ứng).
     - **Đứt dây cảm biến ẩm đất đọc ~0 ADC KHÔNG ĐƯỢC COI LÀ "ĐẤT KHÔ"!** (`soil_raw < 50` hoặc `soil_raw > 4090` hoặc `FLAG_SOIL_ERR` phải chặn failsafe tưới).
     - Được cập nhật trong **3 chu kỳ gần nhất** (`now - last_rx <= 3 * sample_interval_s`).
     - Không bị kẹt (`stuck`) — phát hiện giá trị thô lặp nguyên si qua ngưỡng chu kỳ.
- **Hành động failsafe:**
  - **Đất quá khô:** `soil_pct < soil_moisture_critical_low_pct` → bật bơm của zone đó trong `irrigation_max_run_s` (vẫn bắt buộc tuân thủ `min_gap_s` và `max_total_s_per_hour`).
  - **Nhiệt quá cao:** `air_t > temp_critical_high_c` → ép tắt `mist` (nếu đang bật) và bật `fan` (tuân thủ `fan_max_on_s`) cho tới khi `air_t < temp_critical_high_c - 2.0` (hysteresis 2 °C).
- **Cảnh báo & Event:**
  - Bật **Buzzer (`GPIO23`)** theo mẫu kêu ngắt quãng khi failsafe kích hoạt hoặc mất kết nối cloud kéo dài.
  - Ghi các sự kiện vào RAM ring buffer để gửi lên `gh/{farm_id}/{gh_id}/event` khi có mạng lại:
    - `failsafe_start`: `{"ts":"...","type":"failsafe_start","zone":2,"detail":{"trigger":"soil_low","soil_m":27.0}}`
    - `actuator_changed`: kèm `actuator`, `action`, `source: "failsafe"`, `detail: {"trigger": ..., "duration_s": ...}` (backend `IngestService.handle_event` tự động ghi vào `actuator_logs`!).
    - `failsafe_stop`: khi MQTT kết nối lại hoặc điều kiện failsafe kết thúc.
    - `boot`, `sensor_invalid` khi phát sinh.

## 9. Kiểm tra & Xác nhận (M1 & Kịch bản C)

- `pio run -d firmware/gateway -e gateway` biên dịch thành công (partition `min_spiffs.csv`, không tràn flash/RAM).
- Test bằng `mosquitto_pub`/`mosquitto_sub` (hoặc API):
  - Relay không nháy lúc cấp nguồn/reset.
  - Gửi `cmd/mist` `on` rồi `cmd/fan` `on` → relay `mist` ngắt ngay, `ack` trả `side_effects: ["mist_off"]`.
  - Gửi `cmd/mist` `on` khi `fan` đang `on` → `ack` trả `rejected` (`reason: "interlock"`).
  - Bơm tự tắt đúng `duration_s` và chặn `min_gap_s`, `max_total_s_per_hour`.
  - Ngắt Wi-Fi/router > 60 s: buzzer kêu, failsafe chạy đúng ngưỡng, telemetry + event giữ trong RAM queue và xả bù đầy đủ khi có mạng lại, đồng bộ lại `cfg` retained.
