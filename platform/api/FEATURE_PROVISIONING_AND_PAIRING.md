# Feature: Provisioning Gateway, Mosquitto Dynamic Security & Ghép Node (`platform/api/`)

> Nguồn đặc tả: `docs/greenhub-spec.md` mục 1, 5, 6.2, 9, 11, 16 (M4), 17 (#4); `docs/DECISIONS.md`.

## 1. Mục tiêu & Phạm vi

Quản lý trọn vẹn vòng đời cấp phát và kết nối thiết bị cho cả thiết bị thật (ESP32) và giả lập (`tools/simulator`):
1. Cấp phát Gateway gắn với 1 nhà kính (`1-1`), sinh credential MQTT riêng và tự động khóa ACL theo `farm_id`/`greenhouse_id` qua Mosquitto Dynamic Security.
2. Tiếp nhận node mới từ luồng tự phát hiện (`discovery`) hoặc ghép trực tiếp theo địa chỉ MAC nhập tay (fallback MVP).
3. Cập nhật hiệu chuẩn ẩm đất 2 điểm (`soil_dry_raw`, `soil_wet_raw`) và đồng bộ tức thời xuống Gateway qua bản tin `cfg` retained.

## 2. Trạng thái hiện thực trong repo

- **Đã hoàn thiện (M2):**
  - `platform/api/provisioning.py`: `build_gateway_dynsec_commands`, `provision_gateway_mqtt` (giao tiếp `$CONTROL/dynamic-security/v1` qua `aiomqtt`, hỗ trợ chạy `SelectorEventLoop` trong thread riêng trên Windows khi FastAPI chạy `ProactorEventLoop`).
  - `platform/api/routers/devices.py`:
    - `POST /api/gateways`
    - `GET /api/gateways/{gateway_id}/status`
    - `GET /api/nodes?status=`
    - `POST /api/nodes/{mac}/pair`
    - `PUT /api/zones/{zone_id}/calibration`
  - `platform/worker/ingest.py`: `handle_discovery` ghi/cập nhật `device_nodes(status='discovered')` và phát WS `node_discovered`.
- **Cần kiểm tra/mở rộng ở Web Console (M3–M4):**
  - Trang Thiết bị trên `web/` cần gọi đầy đủ 5 endpoint trên (hiển thị password MQTT **1 lần duy nhất** trong modal ngay sau khi gọi `POST /api/gateways`, hiển thị danh sách node `discovered` + form nhập MAC thủ công + form hiệu chuẩn ẩm đất).

## 3. Luồng nghiệp vụ chi tiết (MUST)

### 3.1 Cấp phát Gateway (`POST /api/gateways`, vai trò: `owner`)

1. Kiểm tra `greenhouse_id` thuộc `user.farm_id` (`get_owned_greenhouse`).
2. Kiểm tra nhà kính chưa có gateway (`UNIQUE(greenhouse_id)`). Nếu đã có → trả `409 Conflict` (`"Nhà kính này đã được cấp phát gateway"`).
3. Sinh credential duy nhất:
   - `mqtt_username = f"gw_{gh.id.hex[:12]}"`
   - `mqtt_password = secrets.token_urlsafe(20)` (chỉ trả về 1 lần trong response, **không** lưu plaintext vào DB).
4. Gọi `provision_gateway_mqtt(farm_id, gh.id, mqtt_username, mqtt_password)`:
   - Kết nối tới Mosquitto nội bộ (`Settings.mqtt_host:mqtt_port`, tài khoản `api-admin`).
   - Subscribe `$CONTROL/dynamic-security/v1/response` (QoS 1), publish 4 lệnh tới `$CONTROL/dynamic-security/v1`:
     1. `deleteClient` (`mqtt_username`) — idempotent nếu seed/re-provision.
     2. `deleteRole` (`gw-{greenhouse_id}`) — idempotent.
     3. `createRole` (`gw-{greenhouse_id}`) với **ACL khóa chặt** theo prefix `prefix = f"gh/{farm_id}/{greenhouse_id}"`:
        - Đọc (`subscribePattern`, `publishClientReceive`, `subscribeLiteral`):
          - `{prefix}/cmd/#`
          - `{prefix}/cfg`
        - Ghi (`publishClientSend`):
          - `{prefix}/telemetry/#`
          - `{prefix}/status`
          - `{prefix}/event`
          - `{prefix}/discovery`
          - `{prefix}/ack/#`
     4. `createClient` (`mqtt_username`, `mqtt_password`, gắn role `gw-{greenhouse_id}`).
   - Kiểm tra 2 response cuối không có `"error"` (timeout 8 s).
5. Lưu `Gateway(greenhouse_id=gh.id, mqtt_username=..., is_simulated=body.is_simulated, online=False)`.
6. Đảm bảo tồn tại `DeviceState` (`ensure_device_state`), gửi `pg_notify(CHANNEL_WORKER, {"type": "cfg_updated", "greenhouse_id": ...})` để worker chuẩn bị `cfg` retained ngay khi gateway kết nối.
7. Trả `201 Created` với `GatewayProvisionResponse`:
   `{gateway_id, farm_id, greenhouse_id, mqtt_username, mqtt_password, host: Settings.mqtt_public_host, port: Settings.mqtt_public_port, is_simulated}`.

### 3.2 Phát hiện node lạ & Ghép node vào zone

- **Luồng tự phát hiện (`discovery`):**
  1. Node chưa ghép phát `PKT_HELLO` (hoặc `PKT_TELEMETRY` từ MAC lạ) tới Gateway.
  2. Gateway publish lên `gh/{farm_id}/{gh_id}/discovery`: `{"ts":"...","mac":"AA:BB:CC:DD:EE:03","fw":"1.0","rssi":-62}`.
  3. Worker (`IngestService.handle_discovery`) chuẩn hóa MAC (`AA:BB:CC:DD:EE:03`), upsert `device_nodes` với `status='discovered'` (chỉ ghi đè `greenhouse_id` nếu node đang ở `discovered`, không cướp node đã `paired`), phát WS `device_status` (`event="node_discovered"`).
  4. Owner xem danh sách qua `GET /api/nodes?status=discovered`.
- **Luồng ghép node (`POST /api/nodes/{mac}/pair`, vai trò: `owner`):**
  - Body: `{"zone_id": "<uuid>"}`.
  - Chuẩn hóa MAC qua `normalize_mac(mac)` (`aa-bb-cc-dd-ee-03` → `AA:BB:CC:DD:EE:03`; sai định dạng → `422`).
  - Kiểm tra `zone_id` thuộc `user.farm_id` (`404` nếu không tìm thấy).
  - Nếu MAC đã từng thuộc farm khác → `403 Forbidden`.
  - **1 zone tại 1 thời điểm chỉ gắn node mới nhất:** các `DeviceNode` khác đang gắn vào `zone.id` được đưa về `zone_id = None, status = 'discovered'`.
  - Hỗ trợ cả 2 trường hợp (điểm mở #4 trong `DECISIONS.md`):
    - Node đã có trong `device_nodes` (`status='discovered'`) → cập nhật `greenhouse_id`, `zone_id`, `status='paired'`.
    - Node **chưa** từng `discovery` (nhập MAC thủ công) → tạo mới `DeviceNode(..., status='paired')`.
  - Tăng `cfg_version_desired` (`bump_cfg_version`) và gửi `pg_notify(CHANNEL_WORKER, {"type": "cfg_updated", ...})` trước khi commit để worker publish ngay `cfg` retained mới xuống gateway.

### 3.3 Hiệu chuẩn ẩm đất 2 điểm (`PUT /api/zones/{zone_id}/calibration`, vai trò: `owner`)

- Body: `{"soil_dry_raw": 2900, "soil_wet_raw": 1300}` (`soil_dry_raw ∈ [100, 4090]`, `soil_wet_raw ∈ [50, 4000]`, và `soil_dry_raw != soil_wet_raw`).
- Lưu vào `zones.soil_dry_raw`, `zones.soil_wet_raw`.
- Tăng `cfg_version_desired` và thông báo `worker_events` (`cfg_updated`) để gateway đẩy `CfgPkt` mới xuống node.

### 3.4 Trạng thái Gateway (`GET /api/gateways/{gateway_id}/status`, vai trò: `viewer`)

- Trả trạng thái kết nối (`online`, `last_seen`, `fw_version`, `rssi`, `is_simulated`) kèm Device Shadow (`reported`, `desired`, `cfg_version_desired`, `cfg_version_reported`).

## 4. Kiểm tra & Xác nhận

- Unit tests: `test_dynsec_acl_topic_isolation_and_topic_parser`, `test_manual_mac_pairing_and_cfg_version_bump`.
- Integration test (`test_m2_end_to_end_pipeline`):
  - Cấp phát gateway → kết nối bằng credential vừa cấp qua port TLS `8883` thành công.
  - Gửi `discovery` → thấy trên `GET /api/nodes?status=discovered` → ghép bằng `pair` + test ghép MAC nhập tay → `GET /api/greenhouses/{id}/config-sync` đạt `synced: true`.
  - Thử kết nối MQTT bằng user của Gateway A nhưng publish/subscribe sang topic của Gateway B → Mosquitto từ chối theo Dynamic Security ACL.
