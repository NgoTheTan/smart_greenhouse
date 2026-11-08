# Feature: Simulator Thiết bị (MQTT TLS), Thử tải & Công cụ Dev (`tools/simulator/`, `tools/`)

> Nguồn đặc tả: `docs/greenhub-spec.md` mục 1, 2.1, 4.3, 5, 6.2, 8.1, 8.5, 11, 15 (Kịch bản D), 16 (M2, M4, M5); `docs/DECISIONS.md`.

## 1. Mục tiêu & Phạm vi

Xây dựng bộ giả lập thiết bị hoạt động như một hoặc hàng trăm Gateway + Sensor Node thật và cung cấp các tiện ích khởi tạo môi trường phát triển:
1. **Đi qua đúng luồng thiết bị thật (spec §1, §11):** Đăng nhập JWT → tạo greenhouse → `POST /api/gateways (is_simulated=true)` → nhận credential MQTT riêng (Dynamic Security) → kết nối **MQTT over TLS (:8883)**, gửi `status` + LWT, nhận `cfg`, publish `telemetry/{zone}`, thực thi `cmd/{actuator}` và phản hồi `ack/{cmd_id}`.
2. **Làm chuẩn tham chiếu an toàn biên (`GatewaySafetyEngine`):** Mô phỏng chính xác các ràng buộc an toàn ở gateway (interlock quạt–ẩm, auto-off, giới hạn `max_run_s`/`min_gap_s`/`max_total_s_per_hour`, idempotency `cmd_id`, `expires_at`) để test unit trước khi nạp C++ lên ESP32.
3. **Sinh kịch bản kiểm thử & demo (`normal`, `humid_spike`, `dry_down`, `sensor_fault`)** và **thử tải 50–100 gateway** lên Docker local hoặc AWS EC2 `t3.small`.
4. **Tách bạch nguồn dữ liệu:** Gắn nhãn `readings.source = 'sim'` ở backend để không làm sai lệch tập test/báo cáo AI trên dữ liệu `real`.

- **Ngoài phạm vi:** Không giả lập tầng ESP-NOW nhị phân (simulator đóng vai Gateway kết nối thẳng MQTT TLS); không dùng dữ liệu `sim` để tính chỉ số báo cáo chính của AI/ML (spec §8.1).

## 2. Trạng thái hiện thực trong repo

- **Đã hoàn thiện (M2):**
  - `tools/simulator/requirements.txt`: gọn nhẹ chỉ `aiomqtt==2.5.1` và `httpx==0.28.1` (chạy độc lập trên laptop không cần `platform`).
  - `tools/simulator/__main__.py`: CLI đầy đủ các cờ `--api`, `--email`, `--password`, `--farms`, `--gateways`, `--nodes-per-gw`, `--interval`, `--scenario`, `--insecure`, `--dry-run`; tái sử dụng `.dev-gateway.json` khi `--farms 1 --gateways 1`, hoặc tự gọi HTTP provisioning API.
  - `tools/simulator/gateway_client.py`:
    - `ZoneSafetyLimits` & `GatewaySafetyEngine`: hoàn chỉnh logic `apply_cfg`, `tick`, `apply_command` (dedupe 50 ID, `expires_at`, interlock, `min_gap_s`, sliding window `max_total_s_per_hour`, clamping `duration_s`).
    - `SimulatedGateway`: kết nối `aiomqtt.Client` với TLS + LWT retained `{"online":false}`, subscribe `cfg` & `cmd/#`, heartbeat `status` mỗi 30 s, mô hình vật lý `_step_physics` cho 4 kịch bản.
  - `tools/seed_dev.py`, `tools/gen_vapid.py`, `tools/gen_dev_certs.py`: hoàn chỉnh và chạy tốt ngoài Docker (Windows `SelectorEventLoop` + patch host DB/MQTT).
  - `platform/tests/test_gateway_sim_safety.py`: unit test cho `GatewaySafetyEngine` (T3–T6, T10).
- **Cần mở rộng / kiểm chứng ở M4–M5:**
  - **Đa farm độc lập cho Kịch bản D:** Hiện tại trong `__main__.py`, vòng lặp `total = args.farms * args.gateways` dùng chung 1 tài khoản `--email` (tất cả nhà kính thuộc cùng `farm_id` của user đó). Khi kiểm thử cô lập đa farm (User Farm A không thấy Farm B), cần chạy 2 phiên với 2 tài khoản owner thuộc 2 farm khác nhau (hoặc bổ sung script/flag seed tạo thêm Farm B + user `owner_b@...`).
  - **Đo đạc thử tải M5 (spec §8.5):** Bổ sung cơ chế/script tổng hợp log hoặc đo trực tiếp thông lượng (`msg/s`), độ trễ `ingest-to-DB` (`p50`/`p95` từ timestamp gửi tới thời điểm DB commit) và theo dõi CPU/RAM/CPU credits của EC2 `t3.small`.
  - **Tự động ghép node / tạo zone cho simulator mới:** Hiện `POST /api/greenhouses` tự tạo zone hay không phụ thuộc router `greenhouses.py`; khi provisioning nhiều gateway giả lập mới cho thử tải hoặc M4, cần đảm bảo từng greenhouse mới tạo có đủ `zones` tương ứng `nodes_per_gw` (mặc định router tạo sẵn zone hoặc simulator gọi API tạo/cập nhật zone nếu cần) để `worker/ingest.py` không drop telemetry do thiếu `Zone.zone_index`!

## 3. Chi tiết CLI & Luồng Provisioning (`tools/simulator/__main__.py`)

### 3.1 Tham số dòng lệnh (`parse_args`)

| Cờ CLI | Mặc định | Ý nghĩa |
|---|---|---|
| `--api` | `https://localhost/api` | Base URL của REST API (qua Caddy HTTPS hoặc HTTP dev). |
| `--email` | `owner@greenhub.vn` | Email tài khoản `owner` dùng để tạo greenhouse và gateway. |
| `--password` | `greenhub123` | Mật khẩu đăng nhập. |
| `--farms` | `1` | Hệ số nhân số lượng farm logic (tổng số gateway = `farms * gateways`). |
| `--gateways` | `1` | Số gateway trên mỗi farm. |
| `--nodes-per-gw` | `2` | Số node/zone mà mỗi gateway giả lập (`zone` từ `1` tới `nodes_per_gw`). |
| `--interval` | `10.0` | Chu kỳ phát telemetry mỗi zone (giây). |
| `--scenario` | `normal` | Kịch bản vật lý: `normal` \| `humid_spike` \| `dry_down` \| `sensor_fault`. |
| `--insecure` | `False` | Bỏ kiểm tra chứng chỉ SSL/TLS cho cả HTTPS API (Caddy self-signed) và MQTTS `:8883` (`CERT_NONE`, tắt `check_hostname`). Chỉ dùng ở `dev`! |
| `--dry-run` | `False` | Chỉ kiểm tra phân tích tham số CLI và thoát ngay, không mở kết nối mạng. |

### 3.2 Quy trình khởi tạo Gateway (`_provision_or_load_gateways`)

1. **Tái sử dụng nhanh ở dev (`farms == 1` và `gateways == 1`):** Nếu file `<repo_root>/.dev-gateway.json` tồn tại (do `tools/seed_dev.py` tạo), đọc trực tiếp JSON credential thay vì tạo thêm nhà kính mới mỗi lần chạy.
2. **Đăng ký qua API:** Mở `httpx.AsyncClient(base_url=args.api, verify=not args.insecure, timeout=15.0)`:
   - `POST /auth/login` -> lấy `access_token` (`Bearer`).
   - Lặp `idx = 1 .. (args.farms * args.gateways)`:
     - `POST /greenhouses` với `{"name": f"Nhà kính Sim #{idx}", "location": "Simulator"}` -> nhận `gh["id"]`.
     - `POST /gateways` với `{"greenhouse_id": gh["id"], "is_simulated": True}` -> nhận `{gateway_id, farm_id, greenhouse_id, mqtt_username, mqtt_password, host, port}`.
3. **Chạy song song:** Tạo `SimulatedGateway(...)` cho từng credential và chạy đồng thời bằng `asyncio.gather(*tasks)`. Trên Windows (`sys.platform == "win32"`), ép `asyncio.SelectorEventLoop` vì `aiomqtt` không chạy với `ProactorEventLoop`.

> [!WARNING]
> Khi triển khai thử tải với `--gateways > 1` (tạo nhà kính mới tinh qua `POST /api/greenhouses`), hãy kiểm tra trong `platform/api/routers/farms.py` xem `POST /greenhouses` đã tự động tạo sẵn `Zone 1` & `Zone 2` hay chưa. Vì `IngestService.handle_telemetry` tra `Zone` theo `(greenhouse_id, zone_index)`, nếu nhà kính mới chưa có `Zone` tương ứng thì worker sẽ log `"Bỏ qua telemetry không khớp zone"` và không ghi vào `readings`.

## 4. Động cơ An toàn Biên (`GatewaySafetyEngine` trong `gateway_client.py`)

Class `GatewaySafetyEngine` mô phỏng chính xác máy trạng thái an toàn của firmware gateway (spec §4.3):

### 4.1 Cấu hình & Trạng thái nội bộ

- **Mặc định (`ZoneSafetyLimits` theo bộ `demo`):**
  - `irrigation_max_run_s = 15`, `irrigation_min_gap_s = 90`, `irrigation_max_total_s_per_hour = 120`
  - `fan_max_on_s = 300`, `mist_max_on_s = 300`
- **Cấu hình cập nhật (`apply_cfg`):** Nhận JSON `cfg` từ topic `.../cfg`, kiểm tra `cfg_version != self.cfg_version`, cập nhật `limits` cho từng bơm (`pump_1`, `pump_2`), `fan_max_on_s`, `mist_max_on_s`, `sample_interval_s`.
- **Trạng thái theo dõi:**
  - `actuators`: `{"pump_1": "off", "pump_2": "off", "fan": "off", "mist": "off"}`.
  - `_off_deadlines`: thời điểm monotonic cần tự tắt từng actuator.
  - `_last_pump_end`: thời điểm monotonic bơm tắt gần nhất (dùng kiểm tra `min_gap_s`).
  - `_pump_history`: `deque[tuple[float, int]]` (bộ nhớ cửa sổ trượt `3600.0` s cho `irrigation_max_total_s_per_hour`).
  - `_seen_cmd_ids`: `deque(maxlen=50)` lưu 50 `cmd_id` gần nhất để khử trùng lệnh (idempotent).

### 4.2 Luồng xử lý lệnh (`apply_command(cmd, now_utc, now_mono)`)

1. Gọi `self.tick(now_mono)` trước để tắt các actuator đã hết hạn và cập nhật `_last_pump_end`.
2. Kiểm tra `cmd_id`: nếu rỗng hoặc đã có trong `_seen_cmd_ids` → trả `None` (bỏ qua, không gửi ACK trùng). Nếu mới → thêm vào `_seen_cmd_ids`.
3. Kiểm tra `expires_at`: parse ISO 8601; nếu `exp_dt <= now_utc` → trả `status="expired"`, giữ nguyên relay.
4. Validate `actuator in ("pump_1", "pump_2", "fan", "mist")` và `action in ("on", "off")`; sai → `_reject(cmd_id, "invalid")`.
5. Nếu `action == "off"`: tắt actuator, xóa deadline, nếu là bơm đang chạy thì ghi `_last_pump_end[actuator] = now_mono`, trả `status="applied"`.
6. Nếu `action == "on"`:
   - Kiểm tra `duration_s` phải tồn tại và `> 0`; ngược lại → `_reject(cmd_id, "invalid")`.
   - **Interlock Quạt – Máy tạo ẩm:**
     - Nếu `actuator == "mist"` và `actuators["fan"] == "on"` → `_reject(cmd_id, "interlock")`.
     - Nếu `actuator == "fan"` và `actuators["mist"] == "on"` → ép tắt `mist`, xóa deadline của `mist`, ghi `side_effects.append("mist_off")`.
   - **Giới hạn thời gian & Bơm:**
     - Bơm (`pump_1`, `pump_2`): `eff_duration = min(req_duration, lim.irrigation_max_run_s)`.
     - Nếu bơm đang tắt và `now_mono - last_end < lim.irrigation_min_gap_s` → `_reject(cmd_id, "min_gap")`.
     - Nếu `_pump_used_last_hour(actuator, now_mono) + eff_duration > lim.irrigation_max_total_s_per_hour` → `_reject(cmd_id, "max_total")`.
     - Đạt → ghi `(now_mono, eff_duration)` vào `_pump_history[actuator]`.
     - Quạt / Tạo ẩm: `eff_duration = min(req_duration, fan_max_on_s / mist_max_on_s)`.
   - Bật `actuators[actuator] = "on"`, đặt `_off_deadlines[actuator] = now_mono + eff_duration`, trả `status="applied"` kèm `side_effects` và snapshot `state`.

## 5. Mô hình Vật lý & Client MQTT TLS (`SimulatedGateway`)

### 5.1 Kết nối & Chủ đề MQTT

- **TLS Context (`make_tls_context`):** Nếu `ca_cert` (`deploy/certs/ca.crt`) tồn tại thì nạp làm CA tin cậy; nếu `insecure=True` thì tắt verify hostname & cert. Chỉ dùng TLS khi `mqtt_port == 8883`.
- **Client ID:** `f"sim-{mqtt_username}"`, `keepalive=15`.
- **Last Will & Testament (LWT):** Topic `gh/{farm_id}/{gh_id}/status`, payload `b'{"online":false}'`, `qos=1`, `retain=True`.
- **Vòng nhận (`_rx_loop`):** Subscribe `cfg` và `cmd/#` (`qos=1`). Khi nhận `cfg` thay đổi version → publish ngay `status` retained cập nhật `cfg_version`. Khi nhận `cmd` → `safety.apply_command` → nếu có ACK thì publish `ack/{cmd_id}` (`qos=1`, `retain=False`).
- **Vòng gửi (`_tx_loop`):** Mỗi chu kỳ `interval_s`:
  - Gọi `safety.tick(now_m)`; nếu có actuator vừa tự tắt hoặc đã quá `30.0` s từ lần heartbeat trước → publish `status` retained (`fw="1.0.0-sim"`, `heap=184000`, `queue_len=0`, danh sách node giả lập `AA:BB:CC:DD:EE:{z:02X}`).
  - Với mỗi zone `1..nodes_per_gw`: sinh telemetry từ `_step_physics` và publish `telemetry/{z}` (`qos=1`, `retain=False`).

### 5.2 Mô hình Vật lý & 4 Kịch bản (`_step_physics`)

Khởi tạo ban đầu mỗi zone `z`: `air_t = 25.0 + z * 0.4` (°C), `air_rh = 72.0` (%), `soil_m = 64.0` (%), `lux = 16000.0`.

| Đại lượng / Kịch bản | Quy luật biến thiên mỗi bước `dt_s` | Mục đích kiểm thử |
|---|---|---|
| `air_t` | Nhiễu `uniform(-0.15, +0.15)`; nếu `fan` bật giảm thêm `-0.04 * dt_s`. | Phản ứng hạ nhiệt khi quạt chạy. |
| `air_rh` | `humid_spike` hoặc `mist` bật: `+0.35 * dt_s` (tối đa `98.5%`); `fan` bật: `-0.25 * dt_s` (tối thiểu `50.0%`); thường: nhiễu `±0.4` kẹp `[45.0, 95.0]`. | Kích hoạt VPD tụt < `low_crit` → `DISEASE_RISK` & ép tắt `mist`. |
| `soil_m` | `pump_{z}` bật: `+0.9 * dt_s` (tối đa `92.0%`); `dry_down`: `-0.25 * dt_s` (tối thiểu `22.0%`); thường: `-0.02 * dt_s` (tối thiểu `30.0%`). | Kích hoạt `soil < soil_min` → bơm hysteresis & tính `irrigation_eta`. |
| `lux` | `max(0.0, lux + uniform(-300, +300))` cho **`zone == 1`**; các zone khác gửi `lux = None` (mô phỏng node 2 không có BH1750). | Kiểm tra DLI trên Node 1 và handling `lux=null` ở Node 2+. |
| `soil_raw` | Quy đổi tuyến tính ngược từ `soil_m` theo khoảng mẫu `[2900, 1300]`: `int(2900 - (soil_m / 100.0) * 1600)`. | Khớp hiệu chuẩn 2 điểm mặc định. |
| `sensor_fault` | Riêng tại `zone_idx == 2`: gán `soil_raw = 0`, `flags = 1 << 1` (`FLAG_SOIL_ERR`). | Kích hoạt A1 (`out_of_range` / `dropout`), chặn tưới sai, bật `SENSOR_FAULT`. |

> [!IMPORTANT]
> Ở backend (`platform/worker/ingest.py` dòng 144), cột `readings.source` được gán `"sim" if (gw is not None and gw.is_simulated) else "real"`. Không bao giờ cung cấp tùy chọn ghi đè `is_simulated=false` từ CLI simulator.

## 6. Hướng dẫn Thử tải (Load Test – Spec §8.5)

- **Quy mô mục tiêu:** 50–100 gateway, mỗi gateway 2 node, chu kỳ 10 s:
  - 50 gateway × 2 node / 10 s ≈ **10 bản tin telemetry/giây** (+ heartbeat `status` 30 s/lần).
  - 100 gateway × 2 node / 10 s ≈ **20 bản tin telemetry/giây** (+ ~3.3 `status`/giây) + truy vấn rule engine + DB write + `pg_notify` WS.
- **Lệnh mẫu (chạy từ laptop trỏ lên EC2):**
  ```powershell
  python -m tools.simulator --api https://<domain>.duckdns.org/api --email owner@greenhub.vn --password <PASS> --farms 10 --gateways 10 --nodes-per-gw 2 --interval 10 --scenario normal
  ```
- **Ràng buộc EC2 `t3.small` (MUST tuân thủ):**
  - `t3.small` là instance **burstable** (2 vCPU, 2 GB RAM, baseline CPU thấp ~20% vCPU trước khi tiêu hao CPU credits).
  - Chạy thử tải theo **từng đợt ngắn** (5–15 phút), đồng bộ đồng hồ NTP giữa laptop và EC2 nếu đo độ trễ theo `payload.ts`, và theo dõi đồng thời:
    - `docker stats` trên EC2 (RAM trần các container: TimescaleDB 640 MB, Worker 512 MB, API 384 MB, Mosquitto 128 MB, Caddy 128 MB).
    - AWS CloudWatch metric `CPUCreditBalance`.
- **Chỉ số cần đo và ghi nhận trong báo cáo (ghi rõ tải mô phỏng):**
  1. **Throughput (`msg/s`):** số bản tin/giây nhận được ở Mosquitto và số dòng ghi vào `readings` trong cửa sổ thử tải.
  2. **Độ trễ Ingest-to-DB (`p50`, `p95` ms):** chênh lệch từ thời điểm gateway phát telemetry tới khi `worker` commit xong vào TimescaleDB (có thể đo qua cột `created_at` hoặc log timing trong worker/harness benchmark).
  3. **Mức sử dụng CPU / RAM / DB connections:** đảm bảo không container nào OOM-kill và số kết nối DB giữ ổn định dưới `max_connections=50`.

## 7. Các Công cụ Dev khác trong `tools/`

### 7.1 `tools/seed_dev.py` (`python -m tools.seed_dev`)

- Tạo idempotent bộ dữ liệu phát triển hoàn chỉnh trên stack Docker dev đang chạy:
  - **Farm:** `"Nông trại Demo GreenHub"`.
  - **3 Users + `NotificationPref`:** `owner@greenhub.vn` (`owner`), `operator@greenhub.vn` (`operator`), `viewer@greenhub.vn` (`viewer`) — mật khẩu chung `greenhub123` (băm Argon2).
  - **Greenhouse:** `"Nhà kính Fomex 01"` (`"Phòng thí nghiệm IoT"`).
  - **2 Zones:** Zone 1 `"Zone 1 – Cà chua bi"` (`TEMPLATE_TOMATO_DEMO_ID`, `pump_channel=1`), Zone 2 `"Zone 2 – Dâu tây"` (`TEMPLATE_STRAWBERRY_DEMO_ID`, `pump_channel=2`), hiệu chuẩn `2900 / 1300`.
  - **2 Paired Nodes:** `AA:BB:CC:DD:EE:01` (Zone 1) và `AA:BB:CC:DD:EE:02` (Zone 2).
  - **DeviceState:** `cfg_version_desired=1`, `cfg_version_reported=0`.
  - **Gateway + MQTT DynSec:** gọi `provision_gateway_mqtt` cấp user `gw_{gh.id.hex[:12]}`, tạo bản ghi `Gateway(is_simulated=True)`, phát `pg_notify` `"cfg_updated"`, và lưu thông tin ra `.dev-gateway.json`.

### 7.2 `tools/gen_vapid.py` (`python -m tools.gen_vapid`)

- Sinh cặp khóa EC đường cong `SECP256R1` bằng thư viện `cryptography`, encode dạng `urlsafe_b64` không có padding `=`, in ra hai biến `VAPID_PUBLIC_KEY` và `VAPID_PRIVATE_KEY` để chép vào `.env`.

### 7.3 `tools/gen_dev_certs.py` (`python -m tools.gen_dev_certs [LAN_IP]`)

- Giải pháp Python thuần đa nền tảng (chạy tốt trên Windows không cần Git Bash/OpenSSL) tương đương `deploy/scripts/gen-dev-certs.sh`.
- Sinh (hoặc tái sử dụng) CA `"GreenHub Dev CA"` (RSA 2048, hạn 3650 ngày) tại `deploy/certs/ca.{key,crt}` và ký `server.{key,crt}` (hạn 825 ngày, `ExtendedKeyUsage: SERVER_AUTH`, SAN gồm `DNS:localhost`, `DNS:mosquitto`, `IP:127.0.0.1`, và `IP:<LAN_IP>` nếu truyền đối số).

## 8. Kiểm thử & Xác nhận

```powershell
# 1. Unit test quy tắc an toàn Gateway (interlock, min_gap, max_total, expired, idempotency)
.venv\Scripts\pytest.exe platform/tests/test_gateway_sim_safety.py

# 2. Kiểm tra CLI dry-run (không cần stack Docker)
.venv\Scripts\python.exe -m tools.simulator --dry-run --farms 10 --gateways 10 --scenario dry_down

# 3. Chạy 1 gateway dev dùng .dev-gateway.json trên local stack
.venv\Scripts\python.exe -m tools.simulator --interval 10 --scenario humid_spike --insecure

# 4. Integration test full pipeline (cần Docker dev stack đang chạy)
.venv\Scripts\pytest.exe -v -m integration platform/tests/test_m2_integration.py
```
