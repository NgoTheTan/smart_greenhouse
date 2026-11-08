# Hướng dẫn Coding Assistant – `tools/simulator/`

Thư mục này chứa bộ giả lập thiết bị Gateway + Sensor Node (`python -m tools.simulator`) kết nối trực tiếp qua REST API provisioning và MQTT TLS `:8883` giống hệt phần cứng ESP32 thật.

- Tài liệu tính năng chi tiết:
  - [FEATURE_SIMULATOR_AND_LOAD_TEST.md](./FEATURE_SIMULATOR_AND_LOAD_TEST.md) — CLI `__main__.py`, `SimulatedGateway`, `GatewaySafetyEngine` (`gateway_client.py`), 4 kịch bản vật lý, thử tải 50–100 gateway và các script dev trong `tools/`.
- Bất biến quan trọng:
  - Simulator bắt buộc đăng ký qua luồng API thật (`POST /auth/login` → `POST /greenhouses` → `POST /gateways` với `is_simulated=true`), trừ trường hợp `--farms 1 --gateways 1` có sẵn `.dev-gateway.json`.
  - Dữ liệu từ gateway giả lập tự động được worker gắn `readings.source = 'sim'` (nhờ `Gateway.is_simulated = True`), tách biệt với dữ liệu `real` khi huấn luyện/báo cáo AI.
  - `GatewaySafetyEngine` trong `gateway_client.py` là bản tham chiếu chuẩn cho logic an toàn ở `firmware/gateway/` (`platform/tests/test_gateway_sim_safety.py` kiểm thử trực tiếp class này) — mọi chỉnh sửa quy tắc an toàn phải đồng bộ với spec §4.3.
  - Không thêm dependency nặng vào `tools/simulator/requirements.txt` (chỉ `aiomqtt`, `httpx` để chạy độc lập nhẹ nhàng).
