# Hướng dẫn Coding Assistant – `deploy/mosquitto/`

Thư mục này chứa cấu hình **Eclipse Mosquitto 2.0.20** đóng vai trò MQTT Broker trung tâm giữa Gateway ESP32 / Simulator và Worker Python.

- Tài liệu tính năng chi tiết:
  - [FEATURE_MQTT_BROKER_SECURITY.md](./FEATURE_MQTT_BROKER_SECURITY.md) — `mosquitto.conf`, `docker-entrypoint.sh`, `acl.fallback`, Dynamic Security API (`$CONTROL/dynamic-security/v1`), TLS `:8883` và đặc tả đầy đủ 7 topic MQTT.
- Bất biến quan trọng:
  - `allow_anonymous false` — **tuyệt đối cấm** kết nối ẩn danh.
  - Chỉ publish cổng **`:8883` (TLS 1.2+)** ra ngoài ở production. Cổng `:1883` plaintext chỉ dùng trong mạng Docker nội bộ cho `worker`, `api` (`api-admin`) và container healthcheck (môi trường `dev` chỉ bind `127.0.0.1:1883`).
  - Chứng chỉ Let's Encrypt do Caddy quản lý có quyền `0600` thuộc `root`; `docker-entrypoint.sh` phải sao chép từ `MQTT_TLS_CERTFILE`/`MQTT_TLS_KEYFILE` vào `/mosquitto/certs/` và `chown mosquitto:mosquitto` trước khi khởi động broker. Vì vậy, **cron hàng tháng phải `restart mosquitto`** để nạp chứng chỉ mới sau gia hạn.
  - Quyền ACL cô lập từng gateway vào tiền tố `gh/{farm_id}/{greenhouse_id}/`. Không nới rộng quyền đọc/ghi chéo giữa các gateway.
