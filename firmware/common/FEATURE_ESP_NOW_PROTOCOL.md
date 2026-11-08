# Feature: Giao thức nhị phân ESP-NOW & Thư viện dùng chung (`gh_common`)

> Nguồn đặc tả: `docs/greenhub-spec.md` mục 4.2, 4.3, 4.4, 4.5, 8.2, 17; `docs/DECISIONS.md`.

## 1. Mục tiêu & Phạm vi

Cung cấp định nghĩa gói tin nhị phân ESP-NOW và các hàm/hằng số vật lý dùng chung giữa firmware **Sensor Node** (`firmware/node`) và **Gateway** (`firmware/gateway`) để đảm bảo đồng nhất layout bộ nhớ, cờ lỗi cảm biến, hằng số dải vật lý và công thức hiệu chuẩn ẩm đất.

## 2. Trạng thái hiện thực trong repo

- Đã có:
  - `firmware/common/gh_common/library.json` — khai báo thư viện PlatformIO tên `gh_common`.
  - `firmware/common/gh_common/src/gh_packets.h` — định nghĩa đầy đủ `PktType`, `TelemetryFlag`, `TelemetryPkt`, `HelloPkt`, `HelloAckPkt`, `CfgPkt` và `static_assert` giới hạn 250 byte.
  - `firmware/common/gh_common/src/gh_config.h` — hằng số kênh Wi-Fi (`WIFI_CH_MIN=1`, `WIFI_CH_MAX=13`), `SEND_FAIL_RESCAN=5`, `HELLO_UNPAIRED_MS=30000`, `DEFAULT_SAMPLE_INTERVAL_S` (10s cho `DEMO_MODE`, 60s mặc định), dải vật lý (`AIR_T_MIN/MAX`, `AIR_RH_MIN/MAX`), hàm `clampPct` và `soilPct`.
- Chưa có (nếu cần bổ sung cho M1):
  - Hàm helper dùng chung kiểm tra dải vật lý đầy đủ tại gateway (`isValidAirTemp`, `isValidAirRh`, `isValidLux`, `isValidSoilRaw`), hằng số timeout chờ `CfgPkt` (`CFG_RX_WINDOW_MS = 200`), hoặc hằng số `GH_FW_PATCH` nếu muốn ghép chuỗi `fw` dạng `"1.0.0"` trên MQTT `status`.

## 3. Cấu trúc gói tin nhị phân ESP-NOW (MUST)

- Định dạng: nhị phân, **little-endian** (chuẩn Xtensa ESP32), **`__attribute__((packed))`**, kích thước tối đa **250 byte** (giới hạn frame ESP-NOW v1).
- Phải kiểm tra `len == sizeof(<Struct>)` ở bên nhận trước khi `memcpy` để tránh đọc rác bộ nhớ hoặc ép kiểu struct sai phiên bản.

### 3.1 Enum loại gói tin (`PktType : uint8_t`)

| Giá trị | Tên | Chiều truyền | Mục đích |
|---|---|---|---|
| `1` | `PKT_TELEMETRY` | Node → Gateway (unicast) | Gửi mẫu đo cảm biến theo chu kỳ |
| `2` | `PKT_HELLO` | Node → Gateway (broadcast khi quét kênh hoặc unicast/broadcast khi chưa ghép) | Tìm kênh Wi-Fi của gateway & báo danh node mới để discovery |
| `3` | `PKT_HELLO_ACK` | Gateway → Node (unicast tới MAC nguồn của `HELLO`) | Trả về kênh Wi-Fi hiện tại của gateway |
| `4` | `PKT_CFG` | Gateway → Node (unicast ngay sau khi nhận `TelemetryPkt` hoặc `HelloPkt`) | Đồng bộ `zone`, `sample_interval_s`, `soil_dry_raw`, `soil_wet_raw`, `cfg_version` |

### 3.2 Chi tiết từng struct (`gh_packets.h`)

1. **`TelemetryPkt`** (tổng 19 byte):
   - `uint8_t type` — phải là `PKT_TELEMETRY` (`1`).
   - `uint8_t zone` — `zone_index` (`1..N`) nhận từ `CfgPkt`; `0` nếu node chưa ghép.
   - `uint16_t seq` — số thứ tự gói tăng dần mỗi vòng đo của node (dùng để khử trùng ở gateway).
   - `int16_t air_t_x100` — nhiệt độ không khí nhân 100 (`25.43 °C` → `2543`; giá trị âm hỗ trợ tới `-327.68 °C`).
   - `uint16_t air_rh_x100` — độ ẩm tương đối nhân 100 (`85.50 %RH` → `8550`).
   - `uint16_t soil_raw` — giá trị ADC 12-bit thô (`0..4095`) lấy median 5 mẫu.
   - `uint8_t soil_pct` — `%` ẩm đất đã hiệu chuẩn 2 điểm tại node (`0..100`).
   - `uint8_t flags` — bitmask `TelemetryFlag`:
     - `FLAG_AHT_ERR = 1 << 0` (bit 0): lỗi đọc cảm biến nhiệt-ẩm (AHT20/AHT21 hoặc SHT30).
     - `FLAG_SOIL_ERR = 1 << 1` (bit 1): lỗi đọc cảm biến ẩm đất (ví dụ ADC ngoài ngưỡng hợp lệ phần cứng / đứt dây).
     - `FLAG_BH_ERR = 1 << 2` (bit 2): lỗi đọc BH1750 (chỉ áp dụng khi node có lắp BH1750; node 2 không gắn BH1750 không bật bit này mà đặt `lux = 0xFFFFFFFF`).
     - **Quan trọng:** Bitmask này phải giữ khớp 1-1 với `platform/core/quality.py` (`FLAG_AHT_ERR`, `FLAG_SOIL_ERR`, `FLAG_BH_ERR`).
   - `uint32_t lux` — cường độ sáng lux (`0..65535`); giá trị `GH_LUX_NONE` (`0xFFFFFFFFu`) nghĩa là node không có BH1750 (cloud chuyển thành `null`).
   - `uint16_t vbat_mv` — điện áp pin theo mV; đặt `0` khi cấp nguồn USB 5V.
   - `uint8_t fw_major`, `uint8_t fw_minor` — phiên bản firmware node (ví dụ `1`, `0` → `"1.0"`).

2. **`HelloPkt`** (3 byte):
   - `uint8_t type` (`PKT_HELLO = 2`), `uint8_t fw_major`, `uint8_t fw_minor`.

3. **`HelloAckPkt`** (2 byte):
   - `uint8_t type` (`PKT_HELLO_ACK = 3`), `uint8_t channel` (kênh Wi-Fi 1..13 mà gateway đang hoạt động).

4. **`CfgPkt`** (10 byte):
   - `uint8_t type` (`PKT_CFG = 4`).
   - `uint8_t zone` (`zone_index` từ `cfg.nodes[]` ứng với MAC node; `0` nếu chưa ghép).
   - `uint16_t sample_interval_s` (lấy từ `cfg.zones[]` theo zone).
   - `uint16_t soil_dry_raw` (mặc định `2900`).
   - `uint16_t soil_wet_raw` (mặc định `1300`).
   - `uint16_t cfg_version` (phiên bản `cfg` hiện tại ở gateway).

## 4. Hằng số & Hàm tiện ích dùng chung (`gh_config.h`)

- **Quét kênh & báo danh:**
  - `WIFI_CH_MIN = 1`, `WIFI_CH_MAX = 13`.
  - `SEND_FAIL_RESCAN = 5` (số lần gửi ESP-NOW thất bại liên tiếp trước khi node quét lại kênh).
  - `HELLO_UNPAIRED_MS = 30000` (chu kỳ gửi `HELLO` khi node chưa được ghép).
- **Chu kỳ mặc định:**
  - `#ifdef DEMO_MODE`: `DEFAULT_SAMPLE_INTERVAL_S = 10`.
  - Thường: `DEFAULT_SAMPLE_INTERVAL_S = 60`.
- **Dải vật lý hợp lệ (khớp A1 ở backend):**
  - `air_t`: `-10.0 .. 60.0 °C`.
  - `air_rh`: `0.0 .. 100.0 %`.
  - `soil_pct`: `0 .. 100 %`.
  - `lux`: `0 .. 65535` (hoặc `GH_LUX_NONE`).
- **Công thức hiệu chuẩn 2 điểm ẩm đất (`gh::soilPct`):**
  ```cpp
  long pct = ((long)dryRaw - (long)raw) * 100L / ((long)dryRaw - (long)wetRaw);
  return clampPct((int)pct);
  ```
  - Lưu ý với cảm biến ẩm đất điện dung v1.2: giá trị ADC khi khô (`dryRaw`, trong không khí ~2900) **lớn hơn** khi ướt (`wetRaw`, trong đất ẩm ~1300). Công thức hỗ trợ cả trường hợp `dryRaw != wetRaw`, tránh chia cho 0 (`if (dryRaw == wetRaw) return 0;`), và kẹp kết quả vào `[0, 100]`.

## 5. Ràng buộc tích hợp PlatformIO

- Cả `firmware/node/platformio.ini` và `firmware/gateway/platformio.ini` đều khai báo:
  - `lib_extra_dirs = ../common`
  - `lib_deps = gh_common ...`
- Không đặt logic phụ thuộc Arduino `WiFi.h` / `PubSubClient` / sensor libraries vào `gh_common` để tránh kéo theo dependency không cần thiết giữa node và gateway. Giữ `gh_common` thuần C/C++ standard `<stdint.h>` / `<stddef.h>`.

## 6. Kiểm tra & Xác nhận

- Mọi thay đổi trong `firmware/common/` phải build thành công cho cả 4 env:
  - `pio run -d firmware/node -e node`
  - `pio run -d firmware/node -e node_demo`
  - `pio run -d firmware/node -e node_sht30`
  - `pio run -d firmware/gateway -e gateway`
- Kiểm tra kích thước struct: `sizeof(TelemetryPkt) == 19`, `sizeof(HelloPkt) == 3`, `sizeof(HelloAckPkt) == 2`, `sizeof(CfgPkt) == 10` (tất cả `<= 250`).
