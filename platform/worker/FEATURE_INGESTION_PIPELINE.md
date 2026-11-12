# Feature: Ingestion Pipeline & MQTT Routing (`platform/worker/main.py`, `ingest.py`)

> Nguồn đặc tả: `docs/greenhub-spec.md` mục 3.2, 5, 6.1, 6.2, 8.1, 11; `docs/DECISIONS.md`.

## 1. Mục tiêu & Phạm vi

Tiếp nhận toàn bộ bản tin MQTT chiều **Gateway → Cloud**, kiểm tra hợp lệ bằng Pydantic v2, tính VPD, kiểm tra và gắn nhãn chất lượng dữ liệu theo luật, đối chiếu zone lân cận, lưu vào PostgreSQL/TimescaleDB theo đúng nhãn nguồn (`real`/`sim`), cập nhật trạng thái thiết bị (`gateways`, `device_nodes`, `device_state.reported`, `actuator_logs`), và phát sự kiện realtime lên `ws_events` cũng như kích hoạt Rule Engine & Alert Service.

## 2. Trạng thái hiện thực trong repo

- **Đã hoàn thiện (M2):**
  - `platform/worker/main.py`: `WorkerRuntime` kết nối `aiomqtt` (user `worker`, exponential backoff `1..60s`), subscribe 5 topic pattern (`gh/+/+/telemetry/+`, `gh/+/+/status`, `gh/+/+/event`, `gh/+/+/discovery`, `gh/+/+/ack/+`), lắng nghe `CHANNEL_WORKER` (`worker_events`), chạy `APScheduler` 5 s, gọi `warm_up()` lúc boot và đồng bộ ngay lệnh/cfg còn tồn khi reconnect MQTT.
  - `platform/worker/ingest.py`: `IngestService` đã hiện thực `warm_up(window_size=60)`, `handle_telemetry`, `handle_status`, `handle_discovery`, `handle_event`.
- **Cần nối thêm cho M3 (Rule Engine & Alerts):**
  - Trong `handle_telemetry`: sau khi lưu `Reading` và tính `quality`, cần truyền mẫu + `quality` + `neighbor_suspect` vào **Rule & Control Engine** (`worker/rules.py`) để đánh giá tưới, quạt, máy tạo ẩm, `fungal_minutes`, `SENSOR_FAULT` / `DISEASE_RISK` / `HEAT_STRESS` / `SOIL_DRY`.
  - Trong `handle_status`: khi `payload.online == False` (LWT từ Mosquitto) → gọi `AlertService` tạo alert `DEVICE_OFFLINE` (và cũng nên có watchdog kiểm tra `last_seen` quá `offline_failsafe_after_s` hoặc 3 chu kỳ heartbeat trong scheduler phòng trường hợp mất mạng mà TCP keepalive chưa nổ LWT); khi `payload.online == True` → resolve `DEVICE_OFFLINE`.
  - Trong `handle_event`: khi `payload.type == "failsafe_start"` → tạo alert `FAILSAFE_ACTIVE` (critical); khi `"failsafe_stop"` → resolve `FAILSAFE_ACTIVE`; khi `"sensor_invalid"` → ghi nhận/tạo alert `SENSOR_FAULT` nếu phù hợp.

## 3. Hợp đồng MQTT Subscriptions & Routing (`worker/main.py`)

Worker subscribe với `qos=1`:
1. `gh/+/+/telemetry/+` → `IngestService.handle_telemetry(session, farm_id, gh_id, int(zone_index), payload)`
2. `gh/+/+/status` → `IngestService.handle_status(session, farm_id, gh_id, payload)`
3. `gh/+/+/event` → `IngestService.handle_event(session, farm_id, gh_id, payload)`
4. `gh/+/+/discovery` → `IngestService.handle_discovery(session, farm_id, gh_id, payload)`
5. `gh/+/+/ack/+` → `worker.commands.handle_ack(session, farm_id, gh_id, UUID(cmd_id), payload)`

Hàm `parse_gh_topic(topic)` tách chính xác 2 UUID `farm_id` và `greenhouse_id`; topic không khớp định dạng bị bỏ qua an toàn.

## 4. Chi tiết xử lý từng loại bản tin (`IngestService`)

### 4.1 Warm-up khi khởi động (`warm_up`)
- Truy vấn tất cả `Zone.id`, nạp `window_size = 60` mẫu `Reading` gần nhất (theo thứ tự thời gian tăng dần) cho mỗi zone vào `ZoneQualityTracker.warm_up()` để phát hiện `stuck` (60 chu kỳ cho `soil_raw`, 30 chu kỳ cho `air_t/air_rh`) và `spike` hoạt động ngay cả sau khi container `worker` restart.

### 4.2 `handle_telemetry`
1. Validate JSON theo `TelemetryPayload` (`ts`, `zone >= 1`, `air_t`, `air_rh`, `soil_m`, `soil_raw`, `lux`, `batt`, `rssi`, `flags`, `seq`).
2. Truy vấn `Zone` + `Greenhouse` + `Gateway` + `CropProfile` khớp `(farm_id, greenhouse_id, zone_index)`. Không khớp → log warning và bỏ qua (chống topic giả mạo).
3. Lấy `sample_interval_s` (mặc định `60`) và `vpd.leaf_offset_c` (mặc định `1.0`) từ `CropProfile.parameters_json` (fallback `DEFAULT_DEMO_PARAMS`).
4. Đánh giá chất lượng dữ liệu theo luật qua `self._tracker(zone.id).evaluate(sample, sample_interval_s)` → trả nhãn `quality ∈ {'ok', 'dropout', 'out_of_range', 'spike', 'stuck'}`.
5. Tính VPD (`core.vpd.calc_vpd(air_t, air_rh, leaf_offset_c)` làm tròn 4 chữ số thập phân) nếu `air_t` và `air_rh` không null.
6. Đối chiếu các `Zone` anh em trong cùng nhà kính bằng `is_neighbor_divergent` → đặt cờ `neighbor_suspect` (dùng cảnh báo chẩn đoán và dự phòng cảm biến khí).
7. Xác định `source = "sim"` nếu `gw.is_simulated` là `True`, ngược lại `"real"`.
8. Chèn vào bảng `readings` dùng `pg_insert(Reading).on_conflict_do_nothing(index_elements=["zone_id", "ts"])` để đảm bảo idempotent khi MQTT QoS 1 gửi lại gói trùng timestamp.
9. Cập nhật `gw.last_seen = now`, `gw.online = True`, và cập nhật `last_seen`, `rssi`, `battery_mv` cho `DeviceNode` đang `paired` vào `zone.id`.
10. Gọi `pg_notify(CHANNEL_WS, ...)` phát sự kiện `telemetry` lên WebSocket.

### 4.3 `handle_status`
- Parse `GatewayStatusPayload`:
  - Cập nhật `gw.online = payload.online`.
  - Nếu `payload.online == True`: cập nhật `gw.last_seen`, `gw.fw_version`, `gw.rssi`; cập nhật `DeviceState.reported` (`actuators`, `uptime_s`, `heap`, `queue_len`, `nodes`) và `DeviceState.cfg_version_reported = payload.cfg_version`.
  - Phát WS `device_status`. Nếu `cfg_version_reported` thay đổi → phát thêm WS `config_sync`.
  - **M3 cần nối:** Nếu `payload.online == False` (LWT hoặc gateway ngắt kết nối) → kích hoạt alert `DEVICE_OFFLINE`; khi `online == True` → tự resolve alert `DEVICE_OFFLINE`.

### 4.4 `handle_discovery`
- Validate `DiscoveryPayload`, chuẩn hóa `mac = normalize_mac(payload.mac)`.
- Nếu MAC chưa có trong `device_nodes` → tạo mới với `status="discovered"`, `greenhouse_id=greenhouse_id`, `firmware_version`, `rssi`, `first_seen`, `last_seen`.
- Nếu MAC đã có: chỉ cập nhật `greenhouse_id` nếu đang ở `status == "discovered"` (không ghi đè node đã `paired` sang nơi khác), cập nhật `firmware_version`, `rssi`, `last_seen`.
- Phát WS `device_status` với `event="node_discovered"`.

### 4.5 `handle_event`
- Validate `GatewayEventPayload` (`type ∈ {'boot', 'failsafe_start', 'failsafe_stop', 'actuator_changed', 'sensor_invalid'}`).
- Khi `type == "actuator_changed"` (ví dụ bơm/quạt được bật/tắt cục bộ do failsafe khi mất mạng và được xả bù khi online lại): ghi vào `actuator_logs` với `source = payload.source or "failsafe"`, `duration_s = detail.get("duration_s")`, `reason = f"gateway_event:{detail.get('trigger', payload.type)}"`.
- **M3 cần nối:** `failsafe_start` → mở alert `FAILSAFE_ACTIVE` (severity `critical`), kích hoạt notify; `failsafe_stop` → resolve alert `FAILSAFE_ACTIVE`.

## 5. Kiểm tra & Xác nhận

- `test_m2_end_to_end_pipeline` trong `platform/tests/test_m2_integration.py` đã xác nhận toàn bộ luồng telemetry, luật `out_of_range`, discovery, LWT `online=false`, và `config_sync`.
- Khi nối thêm Rules & Alerts vào `ingest.py`, đảm bảo lỗi phát sinh trong rules/alerts được log và xử lý sạch sẽ, không làm hỏng giao dịch lưu `readings` trừ khi có chủ ý.
