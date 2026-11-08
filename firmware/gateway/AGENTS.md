# Hướng dẫn Coding Assistant – `firmware/gateway/`

Thư mục này chứa project PlatformIO cho **Gateway ESP32 + Relay 4 kênh + Buzzer**.

- Tài liệu chi tiết: [FEATURE_GATEWAY_AND_FAILSAFE.md](./FEATURE_GATEWAY_AND_FAILSAFE.md)
- Giao thức gói tin dùng chung: [../common/FEATURE_ESP_NOW_PROTOCOL.md](../common/FEATURE_ESP_NOW_PROTOCOL.md)
- Bất biến an toàn phần cứng & biên (TUYỆT ĐỐI KHÔNG VI PHẠM):
  - Relay kích mức thấp (`LOW = đóng`): trong `setup()`, **luôn** gọi `digitalWrite(pin, HIGH)` TRƯỚC `pinMode(pin, OUTPUT)`. Không dùng GPIO `0, 2, 12, 15` cho relay.
  - Quạt (`PIN_RELAY_FAN = 27`) và máy tạo ẩm (`PIN_RELAY_MIST = 33`) **KHÔNG BAO GIỜ** bật đồng thời (interlock).
  - Mọi lệnh `on` phải có bộ hẹn giờ tự tắt cục bộ trên gateway; chặn `duration_s` theo giới hạn trong `cfg`; tôn trọng `min_gap_s` và `max_total_s_per_hour` của bơm.
  - Không ghi log telemetry liên tục vào flash/NVS; dùng ring buffer RAM (100–200 bản tin).
  - `MQTT_MAX_PACKET_SIZE` phải `>= 1024` (đã đặt `2048` trong `platformio.ini`).
