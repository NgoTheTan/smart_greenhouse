# Feature: Simulator Thiết bị (MQTT TLS), Sinh dữ liệu Năng suất, Thử tải & Công cụ Dev (`tools/simulator/`, `tools/`)

> Nguồn đặc tả: `docs/greenhub-spec.md` mục 1, 2.1, 4.3, 5, 6.2, 8.1, 8.2, 8.4, 11, 13.3, 15 (Kịch bản D, E), 16 (M2, M4, M5); `docs/DECISIONS.md`. Tài liệu AI liên quan: [ml/FEATURE_AI_YIELD_AND_RECOMMENDATION.md](../../ml/FEATURE_AI_YIELD_AND_RECOMMENDATION.md).

## 1. Mục tiêu & Phạm vi

Xây dựng bộ giả lập thiết bị hoạt động như một hoặc hàng trăm Gateway + Sensor Node thật, bộ sinh dữ liệu huấn luyện tổng hợp cho bài toán năng suất/gợi ý cây trồng, và các tiện ích khởi tạo môi trường phát triển:
1. **Đi qua đúng luồng thiết bị thật (spec §1, §11):** Đăng nhập JWT → tạo greenhouse → `POST /api/gateways (is_simulated=true)` → nhận credential MQTT riêng (Dynamic Security) → kết nối **MQTT over TLS (:8883)**, gửi `status` + LWT, nhận `cfg`, publish `telemetry/{zone}`, thực thi `cmd/{actuator}` và phản hồi `ack/{cmd_id}`. Hỗ trợ mô phỏng theo vùng khí hậu (`--region`), mức trang bị (`equipment_level`), tạo vụ trồng và báo thu hoạch qua REST API để sinh dữ liệu `source='sim'`.
2. **Làm chuẩn tham chiếu an toàn biên (`GatewaySafetyEngine`):** Mô phỏng chính xác các ràng buộc an toàn ở gateway (interlock quạt–ẩm, auto-off, giới hạn `max_run_s`/`min_gap_s`/`max_total_s_per_hour`, idempotency `cmd_id`, `expires_at`) để test unit trước khi nạp C++ lên ESP32.
3. **Sinh kịch bản kiểm thử & demo (`normal`, `humid_spike`, `dry_down`, `sensor_fault`)** và **thử tải 50–100 gateway** lên Docker local hoặc **VPS Linux** (≥ 2 vCPU, 2 GB RAM).
4. **Sinh dữ liệu huấn luyện offline (`synth-yield`):** Tạo tập dữ liệu tổng hợp `source='synthetic'` (hàng trăm nhà kính × nhiều vụ) bằng mô hình sinh trưởng ẩn (`tools/simulator/growth.py` + `tools/simulator/crops_growth.json`) kết hợp hàm trích đặc trưng dùng chung `platform/core/climate_features.py` (`feature_version = 1`).
5. **Tách bạch nguồn dữ liệu:** Dữ liệu từ gateway giả lập được backend gắn `readings.source = 'sim'` (và `yield_samples.source = 'sim'` khi thu hoạch vụ trên farm giả lập), phân biệt rạch ròi với `real` và `synthetic` khi huấn luyện và báo cáo metrics AI theo từng `source`.

- **Ngoài phạm vi:** Không giả lập tầng ESP-NOW nhị phân (simulator đóng vai Gateway kết nối thẳng MQTT TLS); không để mã nguồn huấn luyện `ml/` hay suy luận `worker/` truy cập vào mô hình sinh trưởng ẩn `growth.py` / `crops_growth.json`.

## 2. Trạng thái hiện thực trong repo

- **Đã hoàn thiện (M2):**
  - `tools/simulator/requirements.txt`: gọn nhẹ chỉ `aiomqtt==2.5.1` và `httpx==0.28.1` (chạy độc lập trên laptop không cần `platform`).
  - `tools/simulator/__main__.py`: CLI hiện tại hỗ trợ `--api`, `--email`, `--password`, `--farms`, `--gateways`, `--nodes-per-gw`, `--interval`, `--scenario`, `--insecure`, `--dry-run`; tái sử dụng `.dev-gateway.json` khi `--farms 1 --gateways 1`, hoặc tự gọi HTTP provisioning API.
  - `tools/simulator/gateway_client.py`:
    - `ZoneSafetyLimits` & `GatewaySafetyEngine`: hoàn chỉnh logic `apply_cfg`, `tick`, `apply_command` (dedupe 50 ID, `expires_at`, interlock, `min_gap_s`, sliding window `max_total_s_per_hour`, clamping `duration_s`).
    - `SimulatedGateway`: kết nối `aiomqtt.Client` với TLS + LWT retained `{"online":false}`, subscribe `cfg` & `cmd/#`, heartbeat `status` mỗi 30 s, mô hình vật lý `_step_physics` cho 4 kịch bản.
  - `tools/seed_dev.py`, `tools/gen_vapid.py`, `tools/gen_dev_certs.py`: hoàn chỉnh và chạy tốt ngoài Docker (Windows `SelectorEventLoop` + patch host DB/MQTT).
  - `platform/tests/test_gateway_sim_safety.py`: unit test cho `GatewaySafetyEngine` (T3–T6, T10).
- **Cần mở rộng / hiện thực ở M4–M5:**
  - **Vùng khí hậu & mức trang bị cho simulator trực tuyến (M4):** Bổ sung `--region` (`dalat`, `hanoi_winter`, `hanoi_summer`, `hcm`, `mekong`, `central_coast`) và `--equipment-level` vào `__main__.py` và `SimulatedGateway` để mô phỏng nền nhiệt/RH/DLI và biến thiên ngày/đêm đặc trưng từng vùng (phục vụ Kịch bản E: gợi ý cây trồng khác nhau hợp lý theo vùng khí hậu).
  - **Tạo vụ trồng & báo thu hoạch qua REST API (M4–M5):** Hỗ trợ tạo vụ (`POST /api/zones/{id}/cycles`) và báo thu hoạch (`POST /api/cycles/{id}/harvest`) cho nhà kính giả lập để kiểm thử end-to-end luồng thu hoạch → worker tính đặc trưng → tạo `yield_samples(source='sim')`.
  - **Đa farm độc lập cho Kịch bản D:** Hiện tại trong `__main__.py`, vòng lặp `total = args.farms * args.gateways` dùng chung 1 tài khoản `--email` (tất cả nhà kính thuộc cùng `farm_id` của user đó). Khi kiểm thử cô lập đa farm (User Farm A không thấy Farm B), cần chạy 2 phiên với 2 tài khoản owner thuộc 2 farm khác nhau (hoặc bổ sung script/flag seed tạo thêm Farm B + user `owner_b@...`).
  - **Bộ sinh dữ liệu huấn luyện offline `synth-yield` (M5):** Hiện thực subcommand `synth-yield`, `tools/simulator/growth.py` và `tools/simulator/crops_growth.json` (tất định theo `--seed`, dùng `platform/core/climate_features.py`).
  - **Đo đạc thử tải M5 (spec §8.4):** Bổ sung cơ chế/script tổng hợp log hoặc đo trực tiếp thông lượng (`msg/s`), độ trễ `ingest-to-DB` (`p50`/`p95` từ timestamp gửi tới thời điểm DB commit) và theo dõi CPU/RAM trên **VPS Linux** (vCPU chia sẻ).
  - **Tự động ghép node / tạo zone cho simulator mới:** Đảm bảo từng greenhouse mới tạo qua `POST /api/greenhouses` có đủ `zones` tương ứng `nodes_per_gw` (và có `area_m2` nếu chạy kịch bản vụ trồng) để `worker/ingest.py` không drop telemetry do thiếu `Zone.zone_index`.
  - **Cập nhật `tools/seed_dev.py` (M4):** Đồng bộ với `crop_profiles` `schema_version = 2` (bộ 10 template hệ thống: 5 cây × `real`/`demo`), dùng schema bảng `zones` mới và bổ sung `area_m2` cho Zone 1 & Zone 2 để thử ngay luồng vụ trồng & dự báo năng suất.

## 3. Chi tiết CLI & Luồng Provisioning (`tools/simulator/__main__.py`)

### 3.1 Tham số dòng lệnh simulator trực tuyến (`parse_args`)

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
| `--region` | `None` *(M4)* | Vùng khí hậu cho simulator trực tuyến: `dalat` \| `hanoi_winter` \| `hanoi_summer` \| `hcm` \| `mekong` \| `central_coast`. Khi đặt, `_step_physics` áp dụng nền nhiệt/RH/ánh sáng và biên độ ngày/đêm theo vùng. |
| `--equipment-level` | `standard` *(M4)* | Mức trang bị mô phỏng (`basic` \| `standard` \| `full`: có/không quạt, máy tạo ẩm, lưới che nắng làm thay đổi dải khí hậu thực tế của nhà kính giả lập). |
| `--create-cycle` / `--harvest-after-s` | Tuỳ chọn *(M4–M5)* | Hỗ trợ gọi REST API tạo vụ trồng (`POST /api/zones/{id}/cycles`) cho các zone giả lập khi bắt đầu và báo thu hoạch (`POST /api/cycles/{id}/harvest`) để sinh mẫu `yield_samples(source='sim')`. |
| `--insecure` | `False` | Bỏ kiểm tra chứng chỉ SSL/TLS cho cả HTTPS API (Caddy self-signed) và MQTTS `:8883` (`CERT_NONE`, tắt `check_hostname`). Chỉ dùng ở `dev`! |
| `--dry-run` | `False` | Chỉ kiểm tra phân tích tham số CLI và thoát ngay, không mở kết nối mạng. |

*(Lưu ý: Subcommand `synth-yield` dùng cho sinh dữ liệu huấn luyện offline được đặc tả riêng tại mục 6.)*

### 3.2 Quy trình khởi tạo Gateway & Vụ trồng (`_provision_or_load_gateways`)

1. **Tái sử dụng nhanh ở dev (`farms == 1` và `gateways == 1`):** Nếu file `<repo_root>/.dev-gateway.json` tồn tại (do `tools/seed_dev.py` tạo), đọc trực tiếp JSON credential thay vì tạo thêm nhà kính mới mỗi lần chạy.
2. **Đăng ký qua API:** Mở `httpx.AsyncClient(base_url=args.api, verify=not args.insecure, timeout=15.0)`:
   - `POST /auth/login` -> lấy `access_token` (`Bearer`).
   - Lặp `idx = 1 .. (args.farms * args.gateways)`:
     - `POST /greenhouses` với `{"name": f"Nhà kính Sim #{idx}", "location": region_label}` -> nhận `gh["id"]`.
     - `POST /gateways` với `{"greenhouse_id": gh["id"], "is_simulated": True}` -> nhận `{gateway_id, farm_id, greenhouse_id, mqtt_username, mqtt_password, host, port}`.
3. **Tạo vụ trồng & Thu hoạch qua REST API (M4–M5, phục vụ dữ liệu `source='sim'`):**
   - Sau khi đăng ký nhà kính/zone (bảo đảm zone có `area_m2 > 0`), simulator (khi bật cờ tạo vụ hoặc qua kịch bản kiểm thử) gọi `POST /api/zones/{zone_id}/cycles` với `crop_profile_id`, `started_at`, `area_m2` → tạo vụ `active` và đồng bộ `cfg` xuống gateway.
   - Khi hoàn tất giai đoạn chạy mẫu (hoặc mô phỏng thu hoạch cuối vụ), gọi `POST /api/cycles/{cycle_id}/harvest` với `harvested_at` và `yield_kg` → backend phát `NOTIFY worker_events {type: "cycle_harvested", cycle_id}` → worker tính đặc trưng khí hậu trên `[started_at, harvested_at]` và ghi `yield_samples(source='sim')` (nếu `coverage < ai.min_coverage`, worker bỏ qua tạo mẫu và ghi lý do vào `crop_cycles.notes`).
4. **Chạy song song:** Tạo `SimulatedGateway(...)` cho từng credential và chạy đồng thời bằng `asyncio.gather(*tasks)`. Trên Windows (`sys.platform == "win32"`), ép `asyncio.SelectorEventLoop` vì `aiomqtt` không chạy với `ProactorEventLoop`.

> [!WARNING]
> Khi triển khai thử tải với `--gateways > 1` (tạo nhà kính mới tinh qua `POST /api/greenhouses`), hãy kiểm tra trong `platform/api/routers/farms.py` xem `POST /greenhouses` đã tự động tạo sẵn `Zone 1` & `Zone 2` (kèm `area_m2`) hay chưa. Vì `IngestService.handle_telemetry` tra `Zone` theo `(greenhouse_id, zone_index)`, nếu nhà kính mới chưa có `Zone` tương ứng thì worker sẽ log `"Bỏ qua telemetry không khớp zone"` và không ghi vào `readings`.

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

### 5.2 Mô hình Vật lý, 4 Kịch bản & Hồ sơ Vùng khí hậu (`_step_physics`)

Khởi tạo ban đầu mỗi zone `z` (mặc định khi không đặt `--region`): `air_t = 25.0 + z * 0.4` (°C), `air_rh = 72.0` (%), `soil_m = 64.0` (%), `lux = 16000.0`. Khi truyền `--region` và `--equipment-level`, nền nhiệt độ, độ ẩm, cường độ sáng ban đầu và biến thiên ngày/đêm bám theo hồ sơ vùng khí hậu tương ứng (mục 6.2).

| Đại lượng / Kịch bản | Quy luật biến thiên mỗi bước `dt_s` | Mục đích kiểm thử |
|---|---|---|
| `air_t` | Nhiễu `uniform(-0.15, +0.15)` (+ thành phần ngày/đêm theo `--region` nếu bật); nếu `fan` bật giảm thêm `-0.04 * dt_s`. | Phản ứng hạ nhiệt khi quạt chạy & phân hoá khí hậu theo vùng. |
| `air_rh` | `humid_spike` hoặc `mist` bật: `+0.35 * dt_s` (tối đa `98.5%`); `fan` bật: `-0.25 * dt_s` (tối thiểu `50.0%`); thường: nhiễu `±0.4` kẹp trong dải vùng khí hậu (hoặc `[45.0, 95.0]`). | Kích hoạt VPD tụt < `low_crit` → `DISEASE_RISK` & ép tắt `mist`. |
| `soil_m` | `pump_{z}` bật: `+0.9 * dt_s` (tối đa `92.0%`); `dry_down`: `-0.25 * dt_s` (tối thiểu `22.0%`); thường: `-0.02 * dt_s` (tối thiểu `30.0%`). | Kích hoạt `soil < soil_min` → bơm hysteresis cố định và kiểm tra giới hạn thời gian bơm. |
| `lux` | `max(0.0, lux + uniform(-300, +300))` (theo giờ ngày/đêm & mức che nắng của `equipment_level` nếu bật `--region`) cho **`zone == 1`**; các zone khác gửi `lux = None` (mô phỏng node 2 không có BH1750). | Kiểm tra DLI trên Node 1 và handling `lux=null` ở Node 2+. |
| `soil_raw` | Quy đổi tuyến tính ngược từ `soil_m` theo khoảng mẫu `[2900, 1300]`: `int(2900 - (soil_m / 100.0) * 1600)`. | Khớp hiệu chuẩn 2 điểm mặc định. |
| `sensor_fault` | Riêng tại `zone_idx == 2`: gán `soil_raw = 0`, `flags = 1 << 1` (`FLAG_SOIL_ERR`). | Kích hoạt kiểm tra chất lượng dữ liệu (luật) (`out_of_range` / `dropout`), chặn tưới sai, bật `SENSOR_FAULT`. |

> [!IMPORTANT]
> Ở backend (`platform/worker/ingest.py`), cột `readings.source` được gán `"sim" if (gw is not None and gw.is_simulated) else "real"`, và khi thu hoạch vụ trên nhà kính giả lập, `yield_samples.source` được gán `"sim"`. Không bao giờ cung cấp tùy chọn ghi đè `is_simulated=false` từ CLI simulator.

## 6. Bộ sinh dữ liệu huấn luyện offline (`synth-yield`, `growth.py`, `crops_growth.json`)

> Nguồn đặc tả: `docs/greenhub-spec.md` mục 8.2, 11, 15. Đây là nguồn dữ liệu huấn luyện chính (`source='synthetic'`) cho mô hình dự đoán năng suất & gợi ý cây trồng (`task='yield'`).

### 6.1 Lệnh CLI `synth-yield`

```powershell
python -m tools.simulator synth-yield --greenhouses 200 --cycles-per-gh 5 --seed 42 --out data/synthetic_yield.csv
```

| Cờ CLI | Mặc định | Ý nghĩa |
|---|---|---|
| `--greenhouses` | `200` | Số nhà kính giả lập độc lập (`greenhouse_key` dạng `syn-0001`..`syn-0200`). |
| `--cycles-per-gh` | `5` | Số vụ trồng sinh cho mỗi nhà kính (tổng mục tiêu `greenhouses × cycles-per-gh`, giữ các vụ có `coverage >= 0.7`). |
| `--seed` | `42` | Seed ngẫu nhiên cố định; **MUST bảo đảm tất định 100%** (cùng seed → cùng chuỗi khí hậu, đặc trưng và năng suất). |
| `--out` | `data/synthetic_yield.csv` | Đường dẫn CSV đầu ra, tương thích trực tiếp với `python -m ml.dataset import --source synthetic --file <csv>`. |

### 6.2 Vùng khí hậu (`region`), `equipment_level` & Phân bố cây trồng

1. **6 vùng khí hậu (archetype):**
   - `dalat`: mát quanh năm, biên độ ngày–đêm rõ, thuận lợi dâu tây (`strawberry`) và xà lách (`lettuce`).
   - `hanoi_winter`: mát–lạnh ẩm, ánh sáng/DLI vừa phải.
   - `hanoi_summer`: nóng ẩm, tỉ lệ giờ > 30 °C cao.
   - `hcm`: nóng ẩm quanh năm, thuận lợi dưa leo (`cucumber`) và ớt chuông (`bell_pepper`).
   - `mekong`: nóng ẩm, bức xạ/DLI cao.
   - `central_coast`: nóng, gió khô trưa (VPD cao hơn).
2. **`equipment_level` theo nhà kính:** Mỗi nhà kính được gán một vùng khí hậu, một mức trang bị mô phỏng (có/không quạt làm mát, phun ẩm, lưới che nắng → làm khí hậu giữa các nhà kính cùng vùng vẫn đa dạng) và một hiệu ứng nhà kính cố định `gh_effect ~ N(1, 0.05)` (kẹp dương, giữ nguyên cho mọi vụ của cùng `greenhouse_key` để phép chia `GroupShuffleSplit` theo nhà kính đánh giá đúng khả năng tổng quát hoá sang nhà kính chưa từng thấy).
3. **Mọi cây được trồng ở mọi vùng:** Mỗi vụ chọn ngẫu nhiên `crop_code` trong 5 cây ứng viên (`tomato_cherry`, `strawberry`, `lettuce`, `cucumber`, `bell_pepper`) ở mọi vùng khí hậu (tránh rò rỉ vùng ↔ cây, giúp mô hình ML học được tương tác cây × khí hậu).

### 6.3 Mô hình sinh trưởng ẩn (`tools/simulator/growth.py` & `crops_growth.json`)

- `tools/simulator/crops_growth.json` lưu tham số sinh học ẩn cho 5 loại cây: `Tmin`, `Topt1`, `Topt2`, `Tmax`, `dli_sat`, dải `vpd` tối ưu/ngưỡng, dải `soil` tối ưu/ngưỡng, `heat_penalty`, `reference_kg_m2`, `cycle_days`.
- Công thức năng suất tương đối trong `tools/simulator/growth.py` (tất định theo `seed`):
  ```text
  relative_yield = f_T(t_mean; Tmin, Topt1, Topt2, Tmax)
                 * f_DLI(dli_mean; dli_sat)
                 * f_VPD(vpd_mean)
                 * f_soil(soil_mean)
                 * (1 - heat_penalty * frac_t_gt_Tmax)
                 * gh_effect
                 * noise
  ```
  - `f_T`, `f_VPD`, `f_soil`: các hàm đáp ứng dạng hình thang trong `[0, 1]` (bằng `1.0` trong khoảng tối ưu, giảm tuyến tính ra biên `0.0`).
  - `f_DLI`: hàm bão hoà trong `[0, 1]` theo `dli_mean` và `dli_sat`.
  - `frac_t_gt_Tmax`: tỉ lệ giờ trong chuỗi thời tiết của vụ có nhiệt độ `> Tmax` của cây đó; thừa số `(1 - heat_penalty * frac_t_gt_Tmax)` được kẹp dưới `>= 0.0`.
  - `gh_effect ~ N(1, 0.05)` cố định theo nhà kính; `noise ~ LogNormal(0, 0.1)` sinh từ RNG gắn `seed`.
  - `yield_kg_m2 = relative_yield * reference_kg_m2(crop)`.
- **Trích xuất đặc trưng dùng chung (`platform/core/climate_features.py`):**
  - Với mỗi vụ, `synth-yield` sinh chuỗi bản ghi khí hậu theo giờ (`readings_1h`, `quality='ok'`, giờ địa phương `Asia/Ho_Chi_Minh`) và gọi **trực tiếp** hàm trích đặc trưng trong `platform/core/climate_features.py` (`feature_version = 1`) để tính 16 đặc trưng số (`t_mean`, `t_day_mean`, `t_night_mean`, `t_p95`, `t_p05`, `rh_mean`, `vpd_mean`, `vpd_std`, `frac_vpd_low`, `frac_vpd_high`, `frac_t_gt_30`, `frac_t_lt_12`, `gdd_per_day`, `dli_mean`, `soil_mean`, `soil_std`) và `coverage`. Điều này bảo đảm định nghĩa đặc trưng giữa dữ liệu huấn luyện `synthetic` và suy luận ở `worker` khớp nhau 100%.
- **Oracle cho đánh giá gợi ý (`meta.oracle_relative_yields`):**
  - Trên cùng điều kiện khí hậu của vụ đó (với ẩm đất cố định ở trung điểm tối ưu của từng cây – giả định tưới đủ như thuật toán gợi ý – và không nhân `noise`), `growth.py` tính `relative_yield` kỳ vọng cho cả 5 cây ứng viên, lưu vào `meta.oracle_relative_yields` (`{"tomato_cherry": ..., "strawberry": ..., ...}`).
  - `ml/evaluate.py` đối chiếu thứ hạng dự đoán của mô hình với `oracle_relative_yields` để đo **Top-1 accuracy** và **NDCG@3**.

> [!IMPORTANT]
> **Nguyên tắc tách biệt (MUST):** `tools/simulator/growth.py` và `tools/simulator/crops_growth.json` là ground truth ẩn chỉ dùng khi sinh dữ liệu `synthetic`. Mã nguồn huấn luyện `ml/` và suy luận `platform/worker/` **tuyệt đối không** import `growth.py` hay đọc `crops_growth.json`.

### 6.4 Định dạng CSV đầu ra (`data/synthetic_yield.csv`)

Mỗi dòng tương ứng một bản ghi chuẩn bị nạp vào `yield_samples`:
- `source` (`"synthetic"`), `greenhouse_key` (`"syn-0001"`..), `crop_code`, `started_at`, `ended_at`, `cycle_days`, `feature_version` (`1`), `features` (JSON 16 đặc trưng), `coverage`, `yield_kg_m2`, `meta` (JSON gồm `region`, `equipment_level`, `gh_effect`, `oracle_relative_yields`).

## 7. Hướng dẫn Thử tải (Load Test – Spec §8.4)

- **Quy mô mục tiêu:** 50–100 gateway, mỗi gateway 2 node, chu kỳ 10 s:
  - 50 gateway × 2 node / 10 s ≈ **10 bản tin telemetry/giây** (+ heartbeat `status` 30 s/lần).
  - 100 gateway × 2 node / 10 s ≈ **20 bản tin telemetry/giây** (+ ~3.3 `status`/giây) + truy vấn rule engine + DB write + `pg_notify` WS.
- **Lệnh mẫu (chạy từ laptop trỏ lên VPS Linux):**
  ```powershell
  python -m tools.simulator --api https://<domain>/api --email owner@greenhub.vn --password <PASS> --farms 10 --gateways 10 --nodes-per-gw 2 --interval 10 --scenario normal
  ```
- **Ràng buộc VPS Linux (MUST tuân thủ):**
  - Cấu hình tối thiểu theo spec §13.3: VPS Linux Ubuntu 24.04 LTS (`x86_64`), ≥ 2 vCPU, **2 GB RAM** (khuyến nghị 4 GB), SSD ≥ 40 GB, swap 2 GB.
  - VPS phổ thông thường dùng **vCPU chia sẻ (shared/burstable vCPU)** nên có thể bị giới hạn CPU nếu chạy tải cao liên tục kéo dài.
  - Chạy thử tải theo **từng đợt ngắn** (5–15 phút), đồng bộ đồng hồ NTP giữa laptop và VPS nếu đo độ trễ theo `payload.ts`, theo dõi `docker stats` trên VPS (RAM trần các container: TimescaleDB 640 MB, Worker 512 MB, API 384 MB, Mosquitto 128 MB, Caddy 128 MB), và **ghi rõ cấu hình VPS** (số vCPU, RAM, nhà cung cấp) cùng tải mô phỏng trong báo cáo.
- **Chỉ số cần đo và ghi nhận trong báo cáo (ghi rõ tải mô phỏng):**
  1. **Throughput (`msg/s`):** số bản tin/giây nhận được ở Mosquitto và số dòng ghi vào `readings` trong cửa sổ thử tải.
  2. **Độ trễ Ingest-to-DB (`p50`, `p95` ms):** chênh lệch từ thời điểm gateway phát telemetry tới khi `worker` commit xong vào TimescaleDB (có thể đo qua cột `created_at` hoặc log timing trong worker/harness benchmark).
  3. **Mức sử dụng CPU / RAM / DB connections:** đảm bảo không container nào OOM-kill và số kết nối DB giữ ổn định dưới `max_connections=50`.

## 8. Các Công cụ Dev khác trong `tools/`

### 8.1 `tools/seed_dev.py` (`python -m tools.seed_dev`)

- Tạo idempotent bộ dữ liệu phát triển hoàn chỉnh trên stack Docker dev đang chạy:
  - **Farm:** `"Nông trại Demo GreenHub"`.
  - **3 Users + `NotificationPref`:** `owner@greenhub.vn` (`owner`), `operator@greenhub.vn` (`operator`), `viewer@greenhub.vn` (`viewer`) — mật khẩu chung `greenhub123` (băm Argon2).
  - **Greenhouse:** `"Nhà kính Fomex 01"` (`"Phòng thí nghiệm IoT"`).
  - **2 Zones:** Zone 1 `"Zone 1 – Cà chua bi"` (`TEMPLATE_TOMATO_DEMO_ID`, `pump_channel=1`), Zone 2 `"Zone 2 – Dâu tây"` (`TEMPLATE_STRAWBERRY_DEMO_ID`, `pump_channel=2`), hiệu chuẩn `2900 / 1300`. *(Cập nhật M4: dùng template `schema_version = 2` trong bộ 10 template 5 cây × `real`/`demo` và gán `area_m2` mặc định ví dụ `1.0` m² để thử được ngay luồng vụ trồng & dự báo năng suất.)*
  - **2 Paired Nodes:** `AA:BB:CC:DD:EE:01` (Zone 1) và `AA:BB:CC:DD:EE:02` (Zone 2).
  - **DeviceState:** `cfg_version_desired=1`, `cfg_version_reported=0`.
  - **Gateway + MQTT DynSec:** gọi `provision_gateway_mqtt` cấp user `gw_{gh.id.hex[:12]}`, tạo bản ghi `Gateway(is_simulated=True)`, phát `pg_notify` `"cfg_updated"`, và lưu thông tin ra `.dev-gateway.json`.

### 8.2 `tools/gen_vapid.py` (`python -m tools.gen_vapid`)

- Sinh cặp khóa EC đường cong `SECP256R1` bằng thư viện `cryptography`, encode dạng `urlsafe_b64` không có padding `=`, in ra hai biến `VAPID_PUBLIC_KEY` và `VAPID_PRIVATE_KEY` để chép vào `.env`.

### 8.3 `tools/gen_dev_certs.py` (`python -m tools.gen_dev_certs [LAN_IP]`)

- Giải pháp Python thuần đa nền tảng (chạy tốt trên Windows không cần Git Bash/OpenSSL) tương đương `deploy/scripts/gen-dev-certs.sh`.
- Sinh (hoặc tái sử dụng) CA `"GreenHub Dev CA"` (RSA 2048, hạn 3650 ngày) tại `deploy/certs/ca.{key,crt}` và ký `server.{key,crt}` (hạn 825 ngày, `ExtendedKeyUsage: SERVER_AUTH`, SAN gồm `DNS:localhost`, `DNS:mosquitto`, `IP:127.0.0.1`, và `IP:<LAN_IP>` nếu truyền đối số).

## 9. Kiểm thử & Xác nhận

```powershell
# 1. Unit test quy tắc an toàn Gateway (interlock, min_gap, max_total, expired, idempotency)
.venv\Scripts\pytest.exe platform/tests/test_gateway_sim_safety.py

# 2. Kiểm tra CLI dry-run (không cần stack Docker)
.venv\Scripts\python.exe -m tools.simulator --dry-run --farms 10 --gateways 10 --scenario dry_down

# 3. Sinh dữ liệu huấn luyện tổng hợp tất định (khi đã hiện thực synth-yield & growth.py ở M5)
.venv\Scripts\python.exe -m tools.simulator synth-yield --greenhouses 200 --cycles-per-gh 5 --seed 42 --out data/synthetic_yield.csv

# 4. Chạy 1 gateway dev dùng .dev-gateway.json trên local stack
.venv\Scripts\python.exe -m tools.simulator --interval 10 --scenario humid_spike --insecure

# 5. Integration test full pipeline (cần Docker dev stack đang chạy)
.venv\Scripts\pytest.exe -v -m integration platform/tests/test_m2_integration.py
```
