# GreenHub – Hướng dẫn tổng quan cho Coding Assistant

> Tài liệu gốc: [docs/greenhub-spec.md](docs/greenhub-spec.md) và [docs/DECISIONS.md](docs/DECISIONS.md).
> Mỗi tính năng có tài liệu đặc tả siêu chi tiết đặt trực tiếp trong thư mục mã nguồn tương ứng (`FEATURE_*.md`). Khi làm việc ở thư mục nào, **luôn đọc `AGENTS.md` cục bộ và các file `FEATURE_*.md` trong thư mục đó trước khi sửa mã nguồn**.

## 1. Phạm vi hệ thống (Bắt buộc tuân thủ)

- **Trong phạm vi (MUST xây dựng):**
  - 1 nhà kính mini thật: 2 zone, 2 sensor node ESP32, 1 gateway ESP32 + relay 4 kênh (`pump_1`, `pump_2`, `fan`, `mist`) + buzzer.
  - Nhiều farm/nhà kính giả lập qua `tools/simulator` (đi qua đúng luồng HTTP provisioning + MQTT TLS).
  - Backend monolith 2 tiến trình (`api` và `worker`) trên Python 3.12 + FastAPI + PostgreSQL/TimescaleDB + Mosquitto 2.x.
  - Web console React 18 + Vite + TypeScript (PWA + Web Push, giao diện tiếng Việt, responsive laptop & điện thoại).
  - AI/ML 3 tầng (A1 luật chất lượng dữ liệu, A2 học đặc tính zone `pump_response`/`fan_response`/`irrigation_eta`, A3 `risk_forecast` + phản hồi cảnh báo), CLI huấn luyện offline `ml/train.py`, thí nghiệm so sánh `fixed` vs `adaptive`.
  - Triển khai Docker Compose cho laptop (`dev`) và AWS EC2 `t3.small` (`prod`).
- **Ngoài phạm vi (TUYỆT ĐỐI KHÔNG thêm):**
  - Telegram bot, FCM/Firebase, app di động native.
  - LLM, bảng `farm_activities`, học tăng cường (RL), phân loại bệnh từ ảnh, học liên farm.
  - PostgreSQL Row-Level Security (cô lập tenant thực hiện ở tầng ứng dụng theo `farm_id`).
  - OTA firmware, cảm biến CO₂/PAR/MLX90614/DS18B20, rèm cắt nắng, 4G, pin/tấm pin mặt trời.
  - Grafana, các dịch vụ managed của AWS (AWS IoT Core, RDS, Lambda...), kiến trúc microservice tách rời.

## 2. Quy ước kiến trúc & kỹ thuật bất biến

- **Ngôn ngữ:** Identifier, tên bảng, cột DB, endpoint API, MQTT topic, hằng số dùng **tiếng Anh**; giao diện Web và nội dung cảnh báo/thông báo dùng **tiếng Việt**; comment/docstring được phép bằng tiếng Việt.
- **Mức độ ràng buộc:** `MUST` = bắt buộc, `SHOULD` = nên làm, `MAY` = tuỳ chọn.
- **Cấu trúc import Python (`platform/`):** `platform/` **không** phải Python package (`__init__.py` không tồn tại ở gốc `platform/`). Gốc import (`PYTHONPATH`) là `platform/` và `.`, nên import luôn là `from api...`, `from worker...`, `from core...` (xem `pyproject.toml`, `docs/DECISIONS.md`).
- **Ngân sách bộ nhớ trên EC2 `t3.small` (2 GB RAM):** Tiến trình `api` (giới hạn 384 MB) **không được** import `pandas`, `scikit-learn`, `lightgbm` (đã có unit test `test_api_process_does_not_import_heavy_ml_libraries` kiểm tra). Chỉ `worker` và `ml/` nạp các thư viện ML.
- **Giao tiếp `api` ↔ `worker`:** Dùng PostgreSQL `LISTEN/NOTIFY` qua `asyncpg` trên 2 kênh `worker_events` (`api -> worker`) và `ws_events` (`worker -> api`) kèm vòng quét bù 5 giây trong `worker/scheduler.py`. Không thêm Redis.
- **Ngưỡng sinh học & tham số thời gian:** Không hard-code vào code nghiệp vụ; đọc từ `crop_profiles.parameters_json` (có 2 bộ template `real` và `demo` cho mỗi loại cây).
- **Quyết định kỹ thuật mới:** Khi gặp điểm chưa rõ, chọn phương án đơn giản nhất phù hợp spec và ghi 1 dòng theo định dạng `YYYY-MM-DD – [phạm vi] quyết định – lý do` vào [docs/DECISIONS.md](docs/DECISIONS.md).

## 3. Bản đồ tài liệu theo tính năng (Feature Index)

| Tính năng | Thư mục | Tài liệu chi tiết |
|---|---|---|
| Giao thức nhị phân ESP-NOW & tiện ích dùng chung | `firmware/common/` | [FEATURE_ESP_NOW_PROTOCOL.md](firmware/common/FEATURE_ESP_NOW_PROTOCOL.md) |
| Firmware Sensor Node ESP32 (AHT20/SHT30, BH1750, Soil) | `firmware/node/` | [FEATURE_SENSOR_NODE.md](firmware/node/FEATURE_SENSOR_NODE.md) |
| Firmware Gateway ESP32, Relay, An toàn & Failsafe | `firmware/gateway/` | [FEATURE_GATEWAY_AND_FAILSAFE.md](firmware/gateway/FEATURE_GATEWAY_AND_FAILSAFE.md) |
| Crop Profile Templates, Data Model & Security Core | `platform/core/` | [FEATURE_CROP_PROFILES_AND_DATA_MODEL.md](platform/core/FEATURE_CROP_PROFILES_AND_DATA_MODEL.md) |
| Vi khí hậu (VPD, PPFD, DLI) & Chất lượng dữ liệu A1 | `platform/core/` | [FEATURE_MICROCLIMATE_AND_QUALITY.md](platform/core/FEATURE_MICROCLIMATE_AND_QUALITY.md) |
| CSDL PostgreSQL + TimescaleDB & Continuous Aggregates | `platform/migrations/` | [FEATURE_DATABASE_TIMESCALEDB.md](platform/migrations/FEATURE_DATABASE_TIMESCALEDB.md) |
| Xác thực JWT, RBAC & Cô lập đa Tenant | `platform/api/` | [FEATURE_AUTH_RBAC_TENANCY.md](platform/api/FEATURE_AUTH_RBAC_TENANCY.md) |
| Provisioning Gateway, Discovery & Ghép Node | `platform/api/` | [FEATURE_PROVISIONING_AND_PAIRING.md](platform/api/FEATURE_PROVISIONING_AND_PAIRING.md) |
| Realtime WebSocket (`/ws`) | `platform/api/` | [FEATURE_WEBSOCKET_REALTIME.md](platform/api/FEATURE_WEBSOCKET_REALTIME.md) |
| Đặc tả đầy đủ hợp đồng REST API (`/api/*`) | `platform/api/` | [FEATURE_REST_API_CONTRACTS.md](platform/api/FEATURE_REST_API_CONTRACTS.md) |
| Worker Ingestion (Telemetry, Status, Discovery, Event) | `platform/worker/` | [FEATURE_INGESTION_PIPELINE.md](platform/worker/FEATURE_INGESTION_PIPELINE.md) |
| Device Shadow & Đồng bộ cấu hình `cfg` có phiên bản | `platform/worker/` | [FEATURE_DEVICE_SHADOW_CONFIG.md](platform/worker/FEATURE_DEVICE_SHADOW_CONFIG.md) |
| Command Service, ACK, Timeout & Hết hạn Manual | `platform/worker/` | [FEATURE_COMMAND_LIFECYCLE.md](platform/worker/FEATURE_COMMAND_LIFECYCLE.md) |
| Rule & Control Engine (Fixed/Adaptive, Interlock, Risk) | `platform/worker/` | [FEATURE_RULE_CONTROL_ENGINE.md](platform/worker/FEATURE_RULE_CONTROL_ENGINE.md) |
| Alert Service & Notification 4 lớp (WS, Push, Email, Buzzer) | `platform/worker/` | [FEATURE_ALERTS_AND_NOTIFICATIONS.md](platform/worker/FEATURE_ALERTS_AND_NOTIFICATIONS.md) |
| AI Runtime Inference & Scheduler trong Worker | `platform/worker/` | [FEATURE_AI_RUNTIME_INFERENCE.md](platform/worker/FEATURE_AI_RUNTIME_INFERENCE.md) |
| Kiểm thử đơn vị, tích hợp & Tiêu chí Demo (A–E) | `platform/tests/` | [FEATURE_TESTING_AND_ACCEPTANCE.md](platform/tests/FEATURE_TESTING_AND_ACCEPTANCE.md) |
| Pipeline AI/ML (A1/A2/A3) & Thí nghiệm Fixed vs Adaptive | `ml/` | [FEATURE_AI_ML_AND_EXPERIMENTS.md](ml/FEATURE_AI_ML_AND_EXPERIMENTS.md) |
| Web Console React 18 (9 trang & Biểu đồ trực tiếp) | `web/` | [FEATURE_WEB_CONSOLE_UI.md](web/FEATURE_WEB_CONSOLE_UI.md) |
| PWA & Web Push (Service Worker, VAPID, iOS) | `web/` | [FEATURE_PWA_AND_WEB_PUSH.md](web/FEATURE_PWA_AND_WEB_PUSH.md) |
| Simulator TLS, Thử tải & Công cụ Dev (`seed_dev`) | `tools/simulator/` | [FEATURE_SIMULATOR_AND_LOAD_TEST.md](tools/simulator/FEATURE_SIMULATOR_AND_LOAD_TEST.md) |
| MQTT Broker Mosquitto, TLS & Dynamic Security ACL | `deploy/mosquitto/` | [FEATURE_MQTT_BROKER_SECURITY.md](deploy/mosquitto/FEATURE_MQTT_BROKER_SECURITY.md) |
| Triển khai Docker Compose, Caddy, AWS EC2 & Bảo mật | `deploy/` | [FEATURE_DEPLOYMENT_AND_SECURITY.md](deploy/FEATURE_DEPLOYMENT_AND_SECURITY.md) |

## 4. Lệnh kiểm tra nhanh

```powershell
# Python unit tests & lint (từ gốc repo)
.venv\Scripts\pytest.exe -m "not integration"
.venv\Scripts\ruff.exe check .

# Tích hợp đầy đủ (cần Docker Compose đang chạy)
.venv\Scripts\pytest.exe -v -m integration

# Web build & typecheck
npm run build --prefix web
```
