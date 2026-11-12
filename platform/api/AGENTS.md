# Hướng dẫn Coding Assistant – `platform/api/`

Thư mục này chứa tiến trình **FastAPI** (`api.main:app`): REST API dưới tiền tố `/api`, WebSocket `/ws`, xác thực JWT, RBAC, provisioning Mosquitto Dynamic Security.

- Tài liệu tính năng chi tiết trong thư mục này:
  - [FEATURE_AUTH_RBAC_TENANCY.md](./FEATURE_AUTH_RBAC_TENANCY.md) — JWT, RBAC (`viewer`/`operator`/`owner`), cô lập đa tenant `farm_id`, `/auth`, `/greenhouses`, `/health`, quy tắc bảo vệ `yield_samples`.
  - [FEATURE_PROVISIONING_AND_PAIRING.md](./FEATURE_PROVISIONING_AND_PAIRING.md) — Provisioning gateway, Mosquitto Dynamic Security ACL, discovery & ghép node, hiệu chuẩn ẩm đất.
  - [FEATURE_WEBSOCKET_REALTIME.md](./FEATURE_WEBSOCKET_REALTIME.md) — `WS /ws?token=`, PostgreSQL `LISTEN ws_events`, 7 loại sự kiện realtime (gồm `prediction` và `crop_cycle`).
  - [FEATURE_REST_API_CONTRACTS.md](./FEATURE_REST_API_CONTRACTS.md) — Toàn bộ hợp đồng REST API (M2 và cập nhật M3–M5: `cycles`, `recommendations`, `models`, `crop-profiles` v2).
- Bất biến quan trọng:
  - **Không bao giờ** import `pandas`, `scikit-learn`, `lightgbm` (hoặc `joblib`) trong `api/` (giữ RAM container `api` dưới 384 MB trên VPS 2 GB RAM).
  - Mọi truy vấn DB **BẮT BUỘC** lọc theo `user.farm_id` (kể cả qua `Greenhouse.farm_id == user.farm_id`). Nếu tài nguyên thuộc farm khác hoặc không tồn tại, trả `404` hoặc `403`. **Tuyệt đối không** có endpoint đọc `yield_samples`; `GET /models*` chỉ trả số liệu tổng hợp.
  - Khi thay đổi cấu hình ảnh hưởng xuống gateway (`pair_node`, `calibration`, `crop_profile`, `update_zone`, `start_cycle`), tăng `cfg_version_desired` và gọi `pg_notify(session, CHANNEL_WORKER, {"type": "cfg_updated", ...})` **trước khi commit**.
  - Khi thu hoạch vụ (`POST /cycles/{id}/harvest`) hoặc làm mới gợi ý (`POST /greenhouses/{id}/recommendations/refresh`), gọi `pg_notify(session, CHANNEL_WORKER, ...)` tương ứng (`cycle_harvested` / `recommend`) **trước khi commit** (hoặc đảm bảo dữ liệu đã commit trước khi worker đọc).
  - Khi tạo lệnh điều khiển thủ công (`POST /greenhouses/{id}/commands`), kiểm tra `gateway.online` (offline → `409 gateway_offline`) và gọi `pg_notify` `command_created` trước commit.
