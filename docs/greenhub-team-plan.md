# GreenHub – Kế hoạch triển khai cho nhóm

Tài liệu theo dõi tiến độ cho đồ án môn IoT: nền tảng IoT chuyên biệt cho nhà kính thông minh. Bao gồm phần tổng quan hệ thống (để cả nhóm cùng hiểu), phần cứng, lộ trình 6 tuần, kịch bản demo/video, kiểm thử, rủi ro và checklist nộp bài.

Tài liệu đồng hành: `greenhub-spec.md` (đặc tả kỹ thuật chi tiết cho Coding agent: topic MQTT, schema CSDL, API, thuật toán...). Khi cần chi tiết kỹ thuật, tra ở đó.

---

## 1. Mục tiêu và yêu cầu chấm điểm

Sản phẩm demo (6 điểm), có prototype bằng bìa fomex:

| Tiêu chí | Điểm | Cách đáp ứng |
|---|---|---|
| Ý tưởng | 1 | Nền tảng IoT đa tenant: quyết định ở server, quản lý thiết bị từ xa, phân tích dữ liệu đa nhà kính. Không phải tự động hoá nhúng |
| Kiến trúc IoT | 2 | Node → ESP-NOW → Gateway → MQTT TLS → VPS (Docker Compose) → Web console |
| Tự xây IoT platform | 1 | Firmware node/gateway, backend, web console đều tự viết. Không dùng Blynk/ThingsBoard/AWS IoT Core |
| Độ hoàn thiện | 1 | Prototype chạy trọn vòng: cảm biến → quyết định → chấp hành → cảnh báo; đủ kịch bản demo |
| AI/ML hoặc server | 1 | Làm cả hai: AI dự đoán năng suất & gợi ý cây trồng (dữ liệu nhiều nhà kính) và triển khai trên VPS Linux |
| Video demo 5–7 phút có thuyết minh | −0,5 nếu thiếu | Kịch bản ở mục 8 |

---

## 2. Tổng quan hệ thống (đã thống nhất)

### 2.1 Ý tưởng
**GreenHub** là nền tảng IoT chuyên biệt cho giám sát và điều khiển nhà kính đa vùng, đa loại cây. Nhà kính mini bằng fomex là một "site" thật; các farm/nhà kính khác được script giả lập đăng ký và gửi dữ liệu qua đúng luồng của thiết bị thật.

Vì sao đây là IoT chứ không phải nhúng/tự động hoá:
- Vòng quyết định nằm ở **server (VPS)**; ngưỡng/crop profile chỉnh từ xa trên web rồi đồng bộ xuống gateway. Vi điều khiển chỉ giữ failsafe.
- Có **quản lý thiết bị**: cấp phát, ghép node vào zone, online/offline (LWT), RSSI, last seen, đổi chu kỳ đo/hiệu chuẩn từ xa.
- **Đa tenant**: nhiều farm dùng chung một nền tảng, dữ liệu tách theo `farm_id`.
- **Phân tích dữ liệu liên nhà kính**: gộp dữ liệu khí hậu & năng suất thu hoạch từ nhiều nhà kính để huấn luyện mô hình dự báo năng suất và gợi ý cây trồng phù hợp với khí hậu hiện tại của từng nhà kính.

### 2.2 Kiến trúc

```
 Node 1 (Zone 1) ─┐
 Node 2 (Zone 2) ─┴─ ESP-NOW ─► Gateway ESP32 + relay 4 kênh
                                    │ MQTT over TLS :8883
                                    ▼
                        VPS Linux (Docker Compose)
          Mosquitto (TLS+ACL) ─ TimescaleDB ─ api + worker (FastAPI)
          Caddy (HTTPS) ─► Web console (React PWA, Web Push)
```

| Khối | Công nghệ |
|---|---|
| Node ×2 | ESP32 + cảm biến ẩm đất + AHT20 (+ BH1750 ở 1 node); PlatformIO/Arduino; ESP-NOW |
| Gateway | ESP32 + relay 4 kênh; ESP-NOW → MQTT TLS; failsafe, interlock, hàng đợi RAM |
| Broker | Mosquitto (TLS, user + ACL theo gateway) |
| Backend | Python FastAPI, hai tiến trình `api` + `worker`, PostgreSQL + TimescaleDB |
| Web | React + Vite + TypeScript, PWA, Web Push (10 trang) |
| AI | scikit-learn, LightGBM; huấn luyện offline (`ml/train.py`), suy luận trong worker |
| Server | VPS Linux (Ubuntu 24.04 LTS, ≥ 2 vCPU, 2 GB RAM), Docker Compose, Caddy, DuckDNS/tên miền riêng |

### 2.3 Các module platform
Device Registry & Provisioning · Device Shadow/Config · Ingestion · Rule & Control Engine · Command Service · Alert Service · Notification Service · Quản lý vụ trồng (`crop_cycles`) · Analytics (AI) · API/Auth/Tenant.

### 2.4 Thông báo (chỉ trên web)
In-app (WebSocket) → **Web Push** (service worker + VAPID) → email (leo thang alert `critical` chưa xác nhận) → buzzer tại gateway. Không dùng Telegram, không dùng FCM, không làm app di động. iPhone chỉ nhận push khi Add to Home Screen.

### 2.5 Logic điều khiển (tóm tắt)
- **Tưới:** hysteresis theo zone (bật khi dưới ngưỡng min với thời lượng `irrigation.max_run_s`, tắt sớm khi đạt max), giới hạn khoảng nghỉ/tổng mỗi giờ/thời gian chờ đất thấm (`soil_settle_s`).
- **Quạt:** bật khi VPD thấp kéo dài (nguy cơ nấm) hoặc nhiệt độ cao (thời lượng `fan.min_on_s`, lặp lại nếu điều kiện còn). **Máy tạo ẩm** bật tay hoặc auto khi VPD cao.
- **Interlock:** quạt và máy tạo ẩm không chạy cùng lúc; quạt bật vì rủi ro thì ép tắt máy tạo ẩm (kể cả đang manual) và khoá `mist.lockout_s`.
- Mọi lệnh bật đều có thời lượng; gateway tự tắt khi hết giờ. Mất kết nối server hơn 60 s thì failsafe cục bộ.
- Chỉ có **một chiến lược điều khiển duy nhất** (hysteresis cố định); AI **không** tham gia điều khiển thiết bị.

### 2.6 Kiểm tra chất lượng dữ liệu & Bài toán AI duy nhất

- **Kiểm tra chất lượng dữ liệu (luật, MUST):** gắn nhãn `ok / stuck / spike / dropout / out_of_range`, đối chiếu node lân cận → loại dữ liệu xấu khỏi điều khiển, tổng hợp đặc trưng khí hậu và huấn luyện.
- **Bài toán AI duy nhất – Dự đoán năng suất & Gợi ý cây trồng (`task = 'yield'`):**

| Ứng dụng | Đầu vào | Đầu ra |
|---|---|---|
| **1. Dự báo năng suất vụ đang trồng** (`yield_forecast`) | Đặc trưng khí hậu từ đầu vụ tới hiện tại (ẩm đất thực tế) + `crop_code` | `relative_yield` → nhân `reference_kg_m2` ra `kg/m²` kèm khoảng tin cậy `p10–p90` |
| **2. Gợi ý cây nên trồng** (`crop_recommendation`) | Đặc trưng khí hậu nhà kính cửa sổ gần nhất (`recommend_window_h`), đặt ẩm đất ở trung điểm tối ưu của từng cây (giả định tưới đủ) | Xếp hạng top-3 cây ứng viên (`Cà chua bi`, `Dâu tây`, `Xà lách`, `Dưa leo`, `Ớt chuông`) theo `relative_yield` + tối đa 3 lý do tiếng Việt |

Nguyên tắc: **một mô hình LightGBM toàn cục** học từ dữ liệu **gộp nhiều nhà kính** (`synthetic` là nguồn huấn luyện chính, `sim` từ simulator nhiều vùng khí hậu, `real` từ vụ xà lách thật trên mô hình, MAY `public`); chia train/val/test **theo nhà kính** (70/15/15, test là các nhà kính chưa từng thấy); so sánh với 2 baseline **B0** (median theo cây) và **B1** (Ridge); chỉ kích hoạt khi thắng cả B0, B1 và bản đang chạy về MAE trên test; báo cáo tách riêng từng nguồn (`real` báo cáo trung thực). Dữ liệu `yield_samples` không bao giờ lộ qua API.

### 2.7 Phạm vi KHÔNG làm
Telegram, FCM, app di động, LLM, RLS (có thể thêm sau), OTA, CO₂/PAR/MLX90614/DS18B20, rèm cắt nắng, 4G, pin + pin mặt trời, Grafana, dịch vụ cloud managed (AWS IoT Core, RDS, Lambda…), học tăng cường, phân loại bệnh từ ảnh, *federated learning* (huấn luyện tập trung từ dữ liệu nhiều nhà kính là **trong phạm vi**), điều khiển thích nghi bằng ML (`adaptive`), dự báo rủi ro bằng ML (`risk_forecast`), phản hồi đúng/sai cảnh báo.

---

## 3. Phân công (work package)

Điền tên người phụ trách; có thể gộp WP nếu nhóm ít người.

| WP | Nội dung | Người phụ trách |
|---|---|---|
| WP1 | Phần cứng và mô hình vật lý (mua linh kiện, lắp node/gateway/tủ relay, làm hộp fomex, hiệu chuẩn cảm biến) | ____ |
| WP2 | Firmware node + gateway (ESP-NOW, MQTT TLS, lệnh/ACK, failsafe, captive portal) | ____ |
| WP3 | Platform backend (MQTT ingest, DB, rule engine, command, alert, notify, `crop_cycles`, API, provisioning) | ____ |
| WP4 | Web console PWA (10 trang: dashboard, zone + khung vụ/năng suất, điều khiển, thiết bị, crop profile, cảnh báo, Gợi ý cây trồng, Mô hình AI, Web Push) | ____ |
| WP5 | AI/Data (`climate_features`, bộ sinh `synthetic`, `ml.dataset`/`ml.train`/`evaluate`, suy luận năng suất & gợi ý trong worker, vụ xà lách thật) | ____ |
| WP6 | DevOps/VPS, simulator đa vùng khí hậu & thử tải, kiểm thử tích hợp, video, báo cáo | ____ |

---

## 4. Lộ trình 6 tuần

Mỗi tuần kết thúc bằng một milestone (M1–M6, trùng `greenhub-spec.md` mục 16). Đánh dấu `[x]` khi xong.

### Tuần 1 – M1: Phần cứng và đường dữ liệu cơ bản
- [ ] (WP1) Mua linh kiện (mục 7), kiểm tra từng cảm biến
- [ ] (WP1) Lắp node 1, node 2 trên breadboard; hiệu chuẩn ẩm đất 2 điểm (khô/ướt)
- [ ] (WP1) Lắp tủ gateway: relay + bơm/quạt/máy tạo ẩm + diode + tụ + nguồn 5 V
- [ ] (WP2) Node: đọc cảm biến, đóng gói `TelemetryPkt`, gửi ESP-NOW, tìm kênh tự động
- [ ] (WP2) Gateway: nhận ESP-NOW, publish MQTT lên broker chạy trên laptop, nhận `cmd` điều khiển relay
- [ ] (WP6) Dựng repo, Docker Compose dev (Mosquitto + Timescale)
- **Đạt M1 khi:** số liệu 2 node hiện trên broker; gửi lệnh MQTT thủ công bật/tắt được 4 relay; relay tắt khi boot.

### Tuần 2 – M2: Ingestion, lệnh/ACK, shadow
- [ ] (WP3) Schema DB + Alembic; ingestion → `readings`, tính VPD
- [ ] (WP3) Kiểm tra chất lượng dữ liệu (luật) → gắn `quality`
- [ ] (WP3) Command Service: `cmd → ack`, trạng thái lệnh, `device_state` (shadow), publish `cfg` retained
- [ ] (WP2) Gateway: ACK, interlock, giới hạn thời gian, tự tắt khi hết `duration_s`, LWT/`status`
- [ ] (WP1) Hoàn thiện mô hình fomex (hộp, cửa sổ nhựa, lỗ quạt/ống hơi/dây, bồn nước)
- [ ] (WP6) Unit test VPD/DLI/quality
- **Đạt M2 khi:** dữ liệu vào DB đúng; gọi API/script tạo lệnh → relay chạy → ACK cập nhật `reported`; ngắt gateway thì `status` offline qua LWT.

### Tuần 3 – M3: Web console cơ bản, rule engine, alert, Web Push (localhost)
- [ ] (WP3) Rule engine hysteresis cố định (tưới, quạt, máy tạo ẩm, interlock, auto/manual)
- [ ] (WP3) Alert Service: dedupe, vòng đời, leo thang; API + JWT + vai trò; CRUD `crop_cycles` cơ bản
- [ ] (WP4) Web: đăng nhập, dashboard zone (biểu đồ realtime qua WebSocket, nút Bắt đầu vụ/Thu hoạch), điều khiển, crop profile (10 template `schema_version=2`)
- [ ] (WP4) PWA + service worker + đăng ký Web Push; thử trên localhost
- [ ] (WP2) Gateway: failsafe cục bộ, buffer RAM, nhận `cfg` và đẩy xuống node
- [ ] (WP6) **Thuê VPS Linux** (mục 6), trỏ tên miền/DuckDNS, cài Ubuntu + swap + `ufw` + SSH key + Docker
- **Đạt M3 khi:** từ web bật quạt/bơm và thấy trạng thái `pending → applied`; kịch bản A chạy cục bộ (VPD thấp → quạt bật, máy tạo ẩm bị ép tắt, alert hiện trên web và thông báo push trên localhost).

### Tuần 4 – M4: Provisioning, deploy VPS, simulator, bắt đầu vụ thật
- [ ] (WP3) Provisioning: tạo gateway + credential MQTT (Dynamic Security), ghép node lạ vào zone (fallback: nhập MAC tay)
- [ ] (WP2) Gateway: captive portal, TLS với kiểm tra chứng chỉ, kết nối bằng tên miền
- [ ] (WP6) Triển khai VPS: Docker Compose prod (chỉ publish 80/443/8883), Caddy HTTPS, Mosquitto TLS, cron `backup.sh` (`pg_dump` + `/models`)
- [ ] (WP4) Thử Web Push trên **điện thoại thật** qua HTTPS (iPhone: Add to Home Screen)
- [ ] (WP6) Simulator: đăng ký farm B, C qua API với vùng khí hậu khác nhau (`dalat`, `hcm`, ...), publish qua TLS, tạo vụ + thu hoạch mẫu `sim`
- [ ] (WP1, WP5) **Bắt đầu vụ xà lách baby leaf thật** trên 2 zone trong nhà kính mini (hoặc từ sớm hơn nếu phần cứng xong sớm; ghi `started_at`, `area_m2`)
- **Đạt M4 khi:** gateway thật kết nối VPS qua TLS; web truy cập qua HTTPS; push tới điện thoại; farm giả lập hiển thị và cô lập đúng; vụ thật bắt đầu ghi dữ liệu khí hậu liên tục.

### Tuần 5 – M5: AI dự đoán năng suất & gợi ý cây trồng, thử tải
- [ ] (WP5) `platform/core/climate_features.py` (`feature_version = 1`), dùng chung cho `worker`, `ml/`, `tools/simulator`
- [ ] (WP5) Bộ sinh dữ liệu `synthetic` (`tools/simulator/growth.py` + `crops_growth.json` + `synth-yield`), nhập `ml.dataset import`, huấn luyện LightGBM + B0 + B1 (`ml.train` & `ml.evaluate`) trên chia tập theo nhà kính
- [ ] (WP3) Worker inference: nạp model active, `yield_forecast`, `crop_recommendation` (kèm lý do tiếng Việt, OOD/`low_confidence`), `cycle_harvested → yield_samples`, `recommend` qua NOTIFY
- [ ] (WP4) Khung AI ở trang Zone, trang **Gợi ý cây trồng**, trang **Mô hình AI** (metrics vs B0/B1, theo cây, theo `source`, Top-1/NDCG@3, drift)
- [ ] (WP6) Thử tải simulator 50–100 gateway trỏ lên VPS; đo bản tin/s, độ trễ p50/p95, CPU/RAM (chạy theo đợt ngắn)
- [ ] (WP3) Email leo thang alert `critical` chưa ack
- **Đạt M5 khi:** mô hình active thắng B0 & B1 trên nhà kính chưa từng thấy; trang Zone hiện năng suất dự kiến, trang Gợi ý hiện top-3 hợp lý theo vùng khí hậu; có số liệu thử tải VPS.

### Tuần 6 – M6: Thu hoạch vụ thật, chạy thử, quay video, nộp bài
- [ ] (WP1, WP5) Thu hoạch vụ xà lách thật, cân khối lượng tươi, nhập `harvest` trên web → sinh mẫu `real` vào `yield_samples` và báo cáo sai số thực tế trung thực
- [ ] (cả nhóm) Chạy thử trọn kịch bản A/B/C/D/E ít nhất 2 lần theo kịch bản video
- [ ] (WP6) Quay và dựng video 5–7 phút có thuyết minh
- [ ] (WP6) Kéo bản sao lưu DB (`pg_dump`), `/models`, dữ liệu và video về máy nhóm
- [ ] (cả nhóm) Báo cáo (ý tưởng, kiến trúc, platform, AI dự đoán năng suất/gợi ý, kết quả test, hạn chế)
- [ ] (WP1) Hoàn thiện thẩm mỹ mô hình, nhãn dán các khối
- **Đạt M6 khi:** đủ checklist nộp bài (mục 10).

**Việc có thể trượt cần canh:** (1) Web Push trên điện thoại (thử từ tuần 4, không dồn sau); (2) vụ xà lách baby leaf thật cần ~3–4 tuần để thu hoạch cân tươi (cần trồng sớm ngay khi mô hình/cảm biến chạy ổn, hoặc dự phòng nếu chưa kịp thu hoạch thì dùng dữ liệu vụ đang chạy để demo `yield_forecast` và nói rõ trạng thái vụ thật); (3) sinh dữ liệu `synthetic` và chốt bảng 5 cây ứng viên ngay đầu tuần 5.

---

## 6. Kế hoạch VPS

Không dùng dịch vụ cloud managed; triển khai toàn bộ Docker Compose trên **một VPS Linux** (nhà cung cấp bất kỳ trong nước hoặc quốc tế có IPv4 công khai tĩnh và không chặn cổng 80/443/8883).

| Hạng mục | Giá trị |
|---|---|
| Cấu hình tối thiểu | 2 vCPU, **2 GB RAM** (khuyến nghị **4 GB RAM**), SSD ≥ 40 GB, x86_64 |
| Hệ điều hành & Swap | Ubuntu 24.04 LTS + swap 2 GB |
| Mạng & Tên miền | IPv4 công khai tĩnh; tên miền riêng hoặc DuckDNS (bản ghi A trỏ về IP VPS) |
| Chi phí ước tính | Khoảng **120.000–250.000 VNĐ/tháng** (≈ 5–10 USD/tháng tuỳ nhà cung cấp và gói 2–4 GB RAM) |
| Không dùng | Dịch vụ cloud managed (AWS IoT Core, RDS, Lambda… hoặc tương đương) |

**Checklist VPS:**
- [ ] Chọn VPS cho phép mở cổng 80/443/8883, ưu tiên datacenter VN/Singapore
- [ ] Tạo user thường + `sudo`, tắt SSH root và mật khẩu (`PasswordAuthentication no`, `PermitRootLogin no`), cài `unattended-upgrades`, SHOULD bật `fail2ban`
- [ ] Cấu hình `ufw`: chỉ mở 22 (nên giới hạn IP nhóm), 80, 443, 8883; kiểm tra `docker-compose.prod.yml` **chỉ publish 80/443/8883** (không publish 1883, 5432 vì Docker publish bỏ qua `ufw`)
- [ ] Cài Docker Engine + Compose, tạo swap 2 GB, cấu hình `.env` (`DOMAIN`, `MQTT_PUBLIC_HOST`, `TZ=Asia/Ho_Chi_Minh`, ...), `docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.prod.yml up -d --build`
- [ ] Chứng chỉ Caddy Let's Encrypt + Mosquitto dùng lại file chứng chỉ, cron restart Mosquitto hàng tháng
- [ ] Cron `deploy/backup.sh` hằng ngày (`pg_dump` + `/models`, giữ 7 bản), kéo bản sao về máy nhóm bằng `rsync`/`scp`

**Lưu ý vCPU chia sẻ:** VPS phổ thông dùng vCPU chia sẻ; khi thử tải 50–100 gateway nên chạy theo đợt ngắn và ghi rõ cấu hình VPS trong báo cáo.

**Laptop:** môi trường phát triển (cùng file compose), sinh dữ liệu `synthetic`, huấn luyện mô hình `ml/train.py` (nếu VPS 2 GB RAM thiếu dư địa), chạy simulator.

---

## 7. Phần cứng

### 7.1 Danh sách linh kiện và chi phí (nghìn đồng, là ước lượng, cần kiểm tra giá khi mua)

| Nhóm | Linh kiện | SL | Thành tiền |
|---|---|---|---|
| **Node** | ESP32 DevKit (mua cùng loại cho cả node và gateway) | 2 | 160–220 |
| | Cảm biến ẩm đất điện dung v1.2 | 2 | 40–70 |
| | AHT20/AHT21 (hoặc SHT30 nếu giá gần nhau) | 2 | 50–120 |
| | BH1750 (chỉ 1 node) | 1 | 25–45 |
| | Breadboard mini, jumper, cáp USB | | 40–60 |
| | *Tổng node* | | **≈ 315–515** |
| **Gateway** | ESP32 DevKit | 1 | 80–110 |
| | Relay 4 kênh cách ly quang 5 V (kích mức thấp) | 1 | 50–90 |
| | Bơm chìm mini 3–6 V | 2 | 50–100 |
| | Ống silicone 1–2 m | | 20–40 |
| | Quạt 5 V (80 mm hoặc quạt USB) | 1 | 30–60 |
| | Máy tạo ẩm USB mini 5 V | 1 | 60–120 |
| | Nguồn 5 V 3 A (hoặc dùng củ sạc có sẵn) | 1 | 0–70 |
| | Diode 1N4007 ×4, tụ 1000 µF, buzzer, domino, hộp nhựa | | 60–100 |
| | *Tổng gateway* | | **≈ 350–690** |
| **Mô hình** | Bìa fomex, keo nến, băng keo | | 60–100 |
| | Tấm nhựa trong (cửa sổ) | | 20–40 |
| | 2 chậu nhỏ, xơ dừa, cây giống (tuỳ chọn), chai nước làm bồn | | 50–100 |
| | *Tổng mô hình* | | **≈ 130–240** |
| **Tổng** | | | **≈ 0,8–1,45 triệu** |

Tiết kiệm: tận dụng củ sạc, breadboard, dây, cáp USB có sẵn. Node cấp nguồn USB (không dùng pin/pin mặt trời); firmware vẫn hỗ trợ deep sleep để nói "battery-ready" trong báo cáo.

### 7.2 Đấu nối

**Node (ESP32):**

| Linh kiện | Chân |
|---|---|
| AHT20 + BH1750 (I2C, 0x38 và 0x23) | SDA = GPIO21, SCL = GPIO22, VCC = 3V3 |
| Ẩm đất AOUT | GPIO34 (ADC1; không dùng ADC2) |
| Ẩm đất VCC | GPIO25 (bật khi đo) |

**Gateway (ESP32 + relay 4 kênh):**

| Relay | Chân | Tải |
|---|---|---|
| IN1 | GPIO25 | Bơm zone 1 |
| IN2 | GPIO26 | Bơm zone 2 |
| IN3 | GPIO27 | Quạt |
| IN4 | GPIO33 | Máy tạo ẩm |
| Buzzer | GPIO23 | Cảnh báo cục bộ |

- Relay kích mức thấp: firmware `digitalWrite(pin, HIGH)` **trước** `pinMode(pin, OUTPUT)`.
- Mỗi tải: +5 V → COM, NO → cực dương tải, cực âm tải → GND. Bơm có **diode 1N4007 song song tải** (cathode, đầu có vạch, về phía +).
- Một nguồn 5 V chung (nối chung GND), **tụ 1000 µF** ở rail để bơm khởi động không làm ESP32 reset. Nếu vẫn reset thì tách nguồn cho bơm.
- Chỉ dùng điện áp thấp 5 V, không đụng 220 V.

### 7.3 Lắp mô hình
1. Hộp fomex khoảng 40×30×30 cm, một mặt gắn tấm nhựa trong, mép dán kín bằng băng keo. Hộp phải **gần kín** để độ ẩm tăng được.
2. Khoét lỗ: quạt hút ở thành hộp, ống hơi từ máy tạo ẩm, dây cảm biến và ống nước.
3. Trong hộp: 2 chậu, mỗi chậu 1 cảm biến ẩm đất + 1 AHT20 treo cao hơn mặt chậu, **xa miệng phun hơi ẩm**. Seal phần mép mạch cảm biến điện dung bằng epoxy/sơn.
4. Bồn nước (chai/hộp) để ngoài, 2 bơm nhúng bên trong, mỗi bơm một ống vào một chậu.
5. Gateway + relay để trong hộp nhựa đặt ngoài nhà kính, tránh khu vực ẩm.
6. Hiệu chuẩn ẩm đất: ghi giá trị ADC khi cảm biến ở không khí khô và khi cắm trong đất ướt; nhập vào cấu hình zone trên web.

### 7.4 Checklist phần cứng
- [ ] Mỗi node đọc đúng nhiệt độ/RH/ẩm đất; node 1 có lux
- [ ] 4 relay đóng/mở đúng kênh; relay tắt khi mới cấp điện
- [ ] Quạt hút đủ để RH giảm trong hộp; máy tạo ẩm làm RH tăng trong vài phút
- [ ] Bơm đưa nước vào đúng chậu, không rò điện
- [ ] Ổn định: chạy 1 giờ liên tục không reset, không mất gói bất thường

---

## 8. Kịch bản demo và video (6–7 phút, có thuyết minh)

| Thời gian | Nội dung |
|---|---|
| 0:00–0:45 | Bài toán, ý tưởng GreenHub, điểm khác biệt với tự động hoá |
| 0:45–1:45 | Kiến trúc và prototype thật: node → gateway → VPS (Docker Compose) → web/push |
| 1:45–2:30 | Web console: 2 zone với 2 crop profile và vụ đang trồng; chọn farm B, C để thấy đa tenant |
| 2:30–3:20 | **Kịch bản A:** bật máy tạo ẩm từ web → RH tăng, VPD giảm → rule engine bật quạt, ép tắt máy tạo ẩm → push hiện trên điện thoại, bấm vào mở trang zone |
| 3:20–4:10 | **Kịch bản B:** ẩm đất giảm → bơm chạy đúng hysteresis và giới hạn thời gian → chuyển Auto/Manual |
| 4:10–5:00 | **Kịch bản C:** rút dây cảm biến → `quality` lỗi, không tưới sai, alert; cắt Wi-Fi gateway → offline + failsafe, nối lại thì dữ liệu gửi bù và `cfg` đồng bộ |
| 5:00–6:45 | **Kịch bản E (AI) & Triển khai:** khung dự báo năng suất vụ trồng ở trang Zone; trang Gợi ý cây trồng trên nhà kính thật + các nhà kính giả lập ở vùng khí hậu khác nhau (`dalat` vs `hcm`), thay đổi khí hậu rồi bấm Làm mới; trang Mô hình AI (metrics trên nhà kính chưa thấy vs B0/B1); thử tải VPS, kết luận và hạn chế |

**Lưu ý chuẩn bị:**
- Đất khô chậm (hàng giờ). Cho kịch bản B: chuyển cảm biến sang chậu đất đã sấy khô, hoặc tua nhanh đoạn đã ghi. Quyết định trước khi quay và nói rõ trong video.
- Nên dùng điện thoại thật để thấy Web Push; quay màn hình điện thoại cùng cảnh nhà kính.
- Dùng hotspot điện thoại hoặc router riêng cho Wi-Fi (Wi-Fi trường có captive portal/WPA2-Enterprise thường không kết nối được).
- Chạy thử toàn bộ kịch bản ít nhất 2 lần trước khi quay; bật `demo` profile (thang thời gian đã thu nhỏ).
- Checklist quay: [ ] kịch bản có thuyết minh [ ] âm thanh rõ [ ] ghi lại số đo thử tải [ ] ghi rõ phần nào là dữ liệu thật/giả lập.

---

## 9. Kiểm thử

| ID | Nội dung | Kết quả mong đợi |
|---|---|---|
| T1 | VPD: T=20 °C, RH=94% (T_lá = T_khí) | ≈ 0.14 kPa |
| T2 | Khởi động gateway | Mọi relay tắt |
| T3 | Bật quạt khi máy tạo ẩm đang chạy | Máy tạo ẩm tắt, ACK có `side_effects` |
| T4 | Bật máy tạo ẩm khi quạt đang chạy | Lệnh bị `rejected` (`interlock`) |
| T5 | Bơm chạy quá `max_run` / vi phạm `min_gap` | Gateway chặn hoặc tự tắt |
| T6 | Mất kết nối server khi bơm đang chạy | Bơm vẫn tự tắt đúng thời lượng |
| T7 | Rút dây cảm biến ẩm đất (đọc ≈ 0) | `quality` lỗi; **không** tưới; alert `SENSOR_FAULT` |
| T8 | Mất Wi-Fi gateway > 60 s | `DEVICE_OFFLINE`; failsafe đúng giới hạn; online lại thì gửi bù dữ liệu |
| T9 | Đổi crop profile trên web | `cfg_version` tăng; gateway báo đã đồng bộ |
| T10 | Lệnh hết hạn (`expires_at`) | Gateway bỏ qua; lệnh `timeout`/`expired` |
| T11 | Alert `critical` không ack sau N phút | Gửi lại push + email |
| T12 | User farm A truy cập dữ liệu farm B | `403`/không thấy |
| T13 | Web Push khi đóng tab | Điện thoại/desktop nhận thông báo, bấm mở đúng trang zone |
| T14 | Mô hình mới không thắng B0/B1 hoặc bản active | Không được kích hoạt |
| T15 | Chia dữ liệu theo nhà kính (`greenhouse_key`) | Không nhà kính nào nằm ở cả train và test |
| T16 | Thay đổi khí hậu nhà kính thật rồi bấm Làm mới gợi ý | Khí hậu tóm tắt và xếp hạng cập nhật đúng |
| T17 | Thử tải 50–100 gateway giả lập lên VPS | Ghi bản tin/s, độ trễ p50/p95, CPU/RAM |

---

## 10. Checklist nộp bài (Definition of Done)

**Sản phẩm**
- [ ] Prototype fomex hoàn chỉnh, chạy ổn định (có vụ xà lách baby leaf thật hoặc dữ liệu vụ đang chạy)
- [ ] Đủ ba khối: IoT nodes, Gateway, Server trên VPS Linux
- [ ] Firmware node/gateway, backend, web console đều tự viết
- [ ] Các kịch bản demo A/B/C/D/E chạy trọn vòng; farm giả lập nhiều vùng khí hậu; cô lập tenant (`yield_samples` không lộ qua API)
- [ ] Web Push nhận được trên điện thoại thật
- [ ] Hệ thống khởi động sạch bằng `docker compose up -d`

**AI/Server**
- [ ] Mô hình dự đoán năng suất `yield` toàn cục có so sánh với baseline B0/B1 trên nhà kính chưa từng thấy (tách riêng phần `synthetic`, `sim`, `real`)
- [ ] Trang Gợi ý cây trồng và trang Mô hình AI hoạt động đầy đủ
- [ ] Số liệu thử tải trên VPS (ghi rõ cấu hình VPS)
- [ ] Triển khai trên VPS đang chạy ổn định

**Tài liệu**
- [ ] Video demo 5–7 phút có thuyết minh (thiếu bị trừ 0,5 điểm)
- [ ] Báo cáo có: ý tưởng, kiến trúc, mô tả platform, AI dự đoán năng suất & gợi ý cây trồng, kết quả test, hạn chế, giả định (T_lá = T_khí − 1 °C; thu nhỏ thang thời gian ở bộ `demo`; gợi ý giả định tưới đủ; ngưỡng sinh học là giá trị khởi tạo)
- [ ] Dữ liệu, mô hình, DB dump, video đã sao lưu về máy nhóm

---

## 11. Rủi ro và phương án dự phòng

| Rủi ro | Phương án |
|---|---|
| Wi-Fi trường có captive portal/WPA2-Enterprise, ESP32 không kết nối được (chỉ hỗ trợ 2.4 GHz) | Dùng hotspot điện thoại hoặc router riêng |
| ESP-NOW và kênh Wi-Fi lệch nhau | Node tự quét kênh 1–13 bằng `HELLO` và lưu NVS; kiểm tra khi đổi mạng |
| Bơm khởi động làm ESP32 reset | Diode, tụ 1000 µF ở rail 5 V; nếu vẫn lỗi tách nguồn cho bơm |
| Máy tạo ẩm USB phải bấm nút mới chạy sau khi cấp điện | Chọn loại tự chạy khi có điện, hoặc dùng module tạo sương |
| Cảm biến RH sai khi bị đọng nước | Đặt xa miệng phun; chờ phục hồi |
| Đất khô quá chậm cho demo | Chuyển cảm biến sang chậu đất sấy khô hoặc tua nhanh đoạn đã ghi (nói rõ trong video) |
| Thang thời gian nhà kính mini khác nhà kính thật | Dùng template `demo` có thời gian thu nhỏ; ghi rõ trong báo cáo |
| Mô hình ML không thắng baseline B0/B1 | Vẫn báo cáo trung thực; mô hình không được kích hoạt |
| Mẫu thu hoạch `real` ít (chỉ 1–2 vụ) | Nguồn huấn luyện chính là `synthetic` + `sim`; báo cáo metrics theo từng `source` (`real` tách riêng, trung thực) |
| Gợi ý sai khác khi cửa sổ demo < 24 h | Gắn nhãn `low_confidence=true` và giải thích rõ trên UI là ngoại suy ngắn hạn |
| Web Push không tới (iOS, chế độ Không làm phiền) | iOS: Add to Home Screen; giữ lớp email và buzzer; thử sớm từ tuần 4 |
| Docker publish cổng làm lộ Postgres/Mosquitto bỏ qua `ufw` | `docker-compose.prod.yml` chỉ publish 80/443/8883; kiểm tra bằng `nmap` từ ngoài |
| VPS 2 GB RAM thiếu bộ nhớ khi train hoặc build | Bật swap 2 GB; huấn luyện `ml/train.py` trên laptop rồi đưa artifact lên VPS |
| vCPU chia sẻ của VPS bị nghẽn khi thử tải | Chạy thử tải theo đợt ngắn; ghi rõ cấu hình VPS |
| Mất dữ liệu trên VPS | `backup.sh` hằng ngày (`pg_dump` + `/models`) và `rsync` về máy nhóm |
| Mất mạng/laptop sập khi demo | Gateway có buffer RAM + failsafe; demo chạy trên VPS; có video ghi sẵn dự phòng |

---

## 12. Điểm cần nhóm chốt

1. Phân công WP1–WP6 (mục 3).
2. Cảm biến nhiệt-ẩm: AHT20 hay SHT30 (tuỳ giá lúc mua).
3. Nhà cung cấp VPS cụ thể và cấu hình (2 GB hay 4 GB RAM).
4. Nhà cung cấp SMTP cho email leo thang.
5. Ghép node: tự phát hiện hay nhập MAC thủ công cho MVP.
6. Có dùng thêm bộ dữ liệu `public` (vd Autonomous Greenhouse Challenge) hay chỉ `synthetic` + `sim` + `real`.
7. Cây cho vụ thật (đề xuất xà lách baby leaf) và cách cân/ghi năng suất; danh sách 5 cây ứng viên.
8. Có thêm cảnh báo `MAINTENANCE` / `YIELD_FORECAST_LOW` hay không (tuỳ chọn, MAY).
9. Kịch bản B dùng cách nào: chậu đất sấy khô hay tua nhanh đoạn ghi sẵn.
