# Hướng dẫn Coding Assistant – `deploy/`

Thư mục này chứa toàn bộ cấu hình triển khai Docker Compose (`dev` laptop và `prod` AWS EC2 `t3.small`), Reverse Proxy Caddy, Mosquitto TLS, chứng chỉ dev và script sao lưu PostgreSQL.

- Tài liệu tính năng chi tiết:
  - [FEATURE_DEPLOYMENT_AND_SECURITY.md](./FEATURE_DEPLOYMENT_AND_SECURITY.md) — Kiến trúc 5 service `docker-compose*.yml`, Caddy HTTPS/SPA, AWS EC2 `t3.small` & Security Group, `.env`, `backup.sh`, bảo mật toàn hệ thống & an toàn điện 5V.
  - [mosquitto/FEATURE_MQTT_BROKER_SECURITY.md](./mosquitto/FEATURE_MQTT_BROKER_SECURITY.md) — Chi tiết Mosquitto 2.0.20, TLS `:8883`, Dynamic Security ACL và fallback.
- Bất biến quan trọng:
  - **Không** dùng biến nội suy `${VAR}` trong `deploy/docker-compose*.yml`; tất cả lấy qua `env_file: ../.env` từ gốc repo (`docs/DECISIONS.md`).
  - Tổng giới hạn bộ nhớ 5 container là **1.792 MB** (`timescaledb` 640m + `worker` 512m + `api` 384m + `mosquitto` 128m + `caddy` 128m) để vận hành ổn định trên EC2 `t3.small` (2 GB RAM + 2 GB swap bắt buộc).
  - Cấm thêm dịch vụ managed AWS (IoT Core, RDS, Lambda), cấm thêm Redis hay Grafana; chỉ sử dụng nguồn DC **5 V** cho mô hình demo (không đấu tải AC 220 V).
  - Container `api` tự chạy `alembic upgrade head` khi khởi động; `worker` chỉ chạy sau khi `api`, `timescaledb`, `mosquitto` đều `healthy`.
