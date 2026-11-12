# Hướng dẫn Coding Assistant – `tools/simulator/`

Thư mục này chứa bộ giả lập thiết bị Gateway + Sensor Node (`python -m tools.simulator`) kết nối trực tiếp qua REST API provisioning và MQTT TLS `:8883` giống hệt phần cứng ESP32 thật, cùng bộ sinh dữ liệu huấn luyện tổng hợp offline (`synth-yield`, `growth.py`, `crops_growth.json`).

- Tài liệu tính năng chi tiết:
  - [FEATURE_SIMULATOR_AND_LOAD_TEST.md](./FEATURE_SIMULATOR_AND_LOAD_TEST.md) — CLI `__main__.py` (bao gồm `--region`, `equipment_level`, tạo vụ/thu hoạch qua REST API), `SimulatedGateway`, `GatewaySafetyEngine` (`gateway_client.py`), 4 kịch bản vật lý, `synth-yield` (`growth.py`, `crops_growth.json`), thử tải 50–100 gateway lên VPS Linux và các script dev trong `tools/`.
  - Tài liệu AI liên quan: [ml/FEATURE_AI_YIELD_AND_RECOMMENDATION.md](../../ml/FEATURE_AI_YIELD_AND_RECOMMENDATION.md).
- Bất biến quan trọng:
  - Simulator trực tuyến bắt buộc đăng ký qua luồng API thật (`POST /auth/login` → `POST /greenhouses` → `POST /gateways` với `is_simulated=true`), trừ trường hợp `--farms 1 --gateways 1` có sẵn `.dev-gateway.json`.
  - Dữ liệu từ gateway giả lập tự động được worker gắn `readings.source = 'sim'` (nhờ `Gateway.is_simulated = True`) và `yield_samples.source = 'sim'` khi thu hoạch vụ qua REST API; các nguồn (`synthetic`, `sim`, `real`, `public`) được tách bạch rõ khi báo cáo AI.
  - `synth-yield` và `growth.py` dùng hàm trích đặc trưng dùng chung `platform/core/climate_features.py` (`feature_version = 1`) và phải tất định theo `--seed`. Tuyệt đối không để `ml/` hay `platform/worker/` import `growth.py` hoặc đọc `crops_growth.json`.
  - `GatewaySafetyEngine` trong `gateway_client.py` là bản tham chiếu chuẩn cho logic an toàn ở `firmware/gateway/` (`platform/tests/test_gateway_sim_safety.py` kiểm thử trực tiếp class này) — mọi chỉnh sửa quy tắc an toàn phải đồng bộ với spec §4.3.
  - Không thêm dependency nặng vào `tools/simulator/requirements.txt` (giữ nhẹ `aiomqtt`, `httpx` để chạy độc lập nhẹ nhàng).
