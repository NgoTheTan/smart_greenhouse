# Hướng dẫn Coding Assistant – `firmware/node/`

Thư mục này chứa project PlatformIO cho **Sensor Node ESP32** (2 node thật cho Zone 1 và Zone 2).

- Tài liệu chi tiết: [FEATURE_SENSOR_NODE.md](./FEATURE_SENSOR_NODE.md)
- Giao thức gói tin dùng chung: [../common/FEATURE_ESP_NOW_PROTOCOL.md](../common/FEATURE_ESP_NOW_PROTOCOL.md)
- Bất biến quan trọng:
  - Cảm biến ẩm đất analog **BẮT BUỘC** đọc từ `ADC1` (`GPIO34`), tuyệt đối không dùng `ADC2` vì xung đột Wi-Fi/ESP-NOW.
  - Luôn bật `PIN_SOIL_VCC` (`GPIO25`), chờ ~50 ms, đọc median 5 mẫu ADC, rồi tắt `PIN_SOIL_VCC` ngay để chống điện phân ăn mòn đầu đo.
  - Node phải hỗ trợ cả `AHT20` (mặc định: env `node`, `node_demo`) và `SHT30` (`env:node_sht30` với `-DUSE_SHT30`).
