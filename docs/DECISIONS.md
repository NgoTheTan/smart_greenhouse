# DECISIONS

Một dòng cho mỗi quyết định khi spec chưa rõ (spec mục 0). Định dạng: `YYYY-MM-DD – [phạm vi] quyết định – lý do`.

- 2026-11-05 – [repo] Gốc repo `smart_greenhouse/` đóng vai trò thư mục `greenhub/` trong spec mục 14 – tránh lồng thêm một cấp.
- 2026-11-05 – [platform] `platform/` KHÔNG là Python package; `api`, `worker`, `core` là package cấp cao với `platform/` làm gốc import (PYTHONPATH) – tên `platform` trùng module chuẩn của Python.
- 2026-11-05 – [platform] Một Docker image dùng chung cho `api` và `worker` (entrypoint chọn tiến trình); `api` chạy `alembic upgrade head` khi khởi động, `worker` chờ `api` healthy – migration tự động, không chạy song song.
- 2026-11-05 – [platform] Dùng asyncpg cho cả SQLAlchemy async và LISTEN/NOTIFY – một driver duy nhất.
- 2026-11-05 – [platform] Dependency ML runtime (pandas, scikit-learn, LightGBM) nằm trong image platform – worker cần nạp mô hình joblib; `ml/requirements.txt` kế thừa để artifact tương thích phiên bản.
- 2026-11-05 – [broker] Mosquitto có listener 1883 không TLS chỉ trong mạng Docker (worker, api-admin, healthcheck); ra ngoài chỉ publish 8883 TLS. Dev bind thêm 127.0.0.1:1883 để debug – spec 5 chỉ cấm mở 1883 ra ngoài.
- 2026-11-05 – [broker] Entrypoint Mosquitto khởi tạo Dynamic Security (admin `api-admin`) và tạo user `worker` + role `gh/#` ở lần chạy đầu; chứng chỉ được sao chép vào container rồi chown – Mosquitto không đọc được file key 0600 của Caddy. Fallback password/ACL file ở `deploy/mosquitto/acl.fallback`.
- 2026-11-05 – [deploy] Compose không dùng interpolation `${}`; mọi biến lấy từ `../.env` qua `env_file` – chỉ một file `.env` ở gốc repo cho cả Docker và Python cục bộ.
- 2026-11-05 – [deploy] Dev dùng CA tự ký (`deploy/scripts/gen-dev-certs.sh`) để gateway thật trong LAN kiểm tra chứng chỉ bằng `ca.crt`.
- 2026-11-05 – [deploy] Web build trong image Caddy (multi-stage Node → Caddy) – Caddy phục vụ tĩnh + reverse proxy `/api`, `/ws`.
- 2026-11-05 – [web] Recharts v3 (v2 đã ngừng hỗ trợ), vẫn giữ React 18 theo spec.
- 2026-11-05 – [firmware] Hỗ trợ cả AHT20 (env `node`/`node_demo`) và SHT30 (env `node_sht30`, cờ `USE_SHT30`) – điểm mở #1 spec 17.
- 2026-11-05 – [firmware] Gateway dùng partition `min_spiffs.csv` – WiFiManager + TLS cần nhiều flash cho app.
- 2026-11-05 – [platform] Giao tiếp `api` → `worker` dùng PostgreSQL `LISTEN/NOTIFY` trên kênh `worker_events` kèm vòng quét bù 5 giây – phát lệnh `cmd` và cấu hình `cfg` tức thời không cần Redis.
- 2026-11-05 – [platform] Endpoint `POST /api/nodes/{mac}/pair` hỗ trợ cả ghép node đã `discovered` lẫn khởi tạo trực tiếp MAC nhập thủ công – đáp ứng đồng thời tự phát hiện và fallback MVP (điểm mở #4 spec 17).
- 2026-11-05 – [db] Tách migration tạo continuous aggregates (`readings_1m`, `readings_1h`) sang file riêng dùng `autocommit_block()` – TimescaleDB không cho phép tạo continuous aggregate trong transaction block.
- 2026-11-08 – [platform] Alert Service dedupe qua partial unique index `alerts_open_dedupe` và Web Push chạy qua `asyncio.to_thread` – tránh tạo alert mở trùng lặp và tránh block event loop worker.
- 2026-11-08 – [platform] Rule Engine thực thi an toàn thắng thủ công (Kịch bản A) bằng cách phát lệnh `mist off` và khoá `mist_lockout_until` ngay khi quạt tự bật vì rủi ro nấm/nhiệt.
- 2026-11-09 – [platform] WebSocket `/ws` phân phối sự kiện đa tenant qua PostgreSQL `ws_events`, kiểm tra JWT token và cô lập hoàn toàn theo `farm_id`.




