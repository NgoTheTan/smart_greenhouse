# Feature: Realtime WebSocket (`/ws`) & Thông điệp sự kiện (`platform/api/`)

> Nguồn đặc tả: `docs/greenhub-spec.md` mục 3.2, 6.1, 6.7, 9, 10, 12; `docs/DECISIONS.md`.

## 1. Mục tiêu & Phạm vi

Cung cấp kênh WebSocket đẩy sự kiện thời gian thực từ `worker` và `api` qua PostgreSQL `LISTEN/NOTIFY` (`ws_events`) tới `api` và phân phối tới đúng các client Web Console đang kết nối thuộc cùng `farm_id`.

- **Ngoài phạm vi:** Không thêm Redis Pub/Sub; không truyền dữ liệu điều khiển ngược từ client lên server qua WebSocket (lệnh điều khiển đi qua REST `POST /api/greenhouses/{id}/commands` để có HTTP validation, RBAC và status code chuẩn).

## 2. Trạng thái hiện thực trong repo

- **Đã hiện thực (`platform/api/ws.py`, `main.py`):**
  - `ConnectionManager`, endpoint `@app.websocket("/ws")` (và `/api/ws`), `listen_loop(database_url, CHANNEL_WS, ...)` trong `lifespan` của `FastAPI`.
  - `worker/ingest.py` phát `telemetry`, `device_status` (kèm `node_discovered`), `config_sync`.
  - `worker/commands.py` phát `command_status`.
  - `worker/alerts.py` & `worker/notify.py` phát `alert`.
- **Cần cập nhật / bổ sung (M5):**
  - `worker/inference.py` phát `prediction` với `task ∈ {"yield_forecast", "crop_recommendation"}`.
  - `api/routers/cycles.py` (và `worker` khi xử lý `cycle_harvested` nếu cập nhật `notes`) phát sự kiện `crop_cycle` khi bắt đầu / thu hoạch / huỷ vụ.

## 3. Hợp đồng kỹ thuật `WS /ws?token=` (MUST)

### 3.1 Kết nối & Xác thực
- **URL:** `ws(s)://<host>/ws?token=<JWT_ACCESS_TOKEN>` (qua Caddy HTTPS sẽ là `wss://<domain>/ws?token=...`).
- **Quy trình handshake:**
  1. Đọc query param `token` (trước hoặc ngay khi accept). Nếu thiếu hoặc `decode_access_token(token)` lỗi (hết hạn/chữ ký sai) hoặc không tìm thấy `User` trong DB → đóng kết nối với mã `1008` (Policy Violation).
  2. Lấy `farm_id = str(user.farm_id)` (lưu ý mọi role `viewer`, `operator`, `owner` đều được phép xem realtime của farm mình).
  3. Đăng ký `WebSocket` vào nhóm kết nối theo `farm_id` (`dict[str, set[WebSocket]]`, bảo vệ bằng `asyncio.Lock`).
  4. Duy trì vòng nhận keepalive `ping`/`pong` (mỗi 25–30 s để Caddy/proxy không timeout kết nối rảnh); khi `WebSocketDisconnect` hoặc lỗi gửi → gỡ kết nối khỏi set.

### 3.2 Fan-out theo `farm_id` từ PostgreSQL `CHANNEL_WS = "ws_events"`
- Cấu trúc message trên kênh PostgreSQL `ws_events` (gửi qua `pg_notify`):
  ```json
  {
    "farm_id": "<uuid-string>",
    "type": "telemetry | alert | command_status | device_status | prediction | crop_cycle | config_sync",
    "data": { ... }
  }
  ```
- `api` khi nhận sự kiện từ `listen_loop`:
  - Lọc chính xác `farm_id = event.get("farm_id")`.
  - **Chỉ** gửi khung JSON `{"type": event["type"], "data": event["data"]}` (spec mục 9) tới các kết nối đang mở thuộc `farm_id` đó! Không làm rò rỉ dữ liệu farm A sang farm B.
  - Nếu 1 socket bị gãy khi `send_json`, bắt ngoại lệ, loại socket đó ra khỏi pool mà không làm sập `listen_loop` hoặc ảnh hưởng tới các client khác.

### 3.3 Đặc tả 7 loại thông điệp `{type, data}` (MUST)

1. **`telemetry`** (phát từ `worker/ingest.py`):
   ```json
   {
     "type": "telemetry",
     "data": {
       "greenhouse_id": "<uuid>",
       "zone_id": "<uuid>",
       "zone_index": 1,
       "ts": "2026-10-14T08:00:00+00:00",
       "air_temp": 20.4,
       "air_rh": 93.8,
       "vpd": 0.14,
       "soil_moisture": 58.2,
       "soil_raw": 1873,
       "lux": 18400.0,
       "quality": "ok",
       "neighbor_suspect": false
     }
   }
   ```

2. **`device_status`** (phát từ `worker/ingest.py` khi nhận `status` hoặc `discovery`):
   - Heartbeat/LWT gateway:
     ```json
     {
       "type": "device_status",
       "data": {
         "greenhouse_id": "<uuid>",
         "online": true,
         "rssi": -60,
         "cfg_version_reported": 3,
         "cfg_version_desired": 3,
         "actuators": {"pump_1": "off", "pump_2": "off", "fan": "on", "mist": "off"}
       }
     }
     ```
   - Phát hiện node mới (`event: "node_discovered"`):
     ```json
     {
       "type": "device_status",
       "data": {
         "event": "node_discovered",
         "greenhouse_id": "<uuid>",
         "mac": "AA:BB:CC:DD:EE:03",
         "status": "discovered",
         "rssi": -62
       }
     }
     ```

3. **`config_sync`** (phát từ `worker/ingest.py` khi `cfg_version_reported` đổi):
   ```json
   {
     "type": "config_sync",
     "data": {
       "greenhouse_id": "<uuid>",
       "cfg_version_desired": 3,
       "cfg_version_reported": 3,
       "synced": true
     }
   }
   ```

4. **`command_status`** (phát từ `worker/commands.py` khi gửi, nhận ACK, hết hạn/timeout):
   ```json
   {
     "type": "command_status",
     "data": {
       "cmd_id": "<uuid>",
       "greenhouse_id": "<uuid>",
       "actuator": "fan",
       "action": "on",
       "status": "applied",
       "reason": null,
       "side_effects": ["mist_off"],
       "state": {"pump_1": "off", "pump_2": "off", "fan": "on", "mist": "off"}
     }
   }
   ```

5. **`alert`** (phát từ `worker/alerts.py` & `worker/notify.py` — in-app layer 1):
   ```json
   {
     "type": "alert",
     "data": {
       "id": "<uuid>",
       "greenhouse_id": "<uuid>",
       "zone_id": "<uuid|null>",
       "alert_type": "DISEASE_RISK",
       "severity": "critical",
       "state": "notified",
       "dedupe_key": "DISEASE_RISK:<zone_id>",
       "payload": {"title": "...", "body": "...", "vpd": 0.14, "air_rh": 94.0},
       "created_at": "2026-10-14T08:00:00Z"
     }
   }
   ```

6. **`prediction`** (phát từ `worker/inference.py` theo chu kỳ `ai.inference_interval_s` hoặc khi làm mới gợi ý `recommend`):
   - **Dự báo năng suất (`data.task == "yield_forecast"`):**
     ```json
     {
       "type": "prediction",
       "data": {
         "id": "<uuid>",
         "ts": "2026-11-12T08:00:00Z",
         "task": "yield_forecast",
         "greenhouse_id": "<uuid>",
         "zone_id": "<uuid>",
         "crop_cycle_id": "<uuid>",
         "model_id": "<uuid>",
         "value": 2.76,
         "score": 0.92,
         "details": {
           "crop_code": "lettuce",
           "interval": [2.25, 3.27],
           "coverage": 0.96,
           "low_confidence": false
         }
       }
     }
     ```
   - **Gợi ý cây trồng (`data.task == "crop_recommendation"`):**
     ```json
     {
       "type": "prediction",
       "data": {
         "id": "<uuid>",
         "ts": "2026-11-12T08:00:00Z",
         "task": "crop_recommendation",
         "greenhouse_id": "<uuid>",
         "zone_id": null,
         "crop_cycle_id": null,
         "model_id": "<uuid>",
         "value": null,
         "score": 0.94,
         "details": {
           "window_h": 336,
           "coverage": 0.98,
           "low_confidence": false,
           "ranking": [
             {
               "crop_code": "strawberry",
               "crop_name": "Dâu tây",
               "relative_yield": 0.94,
               "expected_kg_m2": 3.76,
               "interval": [3.16, 4.36],
               "reasons": ["Nhiệt độ TB 19.8 °C nằm trong khoảng tối ưu 18–24 °C"]
             }
           ]
         }
       }
     }
     ```

7. **`crop_cycle`** (phát từ `api/routers/cycles.py` khi bắt đầu / thu hoạch / huỷ vụ, và tuỳ chọn từ `worker` sau khi tạo `yield_samples`):
   ```json
   {
     "type": "crop_cycle",
     "data": {
       "event": "started | harvested | abandoned",
       "cycle_id": "<uuid>",
       "greenhouse_id": "<uuid>",
       "zone_id": "<uuid>",
       "crop_profile_id": "<uuid>",
       "crop_code": "lettuce",
       "status": "active",
       "started_at": "2026-11-12T08:00:00Z",
       "harvested_at": null,
       "area_m2": 0.5,
       "yield_kg": null
     }
   }
   ```

## 4. Lưu ý tích hợp Proxy & Test

- **Caddy (`deploy/caddy/Caddyfile`):** đã cấu hình `handle /ws* { reverse_proxy api:8000 }`. Container `api` chạy 1 worker process `uvicorn` nên toàn bộ socket của client kết nối vào cùng 1 instance `ConnectionManager` (khớp kiến trúc monolith).
- **Giới hạn PG NOTIFY payload:** PostgreSQL `pg_notify` giới hạn 8000 bytes/payload; giữ `data` trong `prediction` và `crop_cycle` gọn nhẹ (với `crop_recommendation`, chỉ nhúng tóm tắt top-3 trong WS hoặc để Web Console tự refetch `GET /api/greenhouses/{id}/recommendations` khi nhận sự kiện).
- **Kiểm thử:**
  - Unit test: token sai/thiếu bị từ chối (`1008`); fan-out chỉ gửi tới socket cùng `farm_id` và không gửi chéo farm.
  - Integration test: khi `SimulatedGateway` publish telemetry hoặc ACK lệnh, client mở `WS /ws?token=...` nhận ngay bản tin tương ứng trong < 1 s.
