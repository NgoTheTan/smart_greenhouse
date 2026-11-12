# Hướng dẫn Coding Assistant – `platform/worker/`

Thư mục này chứa tiến trình **Worker** (`python -m worker.main`): nhận MQTT từ Mosquitto, ingestion telemetry/status/discovery/event, Rule & Control Engine, Command Service, Alert Service, Notification Service (Web Push + Email + WS), AI Inference (nạp joblib), và APScheduler.

- Tài liệu tính năng chi tiết trong thư mục này:
  - [FEATURE_INGESTION_PIPELINE.md](./FEATURE_INGESTION_PIPELINE.md) — `main.py`, `ingest.py` (MQTT → kiểm tra chất lượng dữ liệu → VPD → DB → WS).
  - [FEATURE_DEVICE_SHADOW_CONFIG.md](./FEATURE_DEVICE_SHADOW_CONFIG.md) — `shadow.py` (`desired`/`reported`, `cfg` retained có phiên bản).
  - [FEATURE_COMMAND_LIFECYCLE.md](./FEATURE_COMMAND_LIFECYCLE.md) — `commands.py` (phát lệnh, ACK, timeout, hết hạn manual).
  - [FEATURE_RULE_CONTROL_ENGINE.md](./FEATURE_RULE_CONTROL_ENGINE.md) — `rules.py` (tưới hysteresis cố định, quạt nhà kính theo rủi ro, ép tắt mist, `fungal_minutes`, alerts theo luật).
  - [FEATURE_ALERTS_AND_NOTIFICATIONS.md](./FEATURE_ALERTS_AND_NOTIFICATIONS.md) — `alerts.py`, `notify.py` (dedupe, cooldown, resolve, leo thang email, Web Push `pywebpush` trong thread).
  - [FEATURE_AI_RUNTIME_INFERENCE.md](./FEATURE_AI_RUNTIME_INFERENCE.md) — `inference.py`, `scheduler.py` (nạp mô hình `yield` toàn cục, suy luận `yield_forecast` & `crop_recommendation`, xử lý `cycle_harvested` → `yield_samples`, `recommend` & `model_activated` qua NOTIFY).
- Bất biến quan trọng:
  - Trên Windows chạy ngoài Docker, `aiomqtt` bắt buộc `SelectorEventLoop` (đã xử lý trong `worker/main.py`).
  - Rule engine **CHỈ** đánh giá quyết định trên dữ liệu `quality == 'ok'`.
  - Trạng thái ngắn hạn trong RAM (`ZoneQualityTracker`, `fungal_minutes`, bộ đếm `vpd_low_duration`) phải có `warm_up()` từ DB khi worker khởi động lại.
  - Mọi `pg_notify` phát sự kiện lên `ws_events` gọi **trong cùng transaction** trước `session.commit()`.
