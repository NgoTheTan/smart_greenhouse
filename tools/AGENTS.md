# Hướng dẫn Coding Assistant – `tools/`

Thư mục này chứa các công cụ dòng lệnh (CLI) phụ trợ cho phát triển, khởi tạo chứng chỉ/khóa và giả lập thiết bị/dữ liệu:

- Thư mục con `tools/simulator/`:
  - [simulator/AGENTS.md](./simulator/AGENTS.md) và [simulator/FEATURE_SIMULATOR_AND_LOAD_TEST.md](./simulator/FEATURE_SIMULATOR_AND_LOAD_TEST.md) — Simulator MQTT TLS (`python -m tools.simulator`, hỗ trợ `--region`, `equipment_level`, tạo vụ/thu hoạch), bộ sinh dữ liệu `synth-yield` (`growth.py`, `crops_growth.json`), động cơ an toàn `GatewaySafetyEngine`, kịch bản demo và thử tải 50–100 gateway lên VPS Linux.
- Các module tiện ích ở gốc `tools/`:
  - `seed_dev.py`: khởi tạo dữ liệu mẫu idempotent cho dev (`owner`/`operator`/`viewer @greenhub.vn`, mật khẩu `greenhub123`; Farm `"Nông trại Demo GreenHub"`; Greenhouse `"Nhà kính Fomex 01"`; 2 zone demo dùng template `schema_version = 2` và `area_m2` ở M4; cấp phát MQTT Dynamic Security + ghi `.dev-gateway.json`).
  - `gen_vapid.py`: sinh cặp khóa EC `SECP256R1` (`VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` dạng base64url) cho `.env`.
  - `gen_dev_certs.py`: công cụ đa nền tảng (thay cho `openssl` bash) sinh CA tự ký và server cert/key trong `deploy/certs/` với SAN `DNS:localhost`, `DNS:mosquitto`, `IP:127.0.0.1` và `[LAN_IP]` tuỳ chọn.
- Bất biến quan trọng:
  - Chạy mọi lệnh từ gốc repo (`PYTHONPATH = platform;.`); trên Windows chạy `aiomqtt` bắt buộc dùng `asyncio.SelectorEventLoop` (đã xử lý trong `seed_dev.py` và `simulator/__main__.py`).
  - `seed_dev.py` tự chuyển `@timescaledb:5432` -> `@127.0.0.1:15432` và `MQTT_HOST=mosquitto` -> `127.0.0.1` khi chạy ngoài Docker (`/.dockerenv` không tồn tại).
  - Tuyệt đối không commit `.dev-gateway.json`, `data/*.csv` hay `deploy/certs/` (kiểm tra `.gitignore`).
