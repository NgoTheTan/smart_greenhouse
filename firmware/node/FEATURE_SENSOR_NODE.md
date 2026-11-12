# Feature: Firmware Sensor Node ESP32 (`firmware/node/`)

> Nguồn đặc tả: `docs/greenhub-spec.md` mục 4.1, 4.2, 4.4, 4.5, 16 (M1), 17 (#1), Phụ lục A; `docs/DECISIONS.md`.

## 1. Mục tiêu & Phạm vi

Hiện thực firmware trên **ESP32 DevKit (WROOM-32)** đóng vai trò cảm biến biên cho từng zone (Zone 1 có thêm cảm biến ánh sáng BH1750; Zone 2 không có BH1750). Node truyền dữ liệu nhị phân qua **ESP-NOW** về Gateway, nhận cấu hình từ xa (`CfgPkt`), tự tìm đúng kênh Wi-Fi của Gateway và hỗ trợ chế độ demo lẫn deep sleep.

- **Ngoài phạm vi:** Node không kết nối trực tiếp Wi-Fi router hay MQTT broker, không có OTA, không dùng cảm biến CO₂/PAR/MLX90614/DS18B20, không dùng pin/tấm pin mặt trời trong phạm vi demo (cấp nguồn USB 5V nên `vbat_mv = 0`).

## 2. Trạng thái hiện thực trong repo

- **Đã có (khung khởi tạo):**
  - `firmware/node/platformio.ini` — đã cấu hình đầy đủ 3 môi trường build:
    - `node`: AHT20 + BH1750, chu kỳ 60 s.
    - `node_demo` (mặc định): AHT20 + BH1750, cờ `-DDEMO_MODE`, chu kỳ 10 s.
    - `node_sht30`: SHT30 (`Adafruit SHT31 Library`, cờ `-DUSE_SHT30`) + BH1750 + `-DDEMO_MODE` (giải quyết điểm mở #1 trong `DECISIONS.md`).
  - Các macro chân từ `platformio.ini`: `PIN_I2C_SDA=21`, `PIN_I2C_SCL=22`, `PIN_SOIL_AOUT=34`, `PIN_SOIL_VCC=25`, `PIN_LED=2`.
  - `firmware/node/src/main.cpp` — mới chỉ có khung `setup()`/`loop()` khởi tạo Serial, GPIO25 LOW, `WiFi.mode(WIFI_STA)`, `esp_now_init()` và `TODO(M1)`.
- **Cần hiện thực đầy đủ (M1):**
  - Quét kênh Wi-Fi 1–13 bằng `PKT_HELLO` / `PKT_HELLO_ACK` và lưu kênh + MAC gateway vào NVS (`Preferences`).
  - Gửi `PKT_HELLO` định kỳ 30 s khi chưa được ghép (`zone == 0` hoặc chưa có `CfgPkt`).
  - Driver cảm biến I2C: AHT20 (`0x38`) hoặc SHT30 (`0x44` khi `#ifdef USE_SHT30`), BH1750 (`0x23` tự phát hiện có mặt hay không).
  - Chu trình đo ẩm đất chống điện phân (GPIO25 cấp nguồn ~50 ms -> đọc 5 mẫu ADC1 GPIO34 lấy median -> tắt GPIO25 -> tính `soil_pct` theo hiệu chuẩn 2 điểm).
  - Đóng gói `TelemetryPkt`, gửi ESP-NOW unicast tới MAC gateway, đếm lỗi gửi liên tiếp (`SEND_FAIL_RESCAN = 5`).
  - Cửa sổ nghe ~200 ms sau mỗi lần gửi để nhận `CfgPkt`, kiểm tra `cfg_version` đổi mới ghi NVS (tránh mòn flash).
  - Hỗ trợ `esp_deep_sleep` khi không bật `DEMO_MODE` (SHOULD).

## 3. Sơ đồ phần cứng & Đấu nối chân (MUST)

| Linh kiện | Chân ESP32 | Macro build_flags | Ghi chú kỹ thuật |
|---|---|---|---|
| AHT20/AHT21 (I2C `0x38`) hoặc SHT30 (I2C `0x44`) | `SDA = GPIO21`, `SCL = GPIO22`, `VCC = 3V3` | `PIN_I2C_SDA`, `PIN_I2C_SCL` | Đặt xa miệng phun ẩm để tránh ngưng tụ gây sai số/phục hồi chậm (Phụ lục A). |
| BH1750 (I2C `0x23`, chỉ Node 1) | `SDA = GPIO21`, `SCL = GPIO22`, `VCC = 3V3` | `PIN_I2C_SDA`, `PIN_I2C_SCL` | Tối đa 65.535 lux. Khi khởi tạo kiểm tra `begin()` trên bus I2C: nếu không có thiết bị (Node 2) thì đánh dấu không có BH1750 và gửi `lux = GH_LUX_NONE (0xFFFFFFFF)` (không bật `FLAG_BH_ERR`). Nếu từng phát hiện nhưng đọc lỗi thì bật `FLAG_BH_ERR`. |
| Cảm biến ẩm đất điện dung v1.2 `AOUT` | `GPIO34` | `PIN_SOIL_AOUT` | **MUST dùng ADC1** (`GPIO32..39`). Tuyệt đối không dùng ADC2 vì xung đột Wi-Fi/ESP-NOW. Nên seal mép board cảm biến bằng epoxy/sơn chống nước. |
| Cảm biến ẩm đất `VCC` | `GPIO25` | `PIN_SOIL_VCC` | Chỉ xuất `HIGH` trong lúc đo (~50 ms), xong đặt `LOW` ngay để giảm ăn mòn điện hóa và nhiễu. |
| LED trạng thái | `GPIO2` | `PIN_LED` | Nháy ngắn khi gửi thành công / nháy nhanh khi quét kênh hoặc chưa ghép. |

## 4. Luồng hoạt động & Máy trạng thái (MUST)

### 4.1 Khởi động & Lưu trữ NVS (`Preferences`, namespace `"gh_node"`)

Lưu trong NVS các khóa tối thiểu (chỉ `put*` khi giá trị thực sự thay đổi):
- `gw_mac[6]`: MAC 6 byte của gateway (nhận được khi nhận `PKT_HELLO_ACK`).
- `wifi_ch` (`uint8_t`): kênh Wi-Fi `1..13` đã tìm thấy.
- `zone` (`uint8_t`): `0` = chưa ghép; `1..N` = đã ghép.
- `interval_s` (`uint16_t`): chu kỳ đo, mặc định `gh::DEFAULT_SAMPLE_INTERVAL_S` (`10` cho `DEMO_MODE`, `60` cho thường).
- `dry_raw` (`uint16_t`), `wet_raw` (`uint16_t`): mặc định `2900`, `1300`.
- `cfg_ver` (`uint16_t`): phiên bản cấu hình gần nhất đã lưu.
- `seq` (`uint16_t` hoặc giữ `RTC_DATA_ATTR` nếu dùng deep sleep để không reset về 0 mỗi lần ngủ dậy).

### 4.2 Quét kênh Wi-Fi tìm Gateway (`scanForGateway`)

ESP-NOW chỉ gửi/nhận được khi Node và Gateway ở **cùng kênh Wi-Fi** (kênh router của Gateway).
- **Khi nào chạy:**
  1. Lúc boot nếu NVS chưa có `wifi_ch` hoặc chưa có `gw_mac` hợp lệ (hoặc ở lần đầu đánh thức khi không có RTC state).
  2. Sau `gh::SEND_FAIL_RESCAN` (**5**) lần gửi ESP-NOW thất bại liên tiếp (callback `onDataSent` báo `ESP_NOW_SEND_FAIL`, ví dụ khi router đổi kênh hoặc gateway reboot vào kênh mới).
- **Thuật toán:**
  1. Đảm bảo peer broadcast `FF:FF:FF:FF:FF:FF` đã được đăng ký với `esp_now_add_peer` (kênh `0` = kênh hiện tại).
  2. Lặp `ch` từ `gh::WIFI_CH_MIN` (`1`) tới `gh::WIFI_CH_MAX` (`13`):
     - Đặt `esp_wifi_set_channel(ch, WIFI_SECOND_CHAN_NONE)`.
     - Phát `HelloPkt{PKT_HELLO, GH_FW_MAJOR, GH_FW_MINOR}` tới broadcast MAC.
     - Đợi tối đa ~120–200 ms xem có nhận được `HelloAckPkt` từ gateway không.
  3. Khi nhận `HelloAckPkt` (trong `onDataRecv`):
     - Lưu `channel = ack.channel` (kiểm tra `1..13`) và `mac_addr` nguồn của frame làm `gw_mac`.
     - Chuyển ngay sang `esp_wifi_set_channel(channel, WIFI_SECOND_CHAN_NONE)`, đăng ký peer unicast `gw_mac`, lưu `wifi_ch` + `gw_mac` vào NVS (nếu đổi), dừng quét.
  4. Nếu quét hết 1–13 chưa thấy: nghỉ ngắn (ví dụ 2–5 s) rồi quét lại.

### 4.3 Trạng thái chưa ghép (`zone == 0`)

- Khi chưa nhận được `CfgPkt` có `zone > 0`:
  - Node **MUST** gửi `HelloPkt` (unicast tới `gw_mac` hoặc broadcast) định kỳ mỗi `gh::HELLO_UNPAIRED_MS` (**30.000 ms**).
  - Gateway nhận `HelloPkt` từ MAC lạ sẽ publish `discovery` lên cloud để hiển thị "Phát hiện node lạ" trên Web Console.
  - Nếu gateway đã có MAC của node trong `cfg` (vd đã ghép trước đó bằng MAC thủ công), gateway phản hồi ngay `CfgPkt` trong cửa sổ lắng nghe -> node cập nhật `zone > 0`, `sample_interval_s`, `soil_dry_raw`, `soil_wet_raw`, `cfg_version` vào NVS và chuyển sang vòng đo chính thức.
  - Có thể vẫn gửi `TelemetryPkt` với `zone = 0` hoặc chỉ gửi `HelloPkt` mỗi 30 s; theo spec mục 4.2: *"Hello khi chưa ghép: node gửi HELLO định kỳ (mỗi 30 s) cho tới khi nhận được cfg có MAC của mình."*

### 4.4 Vòng đo Telemetry (MUST, đúng thứ tự 6 bước)

1. **Đo ẩm đất:**
   - `digitalWrite(PIN_SOIL_VCC, HIGH)` → chờ `delay(50)` ms để mạch op-amp trên cảm biến điện dung ổn định.
   - Đọc `analogRead(PIN_SOIL_AOUT)` 5 lần (cách nhau ~2–5 ms), sắp xếp và lấy giá trị **median** (trung vị).
   - `digitalWrite(PIN_SOIL_VCC, LOW)` ngay lập tức.
   - Kiểm tra lỗi phần cứng/đứt dây: nếu `soil_raw <= 10` hoặc `soil_raw >= 4090` (hoặc cấu hình ADC 12-bit bất thường), có thể giữ `soil_raw` thực tế để kiểm tra chất lượng dữ liệu (luật) ở backend cũng bắt `out_of_range` (`50..4090`) và/hoặc bật `FLAG_SOIL_ERR` nếu đứt hoàn toàn (`0` hoặc `4095`). Lưu ý: nếu `FLAG_SOIL_ERR` bật thì backend gắn `dropout`; nếu `soil_raw=0` với `flags=0` thì backend gắn `out_of_range` (test T7); cả hai đều `quality != 'ok'` nên đều chặn tưới sai!
2. **Đọc nhiệt-ẩm & ánh sáng:**
   - Với AHT20 (`!USE_SHT30`): gọi `aht.getEvent(&humidity, &temp)`. Kiểm tra `isnan(temp)` hoặc ngoài `[-40, 85]` → bật `FLAG_AHT_ERR`.
   - Với SHT30 (`#ifdef USE_SHT30`): gọi `sht31.readTemperature()` và `sht31.readHumidity()`. Nếu `isnan(...)` → bật `FLAG_AHT_ERR`.
   - Với BH1750: nếu khi boot phát hiện cảm biến ở `0x23`, đọc `lightMeter.readLightLevel()`. Nếu trả về `< 0` (lỗi thư viện claws/BH1750) thì bật `FLAG_BH_ERR` và đặt `lux = GH_LUX_NONE`; nếu node không lắp BH1750 thì `lux = GH_LUX_NONE` (`0xFFFFFFFF`), không bật `FLAG_BH_ERR`.
3. **Tính toán & đóng gói `TelemetryPkt`:**
   - `soil_pct = gh::soilPct(soil_raw, soil_dry_raw, soil_wet_raw)`.
   - `air_t_x100 = (int16_t)lroundf(air_t * 100.0f)`, `air_rh_x100 = (uint16_t)lroundf(air_rh * 100.0f)`.
   - Tăng `seq` (kiểu `uint16_t`, tự wrap-around).
   - Gửi ESP-NOW unicast tới `gw_mac`. Theo dõi trạng thái gửi qua `esp_now_register_send_cb`: nếu thất bại (`!= ESP_NOW_SEND_SUCCESS`) tăng `send_fail_count`; đạt `SEND_FAIL_RESCAN` (5) -> xóa cờ kênh hợp lệ để quét lại kênh 1–13. Nếu thành công -> reset `send_fail_count = 0`.
4. **Cửa sổ nhận `CfgPkt` (~200 ms, MUST):**
   - Sau khi gửi xong gói `TelemetryPkt` (hoặc `HelloPkt`), Node mở chờ **200 ms** trước khi tắt Wi-Fi/ngủ.
   - Gateway khi nhận `TelemetryPkt` hoặc `HelloPkt` từ node sẽ kiểm tra nếu node có cấu hình (hoặc `cfg_version` mới hơn) và phát ngay `CfgPkt` unicast về node trong khoảng cửa sổ 200 ms này.
   - Node nhận `CfgPkt` (`len == sizeof(CfgPkt)`): cập nhật `zone`, `sample_interval_s`, `soil_dry_raw`, `soil_wet_raw`, `cfg_version`; **chỉ ghi NVS nếu dữ liệu thực sự thay đổi** (tránh mòn flash).
5. **Ngủ / Chờ tới chu kỳ kế:**
   - `DEMO_MODE` (`#ifdef DEMO_MODE`): không deep sleep để phản hồi nhanh (hoặc `delay()`/`millis()` loop), chu kỳ mặc định `10 s` (có thể đổi từ xa qua `CfgPkt.sample_interval_s`).
   - Chế độ thường (`!DEMO_MODE`): **SHOULD** dùng `esp_deep_sleep((uint64_t)sample_interval_s * 1000000ULL)` sau khi đã hoàn tất cửa sổ 200 ms chờ `CfgPkt` và tắt `esp_now_deinit()` / `WiFi.mode(WIFI_OFF)`. Dùng `RTC_DATA_ATTR` để giữ `seq`, `gw_mac`, `wifi_ch`, `cfg_ver`, `zone`, `sample_interval_s`, `soil_dry_raw`, `soil_wet_raw` qua deep sleep mà không cần đọc/ghi NVS liên tục.

## 5. Build, Nạp & Kiểm tra (PlatformIO)

```powershell
# Node 1 & Node 2 demo (AHT20, chu kỳ 10s)
cd firmware/node
pio run -e node_demo
pio run -e node_demo -t upload
pio device monitor -b 115200

# Node dùng SHT30 (nếu mua SHT30 thay AHT20)
pio run -e node_sht30 -t upload

# Node chế độ thường (60s + deep sleep)
pio run -e node -t upload
```

**Tiêu chí xác nhận:**
- Node tìm được kênh Gateway qua `HELLO` / `HELLO_ACK` ngay cả khi router phát ở bất kỳ kênh 1–13 nào.
- Node chưa ghép xuất hiện trên API `GET /api/nodes?status=discovered` trong vòng ≤ 30 s sau khi bật nguồn.
- Sau khi ghép node trên Web/API và cập nhật `soil_dry_raw`/`soil_wet_raw` hoặc `sample_interval_s`, lần gửi tiếp theo Node nhận `CfgPkt` trong cửa sổ 200 ms và áp dụng ngay chu kỳ + hiệu chuẩn mới.
- Tháo cảm biến ẩm đất (`GPIO34` hở hoặc nối GND/3V3) -> backend gắn `quality != 'ok'` (`out_of_range` hoặc `dropout`).
- Đổi kênh Wi-Fi router (hoặc tắt/bật lại gateway ở kênh khác) -> sau 5 lần gửi lỗi, Node tự quét lại kênh và khôi phục truyền mà không cần bấm reset tay.
